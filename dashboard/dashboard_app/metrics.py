from __future__ import annotations

import math
import time

from .config import (
    ANALOG_KEYS,
    CONFIG,
    FLOOR_ZONES,
    IDEAL_CYCLE_SECONDS,
    MACHINE_COUNT,
    REGISTER_BLOCK_SIZE,
    REPORT_PERIODS,
    STATUS_BITS,
)
from .state import add_event, runtime


def percent(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def seconds_label(seconds: float) -> str:
    seconds = int(max(0, seconds))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    if days:
        return f"{days}d {hours:02d}h"
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def hours_label(hours: float) -> str:
    if hours <= 24:
        return f"{max(1, round(hours))}h"
    days = hours / 24
    if days <= 14:
        return f"{round(days, 1)}d"
    return f"{round(days)}d"


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
            "last_estop": False,
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


def maintenance_model(status: dict, analogs: dict, counters: dict) -> dict:
    vibration = analogs["vibration"]
    temperature = analogs["temperature"]
    load = analogs["load"]
    vibration_pressure = vibration["ratio"] * 0.42
    thermal_pressure = temperature["ratio"] * 0.26
    load_pressure = load["ratio"] * 0.18
    fault_ratio = counters["fault_time"] / counters["runtime"] * 100 if counters["runtime"] else 0
    alarm_pressure = min(18, counters["alarm_events"] * 4)
    risk = vibration_pressure + thermal_pressure + load_pressure + fault_ratio * 0.55 + alarm_pressure
    if status.get("estop") or status.get("alarm"):
        risk = max(risk, 88)
    risk = percent(risk)

    if risk >= 80:
        state = "critical"
        recommendation = "Inspect bearings, drive load, and safety circuit before next production run."
    elif risk >= 55:
        state = "watch"
        recommendation = "Schedule lubrication, thermal scan, and vibration check on the next maintenance window."
    else:
        state = "healthy"
        recommendation = "No urgent work. Keep normal lubrication and visual inspection cadence."

    due_hours = max(2, 180 - (risk * 1.85))
    top_driver = max(
        (
            ("vibration", vibration["ratio"]),
            ("temperature", temperature["ratio"]),
            ("load", load["ratio"]),
            ("alarms", alarm_pressure * 4),
        ),
        key=lambda item: item[1],
    )[0]
    return {
        "risk": risk,
        "state": state,
        "due_in": hours_label(due_hours),
        "driver": top_driver,
        "recommendation": recommendation,
    }


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
    if status["estop"] and not counters["last_estop"]:
        add_event(machine_name, "alarm", "Emergency stop bit is active")
    counters["last_alarm"] = status["alarm"]
    counters["last_estop"] = status["estop"]

    previous_cycle_count = counters["last_cycle_count"]
    cycle_delta = 0 if previous_cycle_count is None else max(0, cycle_count - previous_cycle_count)
    counters["last_cycle_count"] = cycle_count
    counters["observed_cycles"] += cycle_delta

    analogs = {key: build_analog(key, value) for key, value in zip(ANALOG_KEYS, registers[1:5])}
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
        "maintenance": maintenance_model(status, analogs, counters),
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


def build_plant(machines: list[dict]) -> dict:
    if not machines:
        return {
            "machine_count": MACHINE_COUNT,
            "connected_machines": 0,
            "running": 0,
            "idle": 0,
            "alarms": 0,
            "stopped": 0,
            "warnings": 0,
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
            "maintenance_risk": 0,
            "critical_maintenance": 0,
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
        "maintenance_risk": round(sum(m["maintenance"]["risk"] for m in machines) / len(machines), 1),
        "critical_maintenance": sum(1 for m in machines if m["maintenance"]["state"] == "critical"),
    }


def machine_period_report(machine: dict, period_seconds: int, observed_window: float) -> dict:
    scale = period_seconds / observed_window
    metrics = machine["metrics"]
    return {
        "id": machine["id"],
        "name": machine["name"],
        "cycles": int(round(machine["produced_cycles"] * scale)),
        "oee": metrics["oee"],
        "availability": metrics["availability"],
        "utilization": metrics["utilization"],
        "working_label": seconds_label(metrics["run_time"] * scale),
        "idle_label": seconds_label(metrics["idle_time"] * scale),
        "stopped_label": seconds_label(metrics["fault_time"] * scale),
        "alarms": int(round(metrics["alarm_events"] * scale)),
        "maintenance_risk": machine["maintenance"]["risk"],
        "maintenance_due": machine["maintenance"]["due_in"],
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
            "machines": [],
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
        "machines": [machine_period_report(m, period_seconds, observed_window) for m in machines],
    }


def build_reports(machines: list[dict]) -> dict:
    return {
        key: period_report(machines, key, label, seconds)
        for key, (label, seconds) in REPORT_PERIODS.items()
    }
