import { useDashboard } from "./hooks/useDashboard";
import { EquityCurve } from "./components/EquityCurve";
import { OpenPositions } from "./components/OpenPositions";
import { RiskMetrics } from "./components/RiskMetrics";
import { OrderLog } from "./components/OrderLog";
import { BridgeLatency } from "./components/BridgeLatency";
import { ConnectionStatus } from "./components/ConnectionStatus";

const INITIAL_BALANCE = 100_000;

export default function App() {
  const { snapshot, running, startBacktest, stopEngine } = useDashboard();

  return (
    <div className="dashboard">
      {/* ── Header ────────────────────────────────────────────────────────── */}
      <header className="header">
        <h1>QUANTFUND</h1>

        <div className="progress-bar-wrap">
          <div
            className="progress-bar-fill"
            style={{ width: `${snapshot.progress_pct}%` }}
          />
        </div>

        <span className="header-meta">
          {snapshot.tick_count.toLocaleString()} / {snapshot.total_ticks.toLocaleString()} ticks
          &nbsp;·&nbsp;
          {snapshot.progress_pct.toFixed(1)}%
        </span>

        {!running ? (
          <button className="btn" onClick={startBacktest}>
            Run Backtest
          </button>
        ) : (
          <button className="btn danger" onClick={stopEngine}>
            Stop
          </button>
        )}
      </header>

      {/* ── Row 1: Charts ─────────────────────────────────────────────────── */}
      <div className="row-charts">
        <EquityCurve data={snapshot.equity_curve} initialBalance={INITIAL_BALANCE} />
        <RiskMetrics risk={snapshot.risk} />
      </div>

      {/* ── Row 2: Data panels ────────────────────────────────────────────── */}
      <div className="row-data">
        <OpenPositions positions={snapshot.positions} />
        <BridgeLatency data={snapshot.latency} mode={snapshot.connection.mode} />
        <div style={{ display: "grid", gridTemplateRows: "1fr 1fr", gap: 8 }}>
          <OrderLog entries={snapshot.order_log} />
          <ConnectionStatus connection={snapshot.connection} />
        </div>
      </div>
    </div>
  );
}
