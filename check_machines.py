from pymodbus.client import ModbusTcpClient
import time

PLC_IP = "192.168.1.5"
PLC_PORT = 502
DEVICE_ID = 1
REGISTER_BLOCK_SIZE = 10
MAX_MACHINES_TO_CHECK = 15

def check_active_machines():
    client = ModbusTcpClient(PLC_IP, port=PLC_PORT)
    if not client.connect():
        print(f"[-] Failed to connect to PLC at {PLC_IP}:{PLC_PORT}")
        return

    print(f"[+] Connected to PLC at {PLC_IP}:{PLC_PORT}")
    print("Checking machine register blocks...\n")

    active_count = 0
    for machine_id in range(MAX_MACHINES_TO_CHECK):
        base_address = machine_id * REGISTER_BLOCK_SIZE
        try:
            # We attempt unit/slave parameters dynamically for pymodbus version compatibility
            response = None
            for key in ("device_id", "slave", "unit"):
                try:
                    response = client.read_holding_registers(
                        address=base_address,
                        count=6,
                        **{key: DEVICE_ID}
                    )
                    break
                except TypeError:
                    continue
            
            if response is None or response.isError():
                # This address range is unreadable or has no registers allocated
                continue

            regs = response.registers
            status = regs[0]
            power = bool(status & (1 << 0))
            running = bool(status & (1 << 2))
            speed = regs[1]

            # If the machine is powered on or running, or has speed > 0, it's active
            if power or running or speed > 0:
                active_count += 1
                state_str = "RUNNING" if running else "IDLE" if power else "OFF"
                print(f"✔ Machine {machine_id + 1:2d} (Address {base_address:3d}): "
                      f"State={state_str:<7} | Speed={speed:3d} RPM | Temp={regs[2]} °C | Cycles={regs[5]}")

        except Exception as e:
            # Skip errors (likely out of range addresses)
            continue

    print(f"\nSummary: Found {active_count} active machines on the PLC.")
    client.close()

if __name__ == "__main__":
    check_active_machines()
