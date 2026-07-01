const history = [];
const maxHistory = 80;
const bitLabels = [
  ["power", "PWR"],
  ["auto", "AUTO"],
  ["running", "RUN"],
  ["estop", "E-STOP"],
  ["alarm", "ALARM"],
  ["door_open", "DOOR"],
];
const analogKeys = ["speed", "temperature", "vibration", "load"];
const reportOrder = ["daily", "weekly", "monthly", "yearly"];
let activeReport = "weekly";

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function fmt(value, suffix = "") {
  if (value === null || value === undefined || Number.isNaN(value)) return "--";
  return `${value}${suffix}`;
}

function cls(value) {
  return String(value || "").toLowerCase();
}

function clamp(value) {
  return Math.max(0, Math.min(100, Number(value) || 0));
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function renderKpis(plant) {
  const kpis = [
    ["OEE", plant.oee, "%", `${plant.running || 0}/${plant.machine_count || 0} machines working`],
    ["Availability", plant.availability, "%", `${plant.alarms || 0} alarms, ${plant.stopped || 0} stopped`],
    ["Performance", plant.performance, "%", `${plant.produced_cycles || 0} observed cycles`],
    ["Maintenance risk", plant.maintenance_risk, "%", `${plant.critical_maintenance || 0} critical checks`],
    ["Avg speed", plant.avg_speed, " RPM", "Mean machine speed"],
    ["Max temp", plant.max_temperature, " deg C", "Highest machine temperature"],
    ["Max vibration", plant.max_vibration, " mm/s", "Highest vibration"],
    ["Avg load", plant.avg_load, "%", "Mean active load"],
  ];

  document.getElementById("kpi-grid").innerHTML = kpis
    .map(
      ([label, value, unit, sub]) => `
        <article class="kpi">
          <div class="kpi-label">${esc(label)}</div>
          <div class="kpi-value">${esc(fmt(value))}<span class="kpi-unit">${esc(unit)}</span></div>
          <div class="kpi-sub">${esc(sub)}</div>
        </article>
      `,
    )
    .join("");
}

function renderProcessSummary(plant) {
  const rows = [
    ["OEE target", plant.oee, "%", 85],
    ["Availability", plant.availability, "%", 90],
    ["Performance", plant.performance, "%", 85],
    ["Average load", plant.avg_load, "%", 85],
    ["Max temperature", plant.max_temperature, " deg C", 70],
    ["Max vibration", plant.max_vibration, " mm/s", 40],
    ["Maintenance risk", plant.maintenance_risk, "%", 55],
  ];

  document.getElementById("process-summary").innerHTML = rows
    .map(([label, value, unit, target]) => {
      const pct = clamp(value);
      const barClass = pct >= target ? "warning" : "";
      return `
        <div class="status-row">
          <div>
            <div>${esc(label)}</div>
            <div class="bar ${barClass}"><span style="width:${pct}%"></span></div>
          </div>
          <div class="mono">${esc(fmt(value, unit))} / ${esc(target + unit)}</div>
        </div>
      `;
    })
    .join("");
}

function renderFloor(machines, plant) {
  const legend = document.getElementById("floor-legend");
  legend.innerHTML = `
    <span class="signal-chip"><span class="dot working"></span>${esc(plant.running || 0)} working</span>
    <span class="signal-chip"><span class="dot idle"></span>${esc(plant.idle || 0)} idle</span>
    <span class="signal-chip"><span class="dot stopped"></span>${esc(plant.stopped || plant.alarms || 0)} stopped</span>
  `;

  const map = document.getElementById("floor-map");
  if (!machines || !machines.length) {
    map.innerHTML = `<div class="empty">Waiting for machine positions from live PLC data.</div>`;
    return;
  }

  const zones = [...new Set(machines.map((machine) => machine.floor.zone))];
  const zoneLabels = zones
    .map((zone, index) => {
      const left = 8 + index * (84 / Math.max(1, zones.length - 1));
      return `<div class="floor-zone" style="left:${left}%">${esc(zone)}</div>`;
    })
    .join("");

  const stations = machines
    .map((machine) => {
      const signal = machine.signal || { state: machine.severity, label: machine.severity };
      const floor = machine.floor || { x: 50, y: 50, zone: "Floor", line: 1, bay: 1 };
      return `
        <button class="floor-machine ${esc(signal.state)}" style="left:${floor.x}%;top:${floor.y}%"
          type="button" title="${esc(machine.name)} ${esc(signal.label)}" onclick="focusMachine(${Number(machine.id)})">
          <div class="machine-shape"><span class="signal-light"></span></div>
          <div class="floor-machine-name">${esc(machine.name)}</div>
          <div class="floor-machine-meta">${esc(signal.label)} / L${esc(floor.line)} B${esc(floor.bay)}</div>
          <div class="floor-machine-data">
            <span>${esc(machine.analogs.speed.value)} rpm</span>
            <span>${esc(machine.produced_cycles)} cycles</span>
          </div>
        </button>
      `;
    })
    .join("");

  map.innerHTML = zoneLabels + stations;
}

function focusMachine(machineId) {
  const card = document.getElementById(`machine-${machineId}`);
  if (!card) return;
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  card.animate(
    [
      { boxShadow: "0 0 0 rgba(79,208,191,0)" },
      { boxShadow: "0 0 0 4px rgba(79,208,191,.35)" },
      { boxShadow: "0 0 0 rgba(79,208,191,0)" },
    ],
    { duration: 900, easing: "ease-out" },
  );
}

function renderReports(reports) {
  const tabs = document.getElementById("report-tabs");
  const body = document.getElementById("report-body");
  const available = reports || {};

  tabs.innerHTML = reportOrder
    .map((key) => {
      const report = available[key] || { label: key };
      return `<button class="report-tab ${key === activeReport ? "active" : ""}" type="button" onclick="setReport('${key}')">${esc(report.label)}</button>`;
    })
    .join("");

  const report = available[activeReport] || {};
  const machineRows = (report.machines || [])
    .map(
      (machine) => `
        <div class="machine-report-row">
          <strong>${esc(machine.name)}</strong>
          <span class="mono">${esc(machine.cycles)} cyc</span>
          <span class="mono">${esc(machine.oee)}% OEE</span>
          <span class="mono">${esc(machine.maintenance_risk)}% risk</span>
          <span class="mono">PM ${esc(machine.maintenance_due)}</span>
        </div>
      `,
    )
    .join("");

  body.innerHTML = `
    <div class="report-hero">
      <div class="report-stat">
        <div class="report-label">${esc(report.label || "Report")} cycles</div>
        <div class="report-value">${esc(fmt(report.cycles))}</div>
      </div>
      <div class="report-stat">
        <div class="report-label">OEE</div>
        <div class="report-value">${esc(fmt(report.oee, "%"))}</div>
      </div>
      <div class="report-stat">
        <div class="report-label">Availability</div>
        <div class="report-value">${esc(fmt(report.availability, "%"))}</div>
      </div>
    </div>
    <div class="report-grid">
      <div class="report-row">Working time<strong>${esc(report.working_label || "--")}</strong></div>
      <div class="report-row">Idle time<strong>${esc(report.idle_label || "--")}</strong></div>
      <div class="report-row">Stopped time<strong>${esc(report.stopped_label || "--")}</strong></div>
      <div class="report-row">Alarm count<strong>${esc(fmt(report.alarms))}</strong></div>
      <div class="report-row">Best machine<strong>${esc(report.leader || "--")}</strong></div>
      <div class="report-row">Bottleneck<strong>${esc(report.bottleneck || "--")}</strong></div>
      <div class="report-row">Utilization<strong>${esc(fmt(report.utilization, "%"))}</strong></div>
      <div class="report-row">Average load<strong>${esc(fmt(report.avg_load, "%"))}</strong></div>
    </div>
    <div class="machine-report-list">
      ${machineRows || '<div class="empty">No machine-level report data yet.</div>'}
    </div>
  `;
}

function setReport(key) {
  activeReport = key;
  refresh();
}

function renderMaintenance(machines) {
  const root = document.getElementById("maintenance-list");
  if (!machines || !machines.length) {
    root.innerHTML = `<div class="empty">Maintenance model starts after the first successful PLC poll.</div>`;
    return;
  }

  root.innerHTML = [...machines]
    .sort((a, b) => (b.maintenance?.risk || 0) - (a.maintenance?.risk || 0))
    .map((machine) => {
      const maintenance = machine.maintenance || {};
      const risk = clamp(maintenance.risk);
      const state = cls(maintenance.state || "healthy");
      return `
        <article class="maintenance-card">
          <div class="maintenance-top">
            <div>
              <strong>${esc(machine.name)}</strong>
              <div class="small mono">driver ${esc(maintenance.driver || "--")} / due ${esc(maintenance.due_in || "--")}</div>
            </div>
            <div class="risk ${state}">${esc(risk)}%</div>
          </div>
          <div class="bar ${state}"><span style="width:${risk}%"></span></div>
          <p class="maintenance-copy">${esc(maintenance.recommendation || "Waiting for signal history.")}</p>
        </article>
      `;
    })
    .join("");
}

function renderEvents(events) {
  const list = document.getElementById("event-list");
  if (!events || !events.length) {
    list.innerHTML = `<div class="empty">No alarm transitions recorded yet.</div>`;
    return;
  }

  list.innerHTML = events
    .slice(0, 18)
    .map(
      (event) => `
        <div class="event">
          <div class="event-time">${esc(new Date(event.time).toLocaleTimeString())}</div>
          <div>
            <div class="event-message">${esc(event.machine)}: ${esc(event.message)}</div>
            <div class="small">${esc(event.level)}</div>
          </div>
        </div>
      `,
    )
    .join("");
}

function renderMachines(machines) {
  const root = document.getElementById("machines");
  if (!machines || !machines.length) {
    root.innerHTML = `<section class="machine"><div class="empty">Waiting for PLC register data. Check simulator PLC mode, router, IP address, and Modbus port.</div></section>`;
    return;
  }

  root.innerHTML = machines
    .map((machine) => {
      const bits = bitLabels
        .map(([key, label]) => {
          const on = machine.status[key];
          const danger = key === "alarm" || key === "estop";
          return `<div class="bit ${on ? "on" : ""} ${danger ? key : ""}"><span class="led"></span><span>${esc(label)}</span></div>`;
        })
        .join("");

      const analogs = analogKeys
        .map((key) => {
          const item = machine.analogs[key];
          return `
            <div class="analog ${esc(item.health)}">
              <div class="analog-top">
                <span class="analog-label">${esc(item.label)}</span>
                <span class="analog-value">${esc(item.value)}<span class="analog-unit"> ${esc(item.unit)}</span></span>
              </div>
              <div class="bar ${esc(item.health)}"><span style="width:${clamp(item.ratio)}%"></span></div>
              <div class="small mono">warn ${esc(item.warn_high ?? "--")} / alarm ${esc(item.alarm_high ?? "--")}</div>
            </div>
          `;
        })
        .join("");

      const maintenance = machine.maintenance || {};
      return `
        <article class="machine ${cls(machine.severity)} ${cls(machine.signal?.state)}" id="machine-${esc(machine.id)}">
          <div class="machine-head">
            <div>
              <div class="machine-name">${esc(machine.name)}</div>
              <div class="register mono">holding registers ${esc(machine.register_base)}-${esc(machine.register_base + 5)} / raw status ${esc(machine.status_raw)}</div>
            </div>
            <span class="badge ${cls(machine.signal?.state || machine.severity)}">${esc(machine.signal?.label || machine.severity)}</span>
          </div>
          <div class="bits">${bits}</div>
          <div class="analog-grid">${analogs}</div>
          <div class="machine-metrics">
            <div class="metric"><div class="metric-label">OEE</div><div class="metric-value">${esc(machine.metrics.oee)}%</div></div>
            <div class="metric"><div class="metric-label">Cycles</div><div class="metric-value">${esc(machine.produced_cycles)}</div></div>
            <div class="metric"><div class="metric-label">Runtime</div><div class="metric-value">${esc(machine.metrics.runtime_label)}</div></div>
            <div class="metric"><div class="metric-label">Idle</div><div class="metric-value">${esc(machine.metrics.idle_label)}</div></div>
            <div class="metric"><div class="metric-label">Avail.</div><div class="metric-value">${esc(machine.metrics.availability)}%</div></div>
            <div class="metric"><div class="metric-label">Perf.</div><div class="metric-value">${esc(machine.metrics.performance)}%</div></div>
            <div class="metric"><div class="metric-label">MTBF</div><div class="metric-value">${esc(machine.metrics.mtbf_label)}</div></div>
            <div class="metric"><div class="metric-label">MTTR</div><div class="metric-value">${esc(machine.metrics.mttr_label)}</div></div>
          </div>
          <div class="machine-maintenance">
            <div class="maintenance-top">
              <div>
                <span class="badge ${cls(maintenance.state)}">${esc(maintenance.state || "healthy")}</span>
                <span class="small mono"> service due ${esc(maintenance.due_in || "--")}</span>
              </div>
              <div class="risk ${cls(maintenance.state)}">${esc(maintenance.risk || 0)}%</div>
            </div>
            <div class="bar ${cls(maintenance.state)}"><span style="width:${clamp(maintenance.risk)}%"></span></div>
          </div>
        </article>
      `;
    })
    .join("");
}

function path(points, key, scaleMax) {
  if (points.length < 2) return "";
  return points
    .map((point, index) => {
      const x = (index / (maxHistory - 1)) * 640;
      const y = 190 - Math.max(0, Math.min(1, point[key] / scaleMax)) * 165;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

function renderTrend(plant) {
  history.push({
    oee: Number(plant.oee) || 0,
    temperature: Number(plant.max_temperature) || 0,
    vibration: Number(plant.max_vibration) || 0,
    risk: Number(plant.maintenance_risk) || 0,
  });
  if (history.length > maxHistory) history.shift();

  document.getElementById("trend-chart").innerHTML = `
    <line class="axis" x1="0" y1="190" x2="640" y2="190"></line>
    <line class="axis" x1="0" y1="108" x2="640" y2="108"></line>
    <line class="axis" x1="0" y1="25" x2="640" y2="25"></line>
    <path class="line-oee" d="${path(history, "oee", 100)}"></path>
    <path class="line-temp" d="${path(history, "temperature", 100)}"></path>
    <path class="line-vib" d="${path(history, "vibration", 50)}"></path>
    <path class="line-risk" d="${path(history, "risk", 100)}"></path>
  `;
}

async function refresh() {
  try {
    const response = await fetch("/api", { cache: "no-store" });
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
    renderMaintenance(data.machines || []);
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
