from __future__ import annotations

import json
import threading
from datetime import datetime

from .config import CONFIG, DEVICE_ID, PLC_IP, PLC_PORT, REGISTER_BLOCK_SIZE


state_lock = threading.Lock()
polling_started = False
runtime: dict[int, dict] = {}

state = {
    "timestamp": None,
    "connection": {
        "connected": False,
        "error": "Waiting for first PLC poll",
        "plc_ip": PLC_IP,
        "port": PLC_PORT,
        "device_id": DEVICE_ID,
        "register_block_size": REGISTER_BLOCK_SIZE,
    },
    "plant": {},
    "machines": [],
    "reports": {},
    "events": [],
    "tags": CONFIG.get("tags", []),
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def snapshot() -> dict:
    with state_lock:
        return json.loads(json.dumps(state))


def update_connection(connected: bool, error: str | None = None):
    state["connection"].update(
        {
            "connected": connected,
            "error": error,
            "last_poll": now_iso() if connected else state["connection"].get("last_poll"),
        }
    )


def add_event(machine_name: str, level: str, message: str):
    event = {"time": now_iso(), "machine": machine_name, "level": level, "message": message}
    state["events"].insert(0, event)
    del state["events"][80:]
