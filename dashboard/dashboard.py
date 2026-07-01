from __future__ import annotations

import json
import math
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template_string
from pymodbus.client import ModbusTcpClient


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATHS = (BASE_DIR / "plcsim" / "config.json", BASE_DIR / "config.json")

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
            "unit": "°C",
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
IDEAL_CYCLE_SECONDS = float(os.environ.get("IDEAL_CYCLE_SECONDS", "30"))
POLL_INTERVAL = float(os.environ.get("DASHBOARD_POLL_INTERVAL", "1"))
FLOOR_ZONES = ("Raw material", "Machining", "Assembly", "Inspection", "Dispatch")
REPORT_PERIODS = {
    "daily": ("Daily", 24 * 60 * 60),
    "weekly": ("Weekly", 7 * 24 * 60 * 60),
    "monthly": ("Monthly", 30 * 24 * 60 * 60),
    "yearly": ("Yearly", 365 * 24 * 60 * 60),
}


def load_config() -> dict:
    for path in CONFIG_PATHS:
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as file:
                    loaded = json.load(file)
                return merge_config(loaded)
            except (OSError, json.JSONDecodeError):
                break
    return merge_config({})


def merge_config(loaded: dict) -> dict:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    for section, values in loaded.items():
        if isinstance(values, dict) and isinstance(config.get(section), dict):
            config[section].update(values)
        else:
            config[section] = values
    for tag in config.get("tags", []):
        if isinstance(tag.get("unit"), str):
            tag["unit"] = tag["unit"].replace("Â°C", "°C")
    return config


CONFIG = load_config()
PLC_IP = os.environ.get("PLC_IP", CONFIG["plc"].get("ip", "192.168.1.5"))
PLC_PORT = int(os.environ.get("PLC_PORT", CONFIG["plc"].get("port", 502)))
DEVICE_ID = int(os.environ.get("PLC_DEVICE_ID", CONFIG["plc"].get("device_id", 1)))
MACHINE_COUNT = int(os.environ.get("MACHINE_COUNT", CONFIG["simulator"].get("machine_count", 1)))
REGISTER_BLOCK_SIZE = int(
    os.environ.get("REGISTER_BLOCK_SIZE", CONFIG["simulator"].get("register_block_size", 10))
)

app = Flask(__name__)
state_lock = threading.Lock()

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

runtime = {}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def percent(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def seconds_label(seconds: float) -> str:
    seconds = int(max(0, seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def tag_meta(name: str) -> dict:
    for tag in CONFIG.get("tags", []):
        if tag.get("name") == name:
            return tag
    return {}


def get_machine_runtime(machine_id: int) -> dict:
    if machine_id not in runtime:
        runtime[machine_id] = {
            "runtime": 0.0,
            "run_time": 0.0,
            "idle_time": 0.0,
            "fault_time": 0.0,
            "alarm_events": 0,
            "last_ts": None,
            "last_cycle_count": None,
            "observed_cycles": 0,
            "last_alarm": False,
            "first_seen": time.time(),
        }
    return runtime[machine_id]


def floor_slot(machine_id: int) -> dict:
    machine_total = max(1, MACHINE_COUNT)
    columns = min(5, max(2, math.ceil(math.sqrt(machine_total))))
    rows = max(1, math.ceil(machine_total / columns))
    row, column = divmod(machine_id, columns)
    x = 12 if columns == 1 else 10 + (column / max(1, columns - 1)) * 80
    y = 50 if rows == 1 else 18 + (row / max(1, rows - 1)) * 64
    return {
        "x": round(x, 1),
        "y": round(y, 1),
        "zone": FLOOR_ZONES[row % len(FLOOR_ZONES)],
        "line": row + 1,
        "bay": column + 1,
    }


def machine_signal(status: dict, severity: str) -> dict:
    if status.get("running") and severity not in {"alarm", "offline"}:
        return {"state": "working", "label": "Working", "color": "green"}
    if severity in {"alarm", "offline"} or status.get("estop"):
        return {"state": "stopped", "label": "Stopped", "color": "red"}
    return {"state": "idle", "label": "Idle", "color": "amber"}


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


def parse_status(raw_status: int) -> dict:
    return {name: bool(raw_status & (1 << bit)) for name, bit in STATUS_BITS.items()}


def analog_health(key: str, value: int) -> str:
    meta = tag_meta(key)
    alarm_high = meta.get("alarm_high")
    warn_high = meta.get("warn_high")
    if alarm_high is not None and value >= alarm_high:
        return "alarm"
    if warn_high is not None and value >= warn_high:
        return "warning"
    return "normal"


def machine_severity(status: dict, analogs: dict) -> str:
    if status.get("estop") or status.get("alarm"):
        return "alarm"
    if any(item["health"] == "alarm" for item in analogs.values()):
        return "alarm"
    if status.get("door_open") or any(item["health"] == "warning" for item in analogs.values()):
        return "warning"
    if status.get("running"):
        return "running"
    if status.get("power"):
        return "idle"
    return "offline"


def add_event(machine_name: str, level: str, message: str):
    event = {"time": now_iso(), "machine": machine_name, "level": level, "message": message}
    state["events"].insert(0, event)
    del state["events"][80:]


def build_machine(machine_id: int, registers: list[int], poll_time: float) -> dict:
    status_raw, speed, temperature, vibration, load, cycle_count = registers[:6]
    status = parse_status(status_raw)
    machine_name = f"Machine {machine_id + 1}"

    counters = get_machine_runtime(machine_id)
    last_ts = counters["last_ts"] or poll_time
    elapsed = max(0.0, min(5.0, poll_time - last_ts))
    counters["last_ts"] = poll_time

    if status["power"]:
        counters["runtime"] += elapsed
    if status["running"]:
        counters["run_time"] += elapsed
    if status["power"] and status["auto"] and not status["running"] and not status["alarm"]:
        counters["idle_time"] += elapsed
    if status["alarm"] or status["estop"]:
        counters["fault_time"] += elapsed

    if status["alarm"] and not counters["last_alarm"]:
        counters["alarm_events"] += 1
        add_event(machine_name, "alarm", "PLC alarm bit went high")
    if status["estop"]:
        add_event(machine_name, "alarm", "Emergency stop bit is active")
    counters["last_alarm"] = status["alarm"]

    previous_cycle_count = counters["last_cycle_count"]
    cycle_delta = 0 if previous_cycle_count is None else max(0, cycle_count - previous_cycle_count)
    counters["last_cycle_count"] = cycle_count
    counters["observed_cycles"] += cycle_delta

    analogs = {
        "speed": build_analog("speed", speed),
        "temperature": build_analog("temperature", temperature),
        "vibration": build_analog("vibration", vibration),
        "load": build_analog("load", load),
    }

    powered = counters["runtime"]
    available_time = max(0.0, powered - counters["fault_time"])
    availability = 100.0 if powered <= 0 else available_time / powered * 100
    observed_cycles = counters["observed_cycles"]
    performance = 100.0 if powered <= 0 else (observed_cycles * IDEAL_CYCLE_SECONDS) / powered * 100
    quality = 100.0
    oee = availability * min(performance, 100.0) * quality / 10000
    uptime_span = max(1.0, poll_time - counters["first_seen"])
    cycles_per_hour = observed_cycles / uptime_span * 3600
    mtbf = powered / counters["alarm_events"] if counters["alarm_events"] else powered
    mttr = counters["fault_time"] / counters["alarm_events"] if counters["alarm_events"] else 0
    severity = machine_severity(status, analogs)
    signal = machine_signal(status, severity)
    return {
        "id": machine_id,
        "name": machine_name,
        "severity": severity,
        "signal": signal,
        "floor": floor_slot(machine_id),
        "register_base": machine_id * REGISTER_BLOCK_SIZE,
        "registers": registers,
        "status": status,
        "status_raw": status_raw,
        "analogs": analogs,
        "cycles": cycle_count,
        "produced_cycles": observed_cycles,
        "cycle_delta": cycle_delta,
        "metrics": {
            "runtime": round(powered, 1),
            "runtime_label": seconds_label(powered),
            "run_time": round(counters["run_time"], 1),
            "idle_time": round(counters["idle_time"], 1),
            "idle_label": seconds_label(counters["idle_time"]),
            "fault_time": round(counters["fault_time"], 1),
            "fault_label": seconds_label(counters["fault_time"]),
            "availability": percent(availability),
            "performance": percent(performance),
            "quality": percent(quality),
            "oee": percent(oee),
            "utilization": percent(counters["run_time"] / powered * 100 if powered else 0),
            "cycles_per_hour": round(cycles_per_hour, 1),
            "mtbf_label": seconds_label(mtbf),
            "mttr_label": seconds_label(mttr),
            "alarm_events": counters["alarm_events"],
            "working_label": seconds_label(counters["run_time"]),
        },
    }


def build_analog(key: str, value: int) -> dict:
    meta = tag_meta(key)
    minimum = float(meta.get("min", 0))
    maximum = float(meta.get("max", 100))
    span = max(1.0, maximum - minimum)
    return {
        "key": key,
        "label": meta.get("label", key.title()),
        "value": value,
        "unit": meta.get("unit", ""),
        "min": minimum,
        "max": maximum,
        "warn_high": meta.get("warn_high"),
        "alarm_high": meta.get("alarm_high"),
        "ratio": percent((value - minimum) / span * 100),
        "health": analog_health(key, value),
    }


def build_plant(machines: list[dict]) -> dict:
    if not machines:
        return {
            "machine_count": MACHINE_COUNT,
            "connected_machines": 0,
            "running": 0,
            "idle": 0,
            "alarms": 0,
            "stopped": 0,
            "total_cycles": 0,
            "produced_cycles": 0,
            "oee": 0,
            "availability": 0,
            "performance": 0,
            "quality": 100,
            "avg_speed": 0,
            "max_temperature": 0,
            "max_vibration": 0,
            "avg_load": 0,
        }

    totals = {
        "runtime": sum(m["metrics"]["runtime"] for m in machines),
        "fault_time": sum(m["metrics"]["fault_time"] for m in machines),
        "cycles": sum(m["cycles"] for m in machines),
        "produced_cycles": sum(m["produced_cycles"] for m in machines),
    }
    availability = (
        100.0
        if totals["runtime"] <= 0
        else max(0.0, (totals["runtime"] - totals["fault_time"]) / totals["runtime"] * 100)
    )
    performance = (
        100.0
        if totals["runtime"] <= 0
        else totals["cycles"] * IDEAL_CYCLE_SECONDS / totals["runtime"] * 100
    )
    quality = 100.0
    oee = availability * min(performance, 100.0) * quality / 10000

    return {
        "machine_count": MACHINE_COUNT,
        "connected_machines": len(machines),
        "running": sum(1 for m in machines if m["status"]["running"]),
        "idle": sum(1 for m in machines if m["severity"] == "idle"),
        "alarms": sum(1 for m in machines if m["severity"] == "alarm"),
        "stopped": sum(1 for m in machines if m["signal"]["state"] == "stopped"),
        "warnings": sum(1 for m in machines if m["severity"] == "warning"),
        "total_cycles": totals["cycles"],
        "produced_cycles": totals["produced_cycles"],
        "oee": percent(oee),
        "availability": percent(availability),
        "performance": percent(performance),
        "quality": percent(quality),
        "avg_speed": round(sum(m["analogs"]["speed"]["value"] for m in machines) / len(machines), 1),
        "max_temperature": max(m["analogs"]["temperature"]["value"] for m in machines),
        "max_vibration": max(m["analogs"]["vibration"]["value"] for m in machines),
        "avg_load": round(sum(m["analogs"]["load"]["value"] for m in machines) / len(machines), 1),
    }


def period_report(machines: list[dict], period_key: str, label: str, period_seconds: int) -> dict:
    if not machines:
        return {
            "key": period_key,
            "label": label,
            "cycles": 0,
            "runtime_label": "0s",
            "working_label": "0s",
            "idle_label": "0s",
            "stopped_label": "0s",
            "oee": 0,
            "availability": 0,
            "utilization": 0,
            "alarms": 0,
            "avg_load": 0,
            "bottleneck": "--",
            "leader": "--",
        }

    first_seen = min(get_machine_runtime(m["id"])["first_seen"] for m in machines)
    observed_window = max(1.0, time.time() - first_seen)
    scale = period_seconds / observed_window
    runtime_seconds = sum(m["metrics"]["runtime"] for m in machines)
    working_seconds = sum(m["metrics"]["run_time"] for m in machines)
    idle_seconds = sum(m["metrics"]["idle_time"] for m in machines)
    stopped_seconds = sum(m["metrics"]["fault_time"] for m in machines)
    produced_cycles = sum(m["produced_cycles"] for m in machines)
    alarm_events = sum(m["metrics"]["alarm_events"] for m in machines)
    availability = (
        100.0 if runtime_seconds <= 0 else (runtime_seconds - stopped_seconds) / runtime_seconds * 100
    )
    utilization = 0.0 if runtime_seconds <= 0 else working_seconds / runtime_seconds * 100
    performance = (
        100.0
        if runtime_seconds <= 0
        else produced_cycles * IDEAL_CYCLE_SECONDS / runtime_seconds * 100
    )
    oee = availability * min(performance, 100.0) / 100
    sorted_by_oee = sorted(machines, key=lambda item: item["metrics"]["oee"])

    return {
        "key": period_key,
        "label": label,
        "cycles": int(round(produced_cycles * scale)),
        "runtime_label": seconds_label(runtime_seconds * scale),
        "working_label": seconds_label(working_seconds * scale),
        "idle_label": seconds_label(idle_seconds * scale),
        "stopped_label": seconds_label(stopped_seconds * scale),
        "oee": percent(oee),
        "availability": percent(availability),
        "utilization": percent(utilization),
        "alarms": int(round(alarm_events * scale)),
        "avg_load": round(sum(m["analogs"]["load"]["value"] for m in machines) / len(machines), 1),
        "bottleneck": sorted_by_oee[0]["name"],
        "leader": sorted_by_oee[-1]["name"],
    }


def build_reports(machines: list[dict]) -> dict:
    return {
        key: period_report(machines, key, label, seconds)
        for key, (label, seconds) in REPORT_PERIODS.items()
    }


def update_connection(connected: bool, error: str | None = None):
    state["connection"].update(
        {
            "connected": connected,
            "error": error,
            "last_poll": now_iso() if connected else state["connection"].get("last_poll"),
        }
    )


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


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="SCADA-level PLC machine dashboard for live workshop-floor monitoring over Modbus TCP.">
<title>Workshop SCADA Dashboard</title>
<style>
:root{
  --bg:#070b10;
  --panel:#0d141c;
  --panel-2:#101923;
  --panel-3:#131f2a;
  --line:#223241;
  --line-soft:rgba(121,151,174,.18);
  --text:#edf4f7;
  --muted:#91a4b1;
  --dim:#596b77;
  --accent:#5dd6c7;
  --accent-2:#a9ffcb;
  --warn:#f0b75a;
  --alarm:#ff5f68;
  --ok:#51d88a;
  --idle:#7c8d99;
  --shadow:0 24px 70px rgba(0,0,0,.35);
  --radius:22px;
  --mono:"Cascadia Mono","SFMono-Regular",Consolas,monospace;
  --sans:"Segoe UI",Roboto,system-ui,-apple-system,sans-serif;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{
  margin:0;
  min-height:100dvh;
  color:var(--text);
  font-family:var(--sans);
  background:
    radial-gradient(circle at 14% 8%,rgba(93,214,199,.13),transparent 34rem),
    radial-gradient(circle at 84% 0%,rgba(240,183,90,.08),transparent 30rem),
    linear-gradient(135deg,#06090d 0%,#091018 47%,#05080c 100%);
}
body:before{
  content:"";
  position:fixed;
  inset:0;
  pointer-events:none;
  background-image:
    linear-gradient(rgba(255,255,255,.028) 1px,transparent 1px),
    linear-gradient(90deg,rgba(255,255,255,.024) 1px,transparent 1px);
  background-size:42px 42px;
  mask-image:linear-gradient(to bottom,rgba(0,0,0,.9),rgba(0,0,0,.24));
}
button{font:inherit}
.shell{position:relative;z-index:1;max-width:1760px;margin:0 auto;padding:22px}
.topbar{
  display:grid;
  grid-template-columns:minmax(260px,1fr) auto minmax(260px,1fr);
  gap:18px;
  align-items:center;
  padding:18px 20px;
  border:1px solid var(--line-soft);
  background:rgba(10,17,24,.76);
  backdrop-filter:blur(20px);
  border-radius:28px;
  box-shadow:var(--shadow);
}
.brand{display:flex;align-items:center;gap:14px}
.brand-mark{
  width:46px;height:46px;border-radius:15px;
  display:grid;place-items:center;
  color:#06100e;
  background:linear-gradient(145deg,var(--accent),var(--accent-2));
  font-weight:900;
  letter-spacing:-.08em;
  box-shadow:0 0 32px rgba(93,214,199,.25);
}
.eyebrow{margin:0 0 2px;color:var(--muted);font-size:11px;letter-spacing:.18em;text-transform:uppercase}
h1{margin:0;font-size:clamp(22px,2vw,34px);line-height:1;letter-spacing:-.055em}
.topology{display:flex;align-items:center;justify-content:center;gap:8px;color:var(--muted);font-size:12px;letter-spacing:.08em;text-transform:uppercase}
.node{border:1px solid var(--line);background:rgba(255,255,255,.035);border-radius:999px;padding:8px 10px;white-space:nowrap}
.link{width:34px;height:1px;background:linear-gradient(90deg,transparent,var(--accent),transparent)}
.connection{justify-self:end;display:flex;align-items:center;gap:12px;text-align:right}
.pill{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--line);border-radius:999px;padding:9px 12px;background:rgba(255,255,255,.035)}
.dot{width:10px;height:10px;border-radius:50%;background:var(--alarm);box-shadow:0 0 18px rgba(255,95,104,.5)}
.dot.connected{background:var(--ok);box-shadow:0 0 18px rgba(81,216,138,.5)}
.small{font-size:12px;color:var(--muted)}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.dashboard{display:grid;grid-template-columns:1.15fr .85fr;gap:18px;margin-top:18px}
.panel{
  border:1px solid var(--line-soft);
  background:linear-gradient(180deg,rgba(16,25,35,.82),rgba(10,16,23,.86));
  border-radius:var(--radius);
  box-shadow:var(--shadow);
  overflow:hidden;
}
.panel-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;padding:18px 18px 0}
.panel-title{margin:0;font-size:16px;letter-spacing:-.02em}
.panel-note{margin:5px 0 0;color:var(--muted);font-size:12px}
.kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;padding:18px}
.kpi{
  position:relative;
  min-height:126px;
  padding:16px;
  border-radius:18px;
  background:linear-gradient(145deg,rgba(255,255,255,.06),rgba(255,255,255,.022));
  border:1px solid var(--line-soft);
  overflow:hidden;
}
.kpi:after{
  content:"";
  position:absolute;
  inset:auto -20% -55% 20%;
  height:80%;
  background:radial-gradient(circle,rgba(93,214,199,.18),transparent 62%);
}
.kpi-label{position:relative;color:var(--muted);font-size:12px;letter-spacing:.12em;text-transform:uppercase}
.kpi-value{position:relative;margin-top:14px;font:700 clamp(28px,3vw,50px)/.9 var(--mono);letter-spacing:-.07em}
.kpi-unit{font-size:16px;color:var(--muted);letter-spacing:0}
.kpi-sub{position:relative;margin-top:14px;color:var(--dim);font-size:12px}
.overview{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:18px}
.operations{display:grid;grid-template-columns:1.25fr .75fr;gap:18px;margin-top:18px}
.floor-panel{position:relative;min-height:560px}
.floor-toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.signal-chip{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--line);border-radius:999px;padding:7px 9px;background:rgba(255,255,255,.03);font-size:11px;color:var(--muted)}
.signal-chip .dot{width:8px;height:8px;box-shadow:none}
.dot.working{background:var(--ok)}
.dot.idle{background:var(--warn)}
.dot.stopped{background:var(--alarm)}
.floor-map{
  position:relative;
  min-height:470px;
  margin:18px;
  border:1px solid rgba(121,151,174,.22);
  border-radius:20px;
  overflow:hidden;
  background:
    linear-gradient(90deg,rgba(255,255,255,.055) 1px,transparent 1px),
    linear-gradient(rgba(255,255,255,.04) 1px,transparent 1px),
    linear-gradient(135deg,rgba(15,27,38,.96),rgba(7,12,18,.98));
  background-size:64px 64px,64px 64px,auto;
}
.floor-map:before{
  content:"";
  position:absolute;
  inset:46% 4% auto;
  height:54px;
  border:1px dashed rgba(93,214,199,.28);
  border-left:0;
  border-right:0;
  background:linear-gradient(90deg,rgba(93,214,199,.05),rgba(240,183,90,.06));
}
.floor-zone{
  position:absolute;
  top:14px;
  color:rgba(237,244,247,.42);
  font:700 10px/1 var(--mono);
  letter-spacing:.14em;
  text-transform:uppercase;
}
.floor-machine{
  position:absolute;
  width:142px;
  min-height:112px;
  transform:translate(-50%,-50%);
  border:1px solid rgba(121,151,174,.25);
  border-radius:16px;
  color:var(--text);
  background:linear-gradient(180deg,rgba(19,31,42,.94),rgba(9,14,20,.94));
  box-shadow:0 18px 44px rgba(0,0,0,.34);
  cursor:pointer;
  text-align:left;
  padding:10px;
  transition:transform .22s ease,border-color .22s ease,box-shadow .22s ease;
}
.floor-machine:hover,.floor-machine:focus-visible{transform:translate(-50%,-52%);outline:none;border-color:rgba(93,214,199,.62);box-shadow:0 22px 56px rgba(93,214,199,.12)}
.floor-machine:active{transform:translate(-50%,-49%) scale(.99)}
.floor-machine.working{border-color:rgba(81,216,138,.55)}
.floor-machine.idle{border-color:rgba(240,183,90,.48)}
.floor-machine.stopped{border-color:rgba(255,95,104,.65);box-shadow:0 18px 54px rgba(255,95,104,.14)}
.machine-shape{
  position:relative;
  height:44px;
  margin-bottom:9px;
  border-radius:11px;
  background:linear-gradient(145deg,rgba(237,244,247,.14),rgba(237,244,247,.04));
  border:1px solid rgba(255,255,255,.08);
}
.machine-shape:before,.machine-shape:after{
  content:"";
  position:absolute;
  bottom:-7px;
  width:26px;
  height:10px;
  border-radius:3px;
  background:#263544;
}
.machine-shape:before{left:18px}
.machine-shape:after{right:18px}
.signal-light{
  position:absolute;
  right:12px;
  top:11px;
  width:15px;
  height:15px;
  border-radius:50%;
  background:var(--warn);
  box-shadow:0 0 22px rgba(240,183,90,.75);
}
.floor-machine.working .signal-light{background:var(--ok);box-shadow:0 0 22px rgba(81,216,138,.78)}
.floor-machine.stopped .signal-light{background:var(--alarm);box-shadow:0 0 24px rgba(255,95,104,.82)}
.floor-machine-name{font-weight:800;font-size:14px;letter-spacing:-.02em}
.floor-machine-meta{margin-top:4px;color:var(--muted);font:11px/1.35 var(--mono)}
.floor-machine-data{display:flex;gap:8px;margin-top:8px;color:var(--dim);font:11px var(--mono)}
.report-panel{min-height:560px}
.report-tabs{display:flex;gap:8px;padding:16px 18px 0;flex-wrap:wrap}
.report-tab{
  border:1px solid var(--line);
  border-radius:999px;
  padding:8px 11px;
  background:rgba(255,255,255,.03);
  color:var(--muted);
  cursor:pointer;
  transition:background .2s ease,color .2s ease,transform .2s ease;
}
.report-tab:hover,.report-tab:focus-visible{outline:none;background:rgba(93,214,199,.1);color:var(--text)}
.report-tab:active{transform:scale(.98)}
.report-tab.active{background:rgba(93,214,199,.16);color:var(--accent);border-color:rgba(93,214,199,.45)}
.report-body{padding:16px 18px 18px}
.report-hero{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:10px;
  margin-bottom:10px;
}
.report-stat{
  padding:14px;
  border-radius:16px;
  border:1px solid var(--line-soft);
  background:rgba(255,255,255,.026);
}
.report-stat.wide{grid-column:1 / -1}
.report-label{color:var(--muted);font-size:11px;letter-spacing:.12em;text-transform:uppercase}
.report-value{margin-top:8px;font:800 28px/.9 var(--mono);letter-spacing:-.06em}
.report-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.report-row{padding:12px;border:1px solid var(--line-soft);border-radius:14px;background:rgba(255,255,255,.022)}
.report-row strong{display:block;margin-top:5px;font:700 16px/1 var(--mono)}
.trend{padding:18px}
.trend svg{width:100%;height:180px;display:block}
.axis{stroke:rgba(255,255,255,.07)}
.line-oee{fill:none;stroke:var(--accent);stroke-width:3;stroke-linecap:round}
.line-temp{fill:none;stroke:var(--warn);stroke-width:2;stroke-linecap:round;opacity:.9}
.line-vib{fill:none;stroke:var(--alarm);stroke-width:2;stroke-linecap:round;opacity:.75}
.status-table{padding:16px 18px 18px;display:grid;gap:10px}
.status-row{display:grid;grid-template-columns:1fr auto;gap:14px;align-items:center;padding:12px;border:1px solid var(--line-soft);border-radius:14px;background:rgba(255,255,255,.025)}
.bar{height:8px;background:rgba(255,255,255,.08);border-radius:999px;overflow:hidden;margin-top:8px}
.bar span{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--accent),var(--accent-2));border-radius:inherit;transition:width .35s ease}
.machines{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:18px;margin-top:18px}
.machine{
  border:1px solid var(--line-soft);
  background:linear-gradient(160deg,rgba(15,24,33,.9),rgba(7,11,16,.92));
  border-radius:24px;
  box-shadow:var(--shadow);
  overflow:hidden;
}
.machine.alarm{border-color:rgba(255,95,104,.52);box-shadow:0 20px 70px rgba(255,95,104,.12)}
.machine.warning{border-color:rgba(240,183,90,.42)}
.machine.running{border-color:rgba(93,214,199,.34)}
.machine-head{display:flex;align-items:flex-start;justify-content:space-between;padding:18px 18px 8px}
.machine-name{font-weight:700;font-size:18px;letter-spacing:-.03em}
.register{margin-top:4px;color:var(--dim);font-size:11px}
.badge{border:1px solid var(--line);border-radius:999px;padding:6px 9px;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.badge.running,.badge.working{color:var(--ok);border-color:rgba(81,216,138,.32)}
.badge.alarm{color:var(--alarm);border-color:rgba(255,95,104,.4)}
.badge.warning{color:var(--warn);border-color:rgba(240,183,90,.4)}
.badge.idle{color:var(--warn);border-color:rgba(240,183,90,.36)}
.badge.stopped{color:var(--alarm);border-color:rgba(255,95,104,.45)}
.bits{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;padding:8px 18px 16px}
.bit{display:grid;place-items:center;gap:6px;padding:8px 4px;border-radius:12px;background:rgba(255,255,255,.028);border:1px solid var(--line-soft);color:var(--dim);font-size:10px;letter-spacing:.12em;text-transform:uppercase}
.led{width:9px;height:9px;border-radius:50%;background:#263441}
.bit.on{color:var(--text)}
.bit.on .led{background:var(--ok);box-shadow:0 0 16px rgba(81,216,138,.55)}
.bit.alarm.on .led,.bit.estop.on .led{background:var(--alarm);box-shadow:0 0 16px rgba(255,95,104,.55)}
.analog-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;padding:0 18px 16px}
.analog{padding:14px;border:1px solid var(--line-soft);border-radius:16px;background:rgba(255,255,255,.026)}
.analog-top{display:flex;align-items:baseline;justify-content:space-between;gap:12px}
.analog-label{color:var(--muted);font-size:12px}
.analog-value{font:700 24px/.9 var(--mono);letter-spacing:-.06em}
.analog-unit{font-size:11px;color:var(--dim);letter-spacing:0}
.analog.warning .bar span{background:var(--warn)}
.analog.alarm .bar span{background:var(--alarm)}
.machine-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line-soft);border-top:1px solid var(--line-soft)}
.metric{padding:13px;background:rgba(7,11,16,.66)}
.metric-label{font-size:10px;color:var(--dim);letter-spacing:.12em;text-transform:uppercase}
.metric-value{margin-top:6px;font:700 18px/1 var(--mono);letter-spacing:-.04em}
.event-list{padding:16px 18px 18px;display:grid;gap:10px;max-height:360px;overflow:auto}
.event{display:grid;grid-template-columns:76px 1fr;gap:12px;padding:12px;border:1px solid var(--line-soft);border-radius:14px;background:rgba(255,255,255,.024)}
.event-time{font:11px var(--mono);color:var(--dim)}
.event-message{font-size:13px;color:var(--text)}
.empty{padding:32px 18px;color:var(--muted);text-align:center}
.footer{margin:18px 0 4px;color:var(--dim);font-size:12px;text-align:center}
@media (max-width:1180px){
  .topbar,.dashboard,.overview,.operations{grid-template-columns:1fr}
  .connection{justify-self:start;text-align:left}
  .topology{justify-content:flex-start;overflow:auto}
  .kpi-grid{grid-template-columns:repeat(2,1fr)}
}
@media (max-width:640px){
  .shell{padding:12px}
  .kpi-grid,.analog-grid,.machine-metrics,.bits{grid-template-columns:1fr 1fr}
  .machines{grid-template-columns:1fr}
  .floor-map{min-height:620px;margin:12px}
  .floor-machine{width:118px;min-height:104px}
  .report-hero,.report-grid{grid-template-columns:1fr}
}
</style>
</head>
<body>
<div class="shell">
  <header class="topbar">
    <div class="brand">
      <div class="brand-mark">SC</div>
      <div>
        <p class="eyebrow">Workshop floor telemetry</p>
        <h1>SCADA machine dashboard</h1>
      </div>
    </div>
    <div class="topology" aria-label="Network topology">
      <span class="node">Simulator</span><span class="link"></span><span class="node">Router</span><span class="link"></span><span class="node">PLC</span><span class="link"></span><span class="node">Dashboard</span>
    </div>
    <div class="connection">
      <div>
        <div class="pill"><span id="conn-dot" class="dot"></span><span id="conn-label">Connecting</span></div>
        <div id="conn-detail" class="small mono">Waiting for PLC data</div>
      </div>
    </div>
  </header>

  <section class="dashboard">
    <div class="panel">
      <div class="panel-head">
        <div>
          <h2 class="panel-title">Plant performance</h2>
          <p class="panel-note">OEE uses availability, cycle-rate performance, and 100% assumed quality because no reject register exists.</p>
        </div>
        <div class="small mono" id="last-update">--</div>
      </div>
      <div class="kpi-grid" id="kpi-grid"></div>
    </div>
    <div class="panel trend">
      <div class="panel-head" style="padding:0 0 12px">
        <div>
          <h2 class="panel-title">Live process trend</h2>
          <p class="panel-note">OEE, max temperature, and max vibration over the current browser session.</p>
        </div>
      </div>
      <svg id="trend-chart" viewBox="0 0 640 180" preserveAspectRatio="none" role="img" aria-label="Live trend chart"></svg>
    </div>
  </section>

  <section class="operations">
    <div class="panel floor-panel">
      <div class="panel-head">
        <div>
          <h2 class="panel-title">Live workshop floor</h2>
          <p class="panel-note">Machine locations, state signals, and current production values.</p>
        </div>
        <div class="floor-toolbar" id="floor-legend"></div>
      </div>
      <div class="floor-map" id="floor-map"></div>
    </div>
    <div class="panel report-panel">
      <div class="panel-head">
        <div>
          <h2 class="panel-title">Production reports</h2>
          <p class="panel-note">Period totals are projected from the live observed run.</p>
        </div>
      </div>
      <div class="report-tabs" id="report-tabs"></div>
      <div class="report-body" id="report-body"></div>
    </div>
  </section>

  <section class="overview">
    <div class="panel">
      <div class="panel-head">
        <div>
          <h2 class="panel-title">Process limits</h2>
          <p class="panel-note">Analog values are evaluated against simulator warning and alarm thresholds.</p>
        </div>
      </div>
      <div class="status-table" id="process-summary"></div>
    </div>
    <div class="panel">
      <div class="panel-head">
        <div>
          <h2 class="panel-title">Alarm and event log</h2>
          <p class="panel-note">Latest alarm transitions observed by the dashboard poller.</p>
        </div>
      </div>
      <div class="event-list" id="event-list"></div>
    </div>
  </section>

  <main class="machines" id="machines"></main>
  <div class="footer mono">Modbus TCP source: <span id="source">--</span> · register block: <span id="block-size">--</span></div>
</div>

<script>
const history = [];
const maxHistory = 80;
const bitLabels = [
  ["power", "PWR"], ["auto", "AUTO"], ["running", "RUN"],
  ["estop", "E-STOP"], ["alarm", "ALARM"], ["door_open", "DOOR"]
];
const analogKeys = ["speed", "temperature", "vibration", "load"];
const reportOrder = ["daily", "weekly", "monthly", "yearly"];
let activeReport = "daily";

function fmt(value, suffix = "") {
  if (value === null || value === undefined || Number.isNaN(value)) return "--";
  return `${value}${suffix}`;
}

function cls(value) {
  return String(value || "").toLowerCase();
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function renderKpis(plant) {
  const kpis = [
    ["OEE", plant.oee, "%", `${plant.running}/${plant.machine_count} running`],
    ["Availability", plant.availability, "%", `${plant.alarms} alarms, ${plant.stopped || 0} stopped`],
    ["Performance", plant.performance, "%", `${plant.produced_cycles || 0} observed cycles`],
    ["Quality", plant.quality, "%", "Assumed good cycles"],
    ["Avg speed", plant.avg_speed, " RPM", "Mean machine speed"],
    ["Max temp", plant.max_temperature, " deg C", "Highest machine temperature"],
    ["Max vibration", plant.max_vibration, " mm/s", "Highest vibration"],
    ["Avg load", plant.avg_load, "%", "Mean active load"],
  ];
  document.getElementById("kpi-grid").innerHTML = kpis.map(([label, value, unit, sub]) => `
    <article class="kpi">
      <div class="kpi-label">${label}</div>
      <div class="kpi-value">${fmt(value)}<span class="kpi-unit">${unit}</span></div>
      <div class="kpi-sub">${sub}</div>
    </article>
  `).join("");
}

function renderProcessSummary(plant) {
  const rows = [
    ["OEE target", plant.oee, "%", 85],
    ["Availability", plant.availability, "%", 90],
    ["Performance", plant.performance, "%", 85],
    ["Average load", plant.avg_load, "%", 85],
    ["Max temperature", plant.max_temperature, " deg C", 70],
    ["Max vibration", plant.max_vibration, " mm/s", 40],
  ];
  document.getElementById("process-summary").innerHTML = rows.map(([label, value, unit, target]) => {
    const pct = Math.max(0, Math.min(100, Number(value) || 0));
    return `
      <div class="status-row">
        <div>
          <div>${label}</div>
          <div class="bar"><span style="width:${pct}%"></span></div>
        </div>
        <div class="mono">${fmt(value, unit)} / ${target}${unit}</div>
      </div>`;
  }).join("");
}

function renderFloor(machines, plant) {
  const legend = document.getElementById("floor-legend");
  legend.innerHTML = `
    <span class="signal-chip"><span class="dot working"></span>${plant.running || 0} working</span>
    <span class="signal-chip"><span class="dot idle"></span>${plant.idle || 0} idle</span>
    <span class="signal-chip"><span class="dot stopped"></span>${plant.stopped || plant.alarms || 0} stopped</span>
  `;

  const map = document.getElementById("floor-map");
  if (!machines || !machines.length) {
    map.innerHTML = `<div class="empty">Waiting for machine positions from live PLC data.</div>`;
    return;
  }

  const zones = [...new Set(machines.map(machine => machine.floor.zone))];
  const zoneLabels = zones.map((zone, index) => {
    const left = 8 + index * (84 / Math.max(1, zones.length - 1));
    return `<div class="floor-zone" style="left:${left}%">${zone}</div>`;
  }).join("");

  const stations = machines.map(machine => {
    const signal = machine.signal || {state: machine.severity, label: machine.severity};
    const floor = machine.floor || {x: 50, y: 50, zone: "Floor", line: 1, bay: 1};
    return `
      <button class="floor-machine ${signal.state}" style="left:${floor.x}%;top:${floor.y}%"
        type="button" title="${machine.name} ${signal.label}" onclick="focusMachine(${machine.id})">
        <div class="machine-shape"><span class="signal-light"></span></div>
        <div class="floor-machine-name">${machine.name}</div>
        <div class="floor-machine-meta">${signal.label} &middot; L${floor.line} B${floor.bay}</div>
        <div class="floor-machine-data">
          <span>${machine.analogs.speed.value} rpm</span>
          <span>${machine.produced_cycles} cycles</span>
        </div>
      </button>`;
  }).join("");

  map.innerHTML = zoneLabels + stations;
}

function focusMachine(machineId) {
  const card = document.getElementById(`machine-${machineId}`);
  if (!card) return;
  card.scrollIntoView({behavior: "smooth", block: "center"});
  card.animate(
    [{boxShadow: "0 0 0 rgba(93,214,199,0)"}, {boxShadow: "0 0 0 4px rgba(93,214,199,.35)"}, {boxShadow: "0 0 0 rgba(93,214,199,0)"}],
    {duration: 900, easing: "ease-out"}
  );
}

function renderReports(reports) {
  const tabs = document.getElementById("report-tabs");
  const body = document.getElementById("report-body");
  const available = reports || {};
  tabs.innerHTML = reportOrder.map(key => {
    const report = available[key] || {label: key};
    return `<button class="report-tab ${key === activeReport ? "active" : ""}" type="button" onclick="setReport('${key}')">${report.label}</button>`;
  }).join("");

  const report = available[activeReport] || {};
  body.innerHTML = `
    <div class="report-hero">
      <div class="report-stat wide">
        <div class="report-label">${report.label || "Report"} cycles</div>
        <div class="report-value">${fmt(report.cycles)}</div>
      </div>
      <div class="report-stat">
        <div class="report-label">OEE</div>
        <div class="report-value">${fmt(report.oee, "%")}</div>
      </div>
      <div class="report-stat">
        <div class="report-label">Availability</div>
        <div class="report-value">${fmt(report.availability, "%")}</div>
      </div>
    </div>
    <div class="report-grid">
      <div class="report-row">Working time<strong>${report.working_label || "--"}</strong></div>
      <div class="report-row">Idle time<strong>${report.idle_label || "--"}</strong></div>
      <div class="report-row">Stopped time<strong>${report.stopped_label || "--"}</strong></div>
      <div class="report-row">Alarm count<strong>${fmt(report.alarms)}</strong></div>
      <div class="report-row">Best machine<strong>${report.leader || "--"}</strong></div>
      <div class="report-row">Bottleneck<strong>${report.bottleneck || "--"}</strong></div>
      <div class="report-row">Utilization<strong>${fmt(report.utilization, "%")}</strong></div>
      <div class="report-row">Average load<strong>${fmt(report.avg_load, "%")}</strong></div>
    </div>
  `;
}

function setReport(key) {
  activeReport = key;
  refresh();
}

function renderEvents(events) {
  const list = document.getElementById("event-list");
  if (!events || !events.length) {
    list.innerHTML = `<div class="empty">No alarm transitions recorded yet.</div>`;
    return;
  }
  list.innerHTML = events.slice(0, 16).map(event => `
    <div class="event">
      <div class="event-time">${new Date(event.time).toLocaleTimeString()}</div>
      <div>
        <div class="event-message">${event.machine}: ${event.message}</div>
        <div class="small">${event.level}</div>
      </div>
    </div>
  `).join("");
}

function renderMachines(machines) {
  const root = document.getElementById("machines");
  if (!machines || !machines.length) {
    root.innerHTML = `<section class="machine"><div class="empty">Waiting for PLC register data. Check simulator PLC mode, router, IP address, and Modbus port.</div></section>`;
    return;
  }
  root.innerHTML = machines.map(machine => {
    const bits = bitLabels.map(([key, label]) => {
      const on = machine.status[key];
      const danger = key === "alarm" || key === "estop";
      return `<div class="bit ${on ? "on" : ""} ${danger ? key : ""}"><span class="led"></span><span>${label}</span></div>`;
    }).join("");
    const analogs = analogKeys.map(key => {
      const item = machine.analogs[key];
      return `
        <div class="analog ${item.health}">
          <div class="analog-top">
            <span class="analog-label">${item.label}</span>
            <span class="analog-value">${item.value}<span class="analog-unit"> ${item.unit}</span></span>
          </div>
          <div class="bar"><span style="width:${item.ratio}%"></span></div>
          <div class="small mono">warn ${item.warn_high ?? "--"} &middot; alarm ${item.alarm_high ?? "--"}</div>
        </div>`;
    }).join("");
    return `
      <article class="machine ${cls(machine.severity)} ${cls(machine.signal?.state)}" id="machine-${machine.id}">
        <div class="machine-head">
          <div>
            <div class="machine-name">${machine.name}</div>
            <div class="register mono">holding registers ${machine.register_base}-${machine.register_base + 5} &middot; raw status ${machine.status_raw}</div>
          </div>
          <span class="badge ${cls(machine.signal?.state || machine.severity)}">${machine.signal?.label || machine.severity}</span>
        </div>
        <div class="bits">${bits}</div>
        <div class="analog-grid">${analogs}</div>
        <div class="machine-metrics">
          <div class="metric"><div class="metric-label">OEE</div><div class="metric-value">${machine.metrics.oee}%</div></div>
          <div class="metric"><div class="metric-label">Cycles</div><div class="metric-value">${machine.produced_cycles}</div></div>
          <div class="metric"><div class="metric-label">Runtime</div><div class="metric-value">${machine.metrics.runtime_label}</div></div>
          <div class="metric"><div class="metric-label">Idle</div><div class="metric-value">${machine.metrics.idle_label}</div></div>
          <div class="metric"><div class="metric-label">Avail.</div><div class="metric-value">${machine.metrics.availability}%</div></div>
          <div class="metric"><div class="metric-label">Perf.</div><div class="metric-value">${machine.metrics.performance}%</div></div>
          <div class="metric"><div class="metric-label">MTBF</div><div class="metric-value">${machine.metrics.mtbf_label}</div></div>
          <div class="metric"><div class="metric-label">MTTR</div><div class="metric-value">${machine.metrics.mttr_label}</div></div>
        </div>
      </article>`;
  }).join("");
}

function path(points, key, scaleMax) {
  if (points.length < 2) return "";
  return points.map((point, index) => {
    const x = (index / (maxHistory - 1)) * 640;
    const y = 160 - Math.max(0, Math.min(1, point[key] / scaleMax)) * 140;
    return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

function renderTrend(plant) {
  history.push({
    oee: Number(plant.oee) || 0,
    temperature: Number(plant.max_temperature) || 0,
    vibration: Number(plant.max_vibration) || 0,
  });
  if (history.length > maxHistory) history.shift();
  document.getElementById("trend-chart").innerHTML = `
    <line class="axis" x1="0" y1="160" x2="640" y2="160"></line>
    <line class="axis" x1="0" y1="90" x2="640" y2="90"></line>
    <line class="axis" x1="0" y1="20" x2="640" y2="20"></line>
    <path class="line-oee" d="${path(history, "oee", 100)}"></path>
    <path class="line-temp" d="${path(history, "temperature", 100)}"></path>
    <path class="line-vib" d="${path(history, "vibration", 50)}"></path>
  `;
}

async function refresh() {
  try {
    const response = await fetch("/api", {cache: "no-store"});
    const data = await response.json();
    const dot = document.getElementById("conn-dot");
    dot.classList.toggle("connected", Boolean(data.connection.connected));
    setText("conn-label", data.connection.connected ? "PLC linked" : "PLC offline");
    setText("conn-detail", data.connection.connected ? `Last poll ${data.connection.last_poll}` : data.connection.error || "No data");
    setText("last-update", data.timestamp ? `Updated ${new Date(data.timestamp).toLocaleTimeString()}` : "--");
    setText("source", `${data.connection.plc_ip}:${data.connection.port} / device ${data.connection.device_id}`);
    setText("block-size", data.connection.register_block_size);
    renderKpis(data.plant || {});
    renderProcessSummary(data.plant || {});
    renderFloor(data.machines || [], data.plant || {});
    renderReports(data.reports || {});
    renderEvents(data.events || []);
    renderMachines(data.machines || []);
    renderTrend(data.plant || {});
  } catch (error) {
    document.getElementById("conn-dot").classList.remove("connected");
    setText("conn-label", "Dashboard error");
    setText("conn-detail", error.message);
  }
}

refresh();
setInterval(refresh, 1000);
</script>
</body>
</html>"""


@app.route("/api")
def api():
    with state_lock:
        return jsonify(json.loads(json.dumps(state)))


@app.route("/")
def home():
    return render_template_string(HTML)


if __name__ == "__main__":
    threading.Thread(target=poll, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("DASHBOARD_PORT", "5000")))
