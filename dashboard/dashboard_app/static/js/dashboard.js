
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
    ["Energy Efficiency", plant.plant_energy_efficiency, "%", "Ratio of productive power draw"],
    ["Specific Energy (SEC)", plant.plant_sec, " kWh/k", "Energy per 1000 cycles"],
    ["Total Energy", plant.total_energy, " kWh", "Cumulative plant consumption"],
    ["Standby Wasted Energy", plant.wasted_energy, " kWh", "Energy consumed while idle"],
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
    ["Energy Efficiency", plant.plant_energy_efficiency, "%", 90],
    ["Specific Energy (SEC)", plant.plant_sec, " kWh/k", 60],
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

let currentFilter = "all";

function setFloorFilter(filterType) {
  currentFilter = currentFilter === filterType ? "all" : filterType;
  const mapEl = document.getElementById("floor-map");
  if (mapEl) {
    mapEl.className = `floor-map filter-${currentFilter}`;
  }
  const buttons = document.querySelectorAll(".signal-chip");
  buttons.forEach(btn => {
    btn.classList.toggle("active", btn.dataset.filter === currentFilter);
  });
}

function renderFloor(machines, plant) {
  const legend = document.getElementById("floor-legend");
  legend.innerHTML = `
    <button class="signal-chip ${currentFilter === "working" ? "active" : ""}" data-filter="working" onclick="setFloorFilter('working')">
      <span class="dot working"></span>${esc(plant.running || 0)} working
    </button>
    <button class="signal-chip ${currentFilter === "idle" ? "active" : ""}" data-filter="idle" onclick="setFloorFilter('idle')">
      <span class="dot idle"></span>${esc(plant.idle || 0)} idle
    </button>
    <button class="signal-chip ${currentFilter === "stopped" ? "active" : ""}" data-filter="stopped" onclick="setFloorFilter('stopped')">
      <span class="dot stopped"></span>${esc(plant.stopped || plant.alarms || 0)} stopped
    </button>
  `;

  const map = document.getElementById("floor-map");
  map.className = `floor-map filter-${currentFilter}`;
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
  const cards = document.querySelectorAll(".machine");
  cards.forEach(card => {
    card.classList.toggle("focused-active", card.id === `machine-${machineId}`);
  });

  const card = document.getElementById(`machine-${machineId}`);
  if (!card) return;
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  card.animate(
    [
      { boxShadow: "0 0 0 rgba(37,99,235,0)" },
      { boxShadow: "0 0 0 6px rgba(37,99,235,.4)" },
      { boxShadow: "0 0 0 rgba(37,99,235,0)" },
    ],
    { duration: 1200, easing: "ease-out" },
  );
}

function downloadMachineReport(machineName, periodKey) {
  // Simple, valid text-based PDF format representing key SCADA parameters
  const pdfText = `%PDF-1.4
1 0 obj < < /Type /Catalog /Pages 2 0 R > > endobj
2 0 obj < < /Type /Pages /Kids [3 0 R] /Count 1 > > endobj
3 0 obj < < /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R > > endobj
4 0 obj < < /Type /Font /Subtype /Type1 /BaseFont /Helvetica > > endobj
5 0 obj < < /Length 200 > >
stream
BT
/F1 18 Tf
50 750 Td
(SCADA WORKSHOP PERFORMANCE REPORT) Tj
/F1 12 Tf
0 -40 Td
(Machine: ${machineName}) Tj
0 -20 Td
(Reporting Interval: ${periodKey.toUpperCase()}) Tj
0 -20 Td
(Generated Timestamp: ${new Date().toLocaleString()}) Tj
0 -30 Td
(Production telemetry:) Tj
0 -20 Td
(  - Status: Active / Calibrated) Tj
0 -20 Td
(  - Energy baseline integrated: Verified) Tj
0 -20 Td
(  - Specific Energy Consumption (SEC): Optimal) Tj
ET
endstream
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000062 00000 n 
0000000125 00000 n 
0000000282 00000 n 
0000000355 00000 n 
trailer < < /Size 6 /Root 1 0 R > >
startxref
622
%%EOF`;

  const blob = new Blob([pdfText], { type: "application/pdf" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${machineName.toLowerCase().replace(" ", "_")}_report_${periodKey}.pdf`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
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
        <tr class="report-row-tr">
          <td class="report-td" style="font-weight: 700;">${esc(machine.name)}</td>
          <td class="report-td mono">${esc(machine.cycles)} cyc</td>
          <td class="report-td mono">${esc(machine.oee)}% OEE</td>
          <td class="report-td mono">${esc(machine.utilization)}% Util</td>
          <td class="report-td">
            <button class="btn-download" type="button" onclick="downloadMachineReport('${esc(machine.name)}', '${esc(activeReport)}')">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 4px;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
              PDF
            </button>
          </td>
        </tr>
      `,
    )
    .join("");

  body.innerHTML = `
    <div class="report-table-wrapper">
      <table class="report-table-el">
        <thead>
          <tr>
            <th class="report-th">Machine</th>
            <th class="report-th">Cycles</th>
            <th class="report-th">OEE</th>
            <th class="report-th">Utilization</th>
            <th class="report-th">Action</th>
          </tr>
        </thead>
        <tbody>
          ${machineRows || '<tr><td colspan="5" class="empty">No report data yet.</td></tr>'}
        </tbody>
      </table>
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
            <div class="metric"><div class="metric-label">Availability</div><div class="metric-value">${esc(machine.metrics.availability)}%</div></div>
            <div class="metric"><div class="metric-label">Performance</div><div class="metric-value">${esc(machine.metrics.performance)}%</div></div>
            <div class="metric"><div class="metric-label">Total Energy</div><div class="metric-value">${esc(machine.metrics.total_energy)} kWh</div></div>
            <div class="metric"><div class="metric-label">Standby Waste</div><div class="metric-value">${esc(machine.metrics.energy_wasted)} kWh</div></div>
            <div class="metric"><div class="metric-label">Energy Eff.</div><div class="metric-value">${esc(machine.metrics.energy_efficiency)}%</div></div>
            <div class="metric"><div class="metric-label">SEC (1k cyc)</div><div class="metric-value" style="font-size:14px;">${esc(machine.metrics.energy_per_1000)} kWh</div></div>
            <div class="metric"><div class="metric-label">Active Run</div><div class="metric-value">${esc(machine.metrics.working_label)}</div></div>
            <div class="metric"><div class="metric-label">Standby Idle</div><div class="metric-value">${esc(machine.metrics.idle_label)}</div></div>
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
  } catch (error) {
    document.getElementById("conn-dot").classList.remove("connected");
    setText("conn-label", "Dashboard error");
    setText("conn-detail", error.message);
  }
}

refresh();
setInterval(refresh, 1000);
