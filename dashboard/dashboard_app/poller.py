from __future__ import annotations

import time

from pymodbus.client import ModbusTcpClient

from .config import DEVICE_ID, MACHINE_COUNT, PLC_IP, PLC_PORT, POLL_INTERVAL, REGISTER_BLOCK_SIZE
from .metrics import build_machine, build_plant, build_reports
from .state import now_iso, state, state_lock, update_connection


def read_holding_registers(client: ModbusTcpClient, address: int, count: int):
    attempts = (
        {"device_id": DEVICE_ID},
        {"slave": DEVICE_ID},
        {"unit": DEVICE_ID},
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


def poll():
    client = ModbusTcpClient(PLC_IP, port=PLC_PORT)
    while True:
        poll_time = time.time()
        machines = []
        error = None
        try:
            if not is_connected(client) and not client.connect():
                raise ConnectionError(f"Cannot connect to PLC at {PLC_IP}:{PLC_PORT}")

            for machine_id in range(MACHINE_COUNT):
                base_address = machine_id * REGISTER_BLOCK_SIZE
                response = read_holding_registers(client, address=base_address, count=6)
                if response.isError():
                    raise RuntimeError(f"PLC read failed at register {base_address}")
                registers = list(response.registers[:6])
                if len(registers) < 6:
                    raise RuntimeError(f"PLC returned {len(registers)} registers at {base_address}")
                machines.append(build_machine(machine_id, registers, poll_time))
        except Exception as exc:
            error = str(exc)
            try:
                client.close()
            except Exception:
                pass
            client = ModbusTcpClient(PLC_IP, port=PLC_PORT)

        with state_lock:
            state["timestamp"] = now_iso()
            if error:
                update_connection(False, error)
            else:
                update_connection(True, None)
                state["machines"] = machines
                state["plant"] = build_plant(machines)
                state["reports"] = build_reports(machines)

        time.sleep(POLL_INTERVAL)
