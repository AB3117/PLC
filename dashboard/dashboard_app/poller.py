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
    last_plc_ip = None
    last_plc_port = None
    client = None

    while True:
        poll_time = time.time()
        machines = []
        error = None

        # Load parameters dynamically from config.json
        plc_ip, plc_port, device_id, machine_count, register_block_size, poll_interval = get_current_connection_params()

        try:
            if client is None or plc_ip != last_plc_ip or plc_port != last_plc_port:
                if client is not None:
                    try:
                        client.close()
                    except Exception:
                        pass
                client = ModbusTcpClient(plc_ip, port=plc_port)
                last_plc_ip = plc_ip
                last_plc_port = plc_port

            if not is_connected(client) and not client.connect():
                raise ConnectionError(f"Cannot connect to PLC at {plc_ip}:{plc_port}")

            for machine_id in range(machine_count):
                base_address = machine_id * register_block_size
                response = read_holding_registers(client, address=base_address, count=6, device_id=device_id)
                if response.isError():
                    raise RuntimeError(f"PLC read failed at register {base_address}")
                registers = list(response.registers[:6])
                if len(registers) < 6:
                    raise RuntimeError(f"PLC returned {len(registers)} registers at {base_address}")
                machines.append(build_machine(machine_id, registers, poll_time, machine_total=machine_count))
        except Exception as exc:
            error = str(exc)
            try:
                if client is not None:
                    client.close()
            except Exception:
                pass
            client = None  # Re-create on next loop if error occurs

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

