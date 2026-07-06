import sys
import os
import time
import threading

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
            return MockResponse(registers=[7, 78, 44, 19, 71, 3], is_error=False)
        else:
            return MockResponse(is_error=True)

# Mock inside poller module
import dashboard_app.poller
dashboard_app.poller.ModbusTcpClient = MockModbusTcpClient

from dashboard_app.poller import poll
from dashboard_app.state import state

# Start the poller in a daemon thread
t = threading.Thread(target=poll, daemon=True)
t.start()

# Let it run for 1.5 seconds
time.sleep(1.5)

print("--- State Snapshot ---")
print(f"Connected: {state['connection']['connected']}")
print(f"Error: {state['connection']['error']}")
print(f"Number of machines: {len(state['machines'])}")
for i, m in enumerate(state['machines']):
    print(f"Machine {i+1}: {m['name']} | State: {m['severity']} | Speed: {m['analogs']['speed']['value']}")
