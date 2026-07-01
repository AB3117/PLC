from __future__ import annotations

import json
import os
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
DASHBOARD_DIR = PACKAGE_DIR.parent
PROJECT_DIR = DASHBOARD_DIR.parent
CONFIG_PATHS = (
    PROJECT_DIR / "plcsim" / "config.json",
    DASHBOARD_DIR / "config.json",
)

DEFAULT_CONFIG = {
    "plc": {"enabled": True, "ip": "192.168.1.5", "port": 502, "device_id": 1},
    "simulator": {"machine_count": 1, "update_interval": 1.0, "register_block_size": 10},
    "tags": [
        {
            "name": "status",
            "label": "Status",
            "type": "bitfield",
            "register_offset": 0,
            "bits": {
                "power": 0,
                "auto": 1,
                "running": 2,
                "estop": 3,
                "alarm": 4,
                "door_open": 5,
            },
        },
        {
            "name": "speed",
            "label": "Speed",
            "type": "analog",
            "register_offset": 1,
            "unit": "RPM",
            "min": 0,
            "max": 100,
            "warn_high": 85,
            "alarm_high": 95,
        },
        {
            "name": "temperature",
            "label": "Temperature",
            "type": "analog",
            "register_offset": 2,
            "unit": "deg C",
            "min": 0,
            "max": 100,
            "warn_high": 55,
            "alarm_high": 70,
        },
        {
            "name": "vibration",
            "label": "Vibration",
            "type": "analog",
            "register_offset": 3,
            "unit": "mm/s",
            "min": 0,
            "max": 50,
            "warn_high": 30,
            "alarm_high": 40,
        },
        {
            "name": "load",
            "label": "Load",
            "type": "analog",
            "register_offset": 4,
            "unit": "%",
            "min": 0,
            "max": 100,
            "warn_high": 85,
            "alarm_high": 95,
        },
        {
            "name": "cycle_count",
            "label": "Cycle Count",
            "type": "counter",
            "register_offset": 5,
            "unit": "cycles",
        },
    ],
}

STATUS_BITS = {
    "power": 0,
    "auto": 1,
    "running": 2,
    "estop": 3,
    "alarm": 4,
    "door_open": 5,
}

ANALOG_KEYS = ("speed", "temperature", "vibration", "load")
FLOOR_ZONES = ("Raw material", "Machining", "Assembly", "Inspection", "Dispatch")
REPORT_PERIODS = {
    "daily": ("Daily", 24 * 60 * 60),
    "weekly": ("Weekly", 7 * 24 * 60 * 60),
    "monthly": ("Monthly", 30 * 24 * 60 * 60),
    "yearly": ("Yearly", 365 * 24 * 60 * 60),
}


def merge_config(loaded: dict) -> dict:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    for section, values in loaded.items():
        if isinstance(values, dict) and isinstance(config.get(section), dict):
            config[section].update(values)
        else:
            config[section] = values

    for tag in config.get("tags", []):
        if tag.get("name") == "temperature":
            tag["unit"] = "deg C"
    return config


def load_config() -> dict:
    for path in CONFIG_PATHS:
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as file:
                return merge_config(json.load(file))
        except (OSError, json.JSONDecodeError):
            continue
    return merge_config({})


CONFIG = load_config()
PLC_IP = os.environ.get("PLC_IP", CONFIG["plc"].get("ip", "192.168.1.5"))
PLC_PORT = int(os.environ.get("PLC_PORT", CONFIG["plc"].get("port", 502)))
DEVICE_ID = int(os.environ.get("PLC_DEVICE_ID", CONFIG["plc"].get("device_id", 1)))
MACHINE_COUNT = int(os.environ.get("MACHINE_COUNT", CONFIG["simulator"].get("machine_count", 1)))
REGISTER_BLOCK_SIZE = int(
    os.environ.get("REGISTER_BLOCK_SIZE", CONFIG["simulator"].get("register_block_size", 10))
)
IDEAL_CYCLE_SECONDS = float(os.environ.get("IDEAL_CYCLE_SECONDS", "30"))
POLL_INTERVAL = float(os.environ.get("DASHBOARD_POLL_INTERVAL", "1"))
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "5000"))
