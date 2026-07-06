import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const FILTERS = ["all", "working", "idle", "stopped"];
const PERIODS = ["daily", "weekly", "monthly", "yearly"];
const ANALOGS = ["speed", "load", "temperature", "vibration"];
const TABS = [
  ["overview", "Overview"],
  ["workshop", "Live Workshop"],
  ["energy", "Energy"],
  ["performance", "Performance"],
  ["maintenance", "Maintenance"],
  ["reports", "Reports"],
];
const BITS = [
  ["power", "PWR"],
  ["auto", "AUTO"],
  ["running", "RUN"],
  ["estop", "E-STOP"],
  ["alarm", "ALARM"],
  ["door_open", "DOOR"],
];

const emptySnapshot = {
  timestamp: null,
  connection: {},
  plant: {},
  machines: [],
  reports: {},
  events: [],
};

function clamp(value, max = 100) {
  return Math.max(0, Math.min(max, Number(value) || 0));
}

function number(value, decimals = 0) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "--";
  return n.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function percent(value) {
  return `${number(value, 1)}%`;
}

function money(value) {
  return `Rs ${number(value, 2)}`;
}

function statusLabel(machine) {
  return machine?.signal?.label || machine?.severity || "Unknown";
}

function statusClass(machine) {
  return machine?.signal?.state || machine?.severity || "offline";
}

function updatedLabel(timestamp) {
  if (!timestamp) return "--";
  return new Date(timestamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function sortByRisk(machines) {
  return [...machines].sort((a, b) => (b.maintenance?.risk || 0) - (a.maintenance?.risk || 0));
}

function downloadMachineReport(machine, period, report) {
  const lines = [
    "WORKSHOP ENERGY INTELLIGENCE REPORT",
    `Machine: ${machine.name}`,
    `Period: ${period.toUpperCase()}`,
    `Generated: ${new Date().toLocaleString()}`,
    "",
    `Cycles: ${machine.cycles}`,
    `OEE: ${machine.oee}%`,
    `Availability: ${machine.availability}%`,
    `Performance: ${machine.performance}%`,
    `Projected energy: ${machine.energy_kwh} kWh`,
    `Idle waste: ${machine.idle_waste_kwh} kWh`,
    `Idle waste cost: ${money(machine.idle_waste_cost)}`,
    `Specific energy: ${machine.sec} kWh / 1k cycles`,
    `Plant baseline for period: ${report.sec || 0} kWh / 1k cycles`,
  ];

  const blob = new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${machine.name.toLowerCase().replaceAll(" ", "_")}_${period}_report.txt`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function useDashboardData() {
  const [data, setData] = useState(emptySnapshot);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;

    async function load() {
      try {
        const response = await fetch("/api", { cache: "no-store" });
        if (!response.ok) throw new Error(`API ${response.status}`);
        const next = await response.json();
        if (live) {
          setData(next);
          setError("");
        }
      } catch (err) {
        if (live) setError(err.message || "Dashboard API unavailable");
      }
    }

    load();
    const timer = setInterval(load, 1000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);

  return { data, error };
}

function App() {
  const { data, error } = useDashboardData();
  const [filter, setFilter] = useState("all");
  const [period, setPeriod] = useState("daily");
  const [selectedId, setSelectedId] = useState(null);
  const [activeTab, setActiveTab] = useState("overview");

  const plant = data.plant || {};
  const machines = data.machines || [];
  const reports = data.reports || {};
  const activeReport = reports[period] || {};
  const selectedMachine = useMemo(() => {
    if (!machines.length) return null;
    return machines.find((machine) => machine.id === selectedId) || machines[0];
  }, [machines, selectedId]);

  const filteredMachines = machines.filter((machine) => {
    if (filter === "all") return true;
    return statusClass(machine) === filter;
  });

  const worstEnergy = useMemo(() => {
    if (!machines.length) return null;
    return [...machines].sort(
      (a, b) => (b.metrics?.energy_wasted || 0) - (a.metrics?.energy_wasted || 0),
    )[0];
  }, [machines]);

  return (
    <main className="app-shell">
      <Header data={data} error={error} />
      <TabNav activeTab={activeTab} setActiveTab={setActiveTab} />

      {activeTab === "overview" ? (
        <OverviewPage
          plant={plant}
          period={period}
          activeReport={activeReport}
          worstEnergy={worstEnergy}
          connection={data.connection || {}}
        />
      ) : null}

      {activeTab === "workshop" ? (
        <LiveWorkshopPage
          machines={filteredMachines}
          allMachines={machines}
          plant={plant}
          filter={filter}
          setFilter={setFilter}
          selectedMachine={selectedMachine}
          setSelectedId={setSelectedId}
        />
      ) : null}

      {activeTab === "energy" ? <EnergyPage machines={machines} plant={plant} /> : null}

      {activeTab === "performance" ? (
        <PerformancePage
          machines={machines}
          selectedMachine={selectedMachine}
          setSelectedId={setSelectedId}
        />
      ) : null}

      {activeTab === "maintenance" ? <MaintenancePage machines={machines} /> : null}

      {activeTab === "reports" ? (
        <ReportsPage period={period} setPeriod={setPeriod} report={activeReport} />
      ) : null}
    </main>
  );
}

function TabNav({ activeTab, setActiveTab }) {
  return (
    <nav className="tab-nav" aria-label="Dashboard sections">
      {TABS.map(([key, label]) => (
        <button
          key={key}
          type="button"
          className={activeTab === key ? "active" : ""}
          onClick={() => setActiveTab(key)}
        >
          {label}
        </button>
      ))}
    </nav>
  );
}

function OverviewPage({ plant, period, activeReport, worstEnergy, connection }) {
  return (
    <div className="tab-page">
      <section className="hero-grid">
        <DecisionPanel plant={plant} activeReport={activeReport} worstEnergy={worstEnergy} />
        <NetworkPanel connection={connection} />
      </section>
      <PrimaryKpis plant={plant} period={period} activeReport={activeReport} />
    </div>
  );
}

function PrimaryKpis({ plant, period, activeReport }) {
  return (
    <section className="kpi-grid" aria-label="Primary workshop KPIs">
      <KpiCard
        label="Output"
        value={number(plant.produced_cycles)}
        unit="cycles"
        note={`${plant.running || 0}/${plant.machine_count || 0} running now`}
        tone="blue"
      />
      <KpiCard
        label="OEE"
        value={number(plant.oee, 1)}
        unit="%"
        note={`Availability ${percent(plant.availability)} / performance ${percent(plant.performance)}`}
        tone="blue"
      />
      <KpiCard
        label="Energy used"
        value={number(plant.total_energy, 2)}
        unit="kWh"
        note={`${number(activeReport.energy_kwh, 1)} kWh projected ${period}`}
        tone="green"
      />
      <KpiCard
        label="Specific energy"
        value={number(plant.plant_sec, 2)}
        unit="kWh / 1k cycles"
        note={`${number(activeReport.sec, 2)} projected ${period}`}
        tone="green"
      />
      <KpiCard
        label="Idle waste"
        value={number(plant.wasted_energy, 2)}
        unit="kWh"
        note={`${money(activeReport.idle_waste_cost)} projected ${period}`}
        tone="amber"
      />
      <KpiCard
        label="Condition review"
        value={number(plant.maintenance_risk, 1)}
        unit="% risk"
        note={`${plant.critical_maintenance || 0} critical machines for review`}
        tone={plant.critical_maintenance ? "red" : "green"}
      />
    </section>
  );
}

function LiveWorkshopPage({
  machines,
  allMachines,
  plant,
  filter,
  setFilter,
  selectedMachine,
  setSelectedId,
}) {
  return (
    <div className="tab-page workshop-showcase">
      <WorkshopMap
        machines={machines}
        allMachines={allMachines}
        plant={plant}
        filter={filter}
        setFilter={setFilter}
        selectedMachine={selectedMachine}
        setSelectedId={setSelectedId}
        featured
      />
      <MachineDeepDive
        machines={allMachines}
        selectedMachine={selectedMachine}
        setSelectedId={setSelectedId}
      />
    </div>
  );
}

function EnergyPage({ machines, plant }) {
  return (
    <div className="tab-page two-column-page">
      <EnergyAnalyzer machines={machines} plant={plant} />
      <section className="panel">
        <div className="panel-head">
          <div>
            <p className="eyebrow">Cost model</p>
            <h2>Rupee impact</h2>
            <p>Industrial tariff is fixed at 8.6 Rs per kWh for this demo.</p>
          </div>
        </div>
        <div className="cost-stack">
          <InsightRow
            label="Observed idle waste cost"
            value={money(plant.wasted_energy_cost)}
            note={`${number(plant.wasted_energy, 2)} kWh idle energy at 8.6 Rs/unit`}
          />
          <InsightRow
            label="Productive energy ratio"
            value={percent(plant.plant_energy_efficiency)}
            note="Higher means more of the bill is tied to actual output"
          />
          <InsightRow
            label="Specific energy"
            value={`${number(plant.plant_sec, 2)} kWh/k`}
            note="Use this as the main bill-vs-production efficiency number"
          />
        </div>
      </section>
    </div>
  );
}

function PerformancePage({ machines, selectedMachine, setSelectedId }) {
  return (
    <div className="tab-page">
      <PerformanceAnalyzer machines={machines} />
      <MachineDeepDive machines={machines} selectedMachine={selectedMachine} setSelectedId={setSelectedId} />
    </div>
  );
}

function MaintenancePage({ machines }) {
  return (
    <div className="tab-page single-panel-page">
      <MaintenanceReview machines={machines} />
    </div>
  );
}

function ReportsPage({ period, setPeriod, report }) {
  return (
    <div className="tab-page single-panel-page">
      <PeriodReports period={period} setPeriod={setPeriod} report={report} expanded />
    </div>
  );
}

function Header({ data, error }) {
  const connection = data.connection || {};
  const connected = Boolean(connection.connected) && !error;
  return (
    <header className="header">
      <div>
        <p className="eyebrow">Live workshop clone</p>
        <h1>Energy and machine performance command center</h1>
        <p className="lede">
          Built for the demo architecture: simulator laptop to router to PLC to router to dashboard laptop.
        </p>
      </div>
      <div className="header-status">
        <span className={`status-dot ${connected ? "connected" : ""}`} />
        <div>
          <strong>{connected ? "PLC linked" : "PLC offline"}</strong>
          <span>{error || connection.error || `Last poll ${connection.last_poll || "--"}`}</span>
        </div>
      </div>
      <div className="clock">
        <span>Last update</span>
        <strong>{updatedLabel(data.timestamp)}</strong>
      </div>
    </header>
  );
}

function DecisionPanel({ plant, activeReport, worstEnergy }) {
  const activePower = Number(plant.avg_load || 0);
  const wasteRatio = plant.total_energy ? (plant.wasted_energy / plant.total_energy) * 100 : 0;
  return (
    <section className="panel decision-panel">
      <div className="panel-head compact">
        <div>
          <p className="eyebrow">Management answer</p>
          <h2>Where the bill is leaking</h2>
        </div>
        <span className="cadence">Live plus period review</span>
      </div>
      <div className="decision-layout">
        <div className="decision-score">
          <span>{number(wasteRatio, 1)}%</span>
          <p>of measured energy has been spent while machines were powered but not producing.</p>
        </div>
        <div className="decision-list">
          <InsightRow
            label="Worst idle contributor"
            value={worstEnergy?.name || "--"}
            note={`${number(worstEnergy?.metrics?.energy_wasted, 2)} kWh waste observed`}
          />
          <InsightRow
            label="Projected idle cost"
            value={money(activeReport.idle_waste_cost)}
            note="Uses 8.6 Rs per kWh industrial tariff"
          />
          <InsightRow
            label="Load pressure"
            value={`${number(activePower, 1)}%`}
            note="Average instantaneous load across connected machines"
          />
        </div>
      </div>
    </section>
  );
}

function NetworkPanel({ connection }) {
  return (
    <section className="panel network-panel">
      <div className="panel-head compact">
        <div>
          <p className="eyebrow">Signal path</p>
          <h2>Demo topology</h2>
        </div>
      </div>
      <div className="topology-line">
        {["Simulator", "Router", "PLC", "Router", "Dashboard"].map((item, index) => (
          <React.Fragment key={`${item}-${index}`}>
            <div className="topology-node">{item}</div>
            {index < 4 ? <div className="topology-link" /> : null}
          </React.Fragment>
        ))}
      </div>
      <div className="network-meta">
        <span>PLC {connection.plc_ip || "--"}:{connection.port || "--"}</span>
        <span>Device {connection.device_id || "--"}</span>
        <span>Block {connection.register_block_size || "--"}</span>
      </div>
    </section>
  );
}

function KpiCard({ label, value, unit, note, tone }) {
  return (
    <article className={`kpi-card ${tone}`}>
      <span>{label}</span>
      <strong>
        {value}
        <small>{unit}</small>
      </strong>
      <p>{note}</p>
    </article>
  );
}

function WorkshopMap({
  machines,
  allMachines,
  plant,
  filter,
  setFilter,
  selectedMachine,
  setSelectedId,
  featured = false,
}) {
  return (
    <section className={`panel workshop-panel ${featured ? "featured" : ""}`}>
      <div className="panel-head">
        <div>
          <p className="eyebrow">Live layer</p>
          <h2>{featured ? "Live workshop clone" : "Workshop clone"}</h2>
          <p>Click a machine to inspect status bits, analog registers, energy, and cycles.</p>
        </div>
        <div className="segmented">
          {FILTERS.map((item) => (
            <button
              key={item}
              type="button"
              className={filter === item ? "active" : ""}
              onClick={() => setFilter(item)}
            >
              {item}
            </button>
          ))}
        </div>
      </div>
      <div className="workshop-layout">
        <div className="floor">
          <div className="floor-title">PLC mirrored shop floor</div>
          <div className="floor-band top">Line 1 / machining</div>
          <div className="floor-band bottom">Line 2 / finishing</div>
          <div className="floor-corridor">material flow</div>
          {machines.length ? (
            <div className="floor-machine-grid">
              {machines.map((machine) => (
                <button
                  key={machine.id}
                  type="button"
                  className={`floor-machine ${statusClass(machine)} ${
                    selectedMachine?.id === machine.id ? "selected" : ""
                  }`}
                  onClick={() => setSelectedId(machine.id)}
                >
                  <span className="machine-light" />
                  <strong>{machine.name}</strong>
                  <small>
                    {statusLabel(machine)} / L{machine.floor?.line || 1} B{machine.floor?.bay || machine.id + 1}
                  </small>
                  <span>{machine.analogs?.load?.value ?? 0}% load / {machine.produced_cycles || 0} cycles</span>
                </button>
              ))}
            </div>
          ) : (
            <div className="floor-empty">Waiting for PLC machine data.</div>
          )}
        </div>
        <MachineInspector machine={selectedMachine} plant={plant} count={allMachines.length} />
      </div>
    </section>
  );
}

function MachineInspector({ machine, plant, count }) {
  if (!machine) {
    return (
      <aside className="inspector">
        <p className="empty-state">No machine selected.</p>
      </aside>
    );
  }

  return (
    <aside className="inspector">
      <div className="inspector-title">
        <div>
          <span className={`machine-state ${statusClass(machine)}`}>{statusLabel(machine)}</span>
          <h3>{machine.name}</h3>
        </div>
        <strong>{machine.metrics?.oee || 0}%</strong>
      </div>
      <div className="mini-grid">
        <MiniStat label="cycles" value={number(machine.produced_cycles)} />
        <MiniStat label="energy" value={`${number(machine.metrics?.total_energy, 2)} kWh`} />
        <MiniStat label="waste" value={`${number(machine.metrics?.energy_wasted, 2)} kWh`} />
        <MiniStat label="SEC" value={`${number(machine.metrics?.energy_per_1000, 1)}`} />
      </div>
      <div className="bit-grid">
        {BITS.map(([key, label]) => (
          <span key={key} className={machine.status?.[key] ? "on" : ""}>
            {label}
          </span>
        ))}
      </div>
      <div className="analog-list">
        {ANALOGS.map((key) => {
          const item = machine.analogs?.[key] || {};
          return (
            <ProgressRow
              key={key}
              label={item.label || key}
              value={`${item.value ?? "--"} ${item.unit || ""}`}
              pct={item.ratio}
              tone={item.health}
            />
          );
        })}
      </div>
      <p className="inspector-note">
        Plant state: {plant.running || 0} running, {plant.idle || 0} idle, {plant.stopped || 0} stopped
        across {count || 0} connected machines.
      </p>
    </aside>
  );
}

function EnergyAnalyzer({ machines, plant }) {
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <p className="eyebrow">Power analyzer</p>
          <h2>Energy per output</h2>
          <p>Track kWh, idle waste, and specific energy by machine.</p>
        </div>
        <span className="cadence">Live metering</span>
      </div>
      <div className="energy-summary">
        <CircularMetric value={plant.plant_energy_efficiency || 100} label="productive energy" />
        <div>
          <InsightRow
            label="Total energy"
            value={`${number(plant.total_energy, 2)} kWh`}
            note="Integrated from load and assumed motor rating"
          />
          <InsightRow
            label="Idle energy"
            value={`${number(plant.wasted_energy, 2)} kWh`}
            note={`${money(plant.wasted_energy_cost)} at 8.6 Rs/unit`}
          />
          <InsightRow
            label="Specific energy"
            value={`${number(plant.plant_sec, 2)} kWh/k`}
            note="Lower means better output for the same bill"
          />
        </div>
      </div>
      <div className="rank-list">
        {machines.map((machine) => (
          <div className="rank-row" key={machine.id}>
            <div>
              <strong>{machine.name}</strong>
              <span>{number(machine.metrics?.energy_per_1000, 1)} kWh / 1k cycles</span>
            </div>
            <div className="rank-bars">
              <ProgressRow
                label="productive"
                value={`${number(machine.metrics?.energy_efficiency, 1)}%`}
                pct={machine.metrics?.energy_efficiency}
                tone="normal"
              />
              <ProgressRow
                label="idle waste"
                value={`${number(machine.metrics?.energy_wasted, 2)} kWh`}
                pct={plant.wasted_energy ? (machine.metrics?.energy_wasted / plant.wasted_energy) * 100 : 0}
                tone="warning"
              />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function PerformanceAnalyzer({ machines }) {
  return (
    <section className="panel analysis-panel">
      <div className="panel-head">
        <div>
          <p className="eyebrow">Machine performance</p>
          <h2>OEE breakdown</h2>
          <p>Availability and performance explain whether low output is downtime or slow cycles.</p>
        </div>
        <span className="cadence">Live production</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Machine</th>
              <th>State</th>
              <th>OEE</th>
              <th>Avail.</th>
              <th>Perf.</th>
              <th>Cycles/hr</th>
            </tr>
          </thead>
          <tbody>
            {machines.map((machine) => (
              <tr key={machine.id}>
                <td>{machine.name}</td>
                <td>
                  <span className={`machine-state ${statusClass(machine)}`}>{statusLabel(machine)}</span>
                </td>
                <td>{percent(machine.metrics?.oee)}</td>
                <td>{percent(machine.metrics?.availability)}</td>
                <td>{percent(machine.metrics?.performance)}</td>
                <td>{number(machine.metrics?.cycles_per_hour, 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function MaintenanceReview({ machines }) {
  return (
    <section className="panel analysis-panel">
      <div className="panel-head">
        <div>
          <p className="eyebrow">Predictive maintenance</p>
          <h2>Condition review</h2>
          <p>Rolling vibration, temperature, load, alarms, and cycle pressure for shift review.</p>
        </div>
        <span className="cadence">End of shift</span>
      </div>
      <div className="maintenance-stack">
        {sortByRisk(machines).map((machine) => {
          const maintenance = machine.maintenance || {};
          return (
            <article className="maintenance-card" key={machine.id}>
              <div>
                <span className={`machine-state ${maintenance.state || "healthy"}`}>
                  {maintenance.state || "healthy"}
                </span>
                <h3>{machine.name}</h3>
              </div>
              <strong>{number(maintenance.risk, 1)}%</strong>
              <ProgressRow
                label={`Driver: ${maintenance.driver || "--"}`}
                value={`due ${maintenance.due_in || "--"}`}
                pct={maintenance.risk}
                tone={maintenance.state}
              />
              <p>{maintenance.recommendation || "Waiting for signal history."}</p>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function PeriodReports({ period, setPeriod, report, expanded = false }) {
  const machines = report.machines || [];
  return (
    <section className={`panel analysis-panel reports-panel ${expanded ? "expanded" : ""}`}>
      <div className="panel-head">
        <div>
          <p className="eyebrow">Reports</p>
          <h2>Period summary</h2>
          <p>Use these for day, week, month, and yearly bill-reduction conversations.</p>
        </div>
      </div>
      <div className="segmented period-tabs">
        {PERIODS.map((item) => (
          <button
            key={item}
            type="button"
            className={period === item ? "active" : ""}
            onClick={() => setPeriod(item)}
          >
            {item}
          </button>
        ))}
      </div>
      <div className="report-metrics">
        <MiniStat label="cycles" value={number(report.cycles)} />
        <MiniStat label="OEE" value={percent(report.oee)} />
        <MiniStat label="energy" value={`${number(report.energy_kwh, 1)} kWh`} />
        <MiniStat label="idle cost" value={money(report.idle_waste_cost)} />
      </div>
      <div className="report-list">
        {machines.slice(0, expanded ? machines.length : 5).map((machine) => (
          <div className="report-row" key={machine.id}>
            <div>
              <strong>{machine.name}</strong>
              <span>{number(machine.cycles)} cycles / {number(machine.sec, 1)} kWh-k</span>
            </div>
            <button type="button" onClick={() => downloadMachineReport(machine, period, report)}>
              report
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}

function MachineDeepDive({ machines, selectedMachine, setSelectedId }) {
  return (
    <section className="panel deep-panel">
      <div className="panel-head">
        <div>
          <p className="eyebrow">PLC details</p>
          <h2>Machine cards</h2>
          <p>Raw status bits and holding-register ranges remain visible for demo explanation.</p>
        </div>
      </div>
      <div className="machine-card-grid">
        {machines.map((machine) => (
          <button
            type="button"
            key={machine.id}
            className={`machine-card ${statusClass(machine)} ${
              selectedMachine?.id === machine.id ? "selected" : ""
            }`}
            onClick={() => setSelectedId(machine.id)}
          >
            <div>
              <span className={`machine-state ${statusClass(machine)}`}>{statusLabel(machine)}</span>
              <h3>{machine.name}</h3>
              <small>
                registers {machine.register_base}-{machine.register_base + 5} / raw {machine.status_raw}
              </small>
            </div>
            <div className="machine-card-metrics">
              <MiniStat label="OEE" value={percent(machine.metrics?.oee)} />
              <MiniStat label="run" value={machine.metrics?.working_label || "0s"} />
              <MiniStat label="idle" value={machine.metrics?.idle_label || "0s"} />
              <MiniStat label="MTTR" value={machine.metrics?.mttr_label || "0s"} />
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}

function CircularMetric({ value, label }) {
  const pct = clamp(value);
  return (
    <div className="circular" style={{ "--value": `${pct * 3.6}deg` }}>
      <div>
        <strong>{number(pct, 1)}%</strong>
        <span>{label}</span>
      </div>
    </div>
  );
}

function InsightRow({ label, value, note }) {
  return (
    <div className="insight-row">
      <span>{label}</span>
      <strong>{value}</strong>
      <p>{note}</p>
    </div>
  );
}

function ProgressRow({ label, value, pct, tone = "normal" }) {
  return (
    <div className={`progress-row ${tone || "normal"}`}>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
      <div className="bar">
        <i style={{ width: `${clamp(pct)}%` }} />
      </div>
    </div>
  );
}

function MiniStat({ label, value }) {
  return (
    <div className="mini-stat">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
