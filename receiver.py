from pymodbus.client import ModbusTcpClient
import time

PLC_IP = "192.168.1.5"
PLC_PORT = 502
DEVICE_ID = 1

client = ModbusTcpClient(PLC_IP, port=PLC_PORT)

if not client.connect():
    print("Failed to connect to PLC")
    exit()

print("Connected to PLC\n")

try:
    while True:

        rr = client.read_holding_registers(
            address=0,
            count=6,
            device_id=DEVICE_ID
        )

        if rr.isError():
            print("Read Error")
        else:

            regs = rr.registers

            status = regs[0]

            power = bool(status & (1 << 0))
            auto = bool(status & (1 << 1))
            running = bool(status & (1 << 2))
            estop = bool(status & (1 << 3))
            alarm = bool(status & (1 << 4))
            door = bool(status & (1 << 5))

            print("=" * 60)
            print(f"Status Register : {status}")
            print(f"Power           : {power}")
            print(f"Auto Mode       : {auto}")
            print(f"Cycle Running   : {running}")
            print(f"E-Stop          : {estop}")
            print(f"Alarm           : {alarm}")
            print(f"Door Open       : {door}")
            print()
            print(f"Speed           : {regs[1]}")
            print(f"Temperature     : {regs[2]} °C")
            print(f"Vibration       : {regs[3]}")
            print(f"Load            : {regs[4]} %")
            print(f"Cycle Count     : {regs[5]}")
            print()

        time.sleep(1)

except KeyboardInterrupt:
    print("\nStopped")

finally:
    client.close()