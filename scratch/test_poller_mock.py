import sys
import os

# Add dashboard to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dashboard")))

class MockResponse:
    def __init__(self, registers=None, is_error=False):
        self.registers = registers or []
        self._is_error = is_error
    
    def isError(self):
        return self._is_error

class MockModbusTcpClient:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.connected_state = False

    def connect(self):
        self.connected_state = True
        return True

    def close(self):
        self.connected_state = False

    def read_holding_registers(self, address, count, **kwargs):
        if address == 0:
            # Succeeded read for Machine 1
            return MockResponse(registers=[7, 78, 44, 19, 71, 3], is_error=False)
        else:
            # Fails for Machine 2 (address 10) and Machine 3 (address 20)
            return MockResponse(is_error=True)

# Test original poller behavior
def test_original():
    print("Testing original poller behavior...")
    # Mocking ModbusTcpClient inside poller
    import dashboard_app.poller
    dashboard_app.poller.ModbusTcpClient = MockModbusTcpClient
    
    # We will simulate the main loop body of poll()
    # Let's import the necessary variables and run
    from dashboard_app.poller import read_holding_registers, get_current_connection_params
    from dashboard_app.metrics import build_machine
    
    plc_ip, plc_port, device_id, machine_count, register_block_size, poll_interval = get_current_connection_params()
    # Force parameters to test
    machine_count = 3
    register_block_size = 10
    
    machines = []
    error = None
    poll_time = 1234567.0
    
    try:
        client = MockModbusTcpClient(plc_ip, port=plc_port)
        if not client.connect():
            raise ConnectionError("Cannot connect")
        
        for machine_id in range(machine_count):
            base_address = machine_id * register_block_size
            response = read_holding_registers(
                client,
                address=base_address,
                count=6,
                device_id=device_id,
            )
            if response.isError():
                raise RuntimeError(f"PLC read failed at register {base_address}")
            registers = list(response.registers[:6])
            machines.append(build_machine(machine_id, registers, poll_time, machine_total=machine_count))
    except Exception as exc:
        error = str(exc)
        machines = []
        
    print(f"Error occurred: {error}")
    print(f"Machines polled: {machines}")

if __name__ == "__main__":
    test_original()
