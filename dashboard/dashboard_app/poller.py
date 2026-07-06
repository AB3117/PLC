from __future__ import annotations

import os
import time

from pymodbus.client import ModbusTcpClient

from .config import load_config
from .metrics import build_machine, build_plant, build_reports
from .state import now_iso, state, state_lock, update_connection


def read_holding_registers(client: ModbusTcpClient, address: int, count: int, device_id: int):
    attempts = (
        {"device_id": device_id},
        {"slave": device_id},
        {"unit": device_id},
        {},
    )
    last_error = None
    for kwargs in attempts:
        try:
            return client.read_holding_registers(address=address, count=count, **kwargs)
        except TypeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise RuntimeError("Could not read holding registers")


def is_connected(client: ModbusTcpClient) -> bool:
    connected = getattr(client, "connected", None)
    if callable(connected):
        return bool(connected())
    return bool(connected)


def get_current_connection_params():
    cfg = load_config()
    plc_ip = os.environ.get("PLC_IP", cfg["plc"].get("ip", "192.168.1.5"))
    plc_port = int(os.environ.get("PLC_PORT", cfg["plc"].get("port", 502)))
    device_id = int(os.environ.get("PLC_DEVICE_ID", cfg["plc"].get("device_id", 1)))
    machine_count = int(os.environ.get("MACHINE_COUNT", cfg["simulator"].get("machine_count", 1)))
    register_block_size = int(
        os.environ.get("REGISTER_BLOCK_SIZE", cfg["simulator"].get("register_block_size", 10))
    )
    poll_interval = float(os.environ.get("DASHBOARD_POLL_INTERVAL", "1.0"))
    return plc_ip, plc_port, device_id, machine_count, register_block_size, poll_interval


def poll():
    while True:
        poll_time = time.time()
        machines = []
        error = None

        # Load parameters dynamically from config.json
        plc_ip, plc_port, device_id, machine_count, register_block_size, poll_interval = get_current_connection_params()

        try:
            last_error = None
            for attempt in range(2):
                client = ModbusTcpClient(plc_ip, port=plc_port)
                try:
                    if not client.connect():
                        raise ConnectionError(f"Cannot connect to PLC at {plc_ip}:{plc_port}")

                    for machine_id in range(machine_count):
                        base_address = machine_id * register_block_size
                        try:
                            response = read_holding_registers(
                                client,
                                address=base_address,
                                count=6,
                                device_id=device_id,
                            )
                            if response.isError():
                                raise RuntimeError(f"Modbus error response: {response}")
                            registers = list(response.registers[:6])
                            if len(registers) < 6:
                                raise RuntimeError(f"Returned only {len(registers)} registers")
                        except Exception as exc:
                            print(f"[WARN] Failed to read registers for Machine {machine_id + 1} at address {base_address}: {exc}")
                            registers = [0, 0, 0, 0, 0, 0]
                        machines.append(build_machine(machine_id, registers, poll_time, machine_total=machine_count))
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    machines = []
                    if attempt == 0:
                        time.sleep(0.15)
                finally:
                    try:
                        client.close()
                    except Exception:
                        pass
            if last_error is not None:
                raise last_error
        except Exception as exc:
            error = str(exc)

        with state_lock:
            state["timestamp"] = now_iso()
            state["connection"].update({
                "plc_ip": plc_ip,
                "port": plc_port,
                "device_id": device_id,
                "register_block_size": register_block_size,
            })
            if error:
                update_connection(False, error)
            else:
                update_connection(True, None)
                state["machines"] = machines
                state["plant"] = build_plant(machines)
                state["reports"] = build_reports(machines)

        time.sleep(poll_interval)
