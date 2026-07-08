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


def detect_machine_count(client: ModbusTcpClient, device_id: int, register_block_size: int) -> int:
    print("[INFO] Starting automatic machine detection on PLC...")
    count = 0
    # Scan up to 16 machines sequentially
    for machine_id in range(16):
        base_address = machine_id * register_block_size
        try:
            response = read_holding_registers(
                client,
                address=base_address,
                count=6,
                device_id=device_id,
            )
            if response.isError():
                break
            regs = list(response.registers[:6])
            if len(regs) < 6:
                break
            
            # Check if there is active data (power, running, or speed > 0)
            status = regs[0]
            power = bool(status & (1 << 0))
            running = bool(status & (1 << 2))
            speed = regs[1]
            
            if not (power or running or speed > 0):
                # No active machine data written here
                break
                
            count += 1
        except Exception:
            break
    print(f"[INFO] Automatically detected {count} machines on the PLC.")
    return max(1, count)


def poll():
    client = None
    last_plc_ip = None
    last_plc_port = None
    detected_machine_count = None
    poll_cycles = 0

    while True:
        poll_time = time.time()
        machines = []
        error = None

        # Load parameters dynamically from config.json
        plc_ip, plc_port, device_id, _, register_block_size, poll_interval = get_current_connection_params()

        # If IP or Port changed, close existing client and reset detection
        if client is not None and (plc_ip != last_plc_ip or plc_port != last_plc_port):
            try:
                client.close()
            except Exception:
                pass
            client = None
            detected_machine_count = None

        try:
            # Connect if client is not initialized or not connected
            if client is None:
                client = ModbusTcpClient(plc_ip, port=plc_port)
                last_plc_ip = plc_ip
                last_plc_port = plc_port
                detected_machine_count = None

            if not is_connected(client):
                if not client.connect():
                    raise ConnectionError(f"Cannot connect to PLC at {plc_ip}:{plc_port}")
                detected_machine_count = None  # Reset detection on new connection

            # Auto-detect machine count if not already done or periodically (every 30 cycles)
            poll_cycles += 1
            if detected_machine_count is None or poll_cycles >= 30:
                poll_cycles = 0
                detected_machine_count = detect_machine_count(client, device_id, register_block_size)

            # Try to read all registers in a single block using the detected count
            try:
                total_count = (detected_machine_count - 1) * register_block_size + 6
                response = read_holding_registers(
                    client,
                    address=0,
                    count=total_count,
                    device_id=device_id,
                )
                if response.isError():
                    raise RuntimeError(f"Contiguous read error: {response}")
                all_registers = list(response.registers[:total_count])
                if len(all_registers) < total_count:
                    raise RuntimeError(f"Returned only {len(all_registers)} registers, expected {total_count}")

                for machine_id in range(detected_machine_count):
                    base_idx = machine_id * register_block_size
                    registers = all_registers[base_idx : base_idx + 6]
                    machines.append(build_machine(machine_id, registers, poll_time, machine_total=detected_machine_count))
            except Exception as block_exc:
                print(f"[WARN] Contiguous block read failed: {block_exc}. Falling back to sequential machine polling.")
                # Fallback: poll machines individually
                for machine_id in range(detected_machine_count):
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
                    machines.append(build_machine(machine_id, registers, poll_time, machine_total=detected_machine_count))

        except Exception as exc:
            error = str(exc)
            detected_machine_count = None  # Reset detection on connection error
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
                client = None

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
