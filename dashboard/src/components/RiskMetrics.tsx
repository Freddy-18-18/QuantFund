import { RiskSnapshot } from "../types";

interface Props {
  risk: RiskSnapshot;
}

interface MetricProps {
  label: string;
  value: string;
  tone: "positive" | "negative" | "neutral" | "warn";
}

function Metric({ label, value, tone }: MetricProps) {
  return (
    <div className="metric-card">
      <div className="metric-label">{label}</div>
      <div className={`metric-value ${tone}`}>{value}</div>
    </div>
  );
}

export function RiskMetrics({ risk }: Props) {
  const ddTone =
    risk.current_drawdown_pct > 15
      ? "negative"
      : risk.current_drawdown_pct > 8
      ? "warn"
      : "neutral";

  const pnlTone = risk.daily_pnl >= 0 ? "positive" : "negative";

  return (
    <div className="card" style={{ height: "100%" }}>
      <div className="card-header">
        <span>Risk Metrics</span>
        {risk.kill_switch_active && (
          <span style={{ color: "var(--danger)", fontFamily: "var(--font-mono)", fontSize: 10 }}>
            KILL SWITCH ACTIVE
          </span>
        )}
      </div>
      <div className="card-body">
        <div className="metric-grid">
          <Metric
            label="Equity"
            value={`$${risk.equity.toLocaleString("en-US", { maximumFractionDigits: 0 })}`}
            tone="neutral"
          />
          <Metric
            label="Daily P&L"
            value={`${risk.daily_pnl >= 0 ? "+" : ""}$${risk.daily_pnl.toFixed(2)}`}
            tone={pnlTone}
          />
          <Metric
            label="Drawdown"
            value={`${risk.current_drawdown_pct.toFixed(2)}%`}
            tone={ddTone}
          />
          <Metric
            label="Max Drawdown"
            value={`${risk.max_drawdown_pct.toFixed(2)}%`}
            tone={risk.max_drawdown_pct > 15 ? "negative" : "neutral"}
          />
          <Metric
            label="Open Positions"
            value={String(risk.open_positions)}
            tone="neutral"
          />
          <Metric
            label="Closed Trades"
            value={String(risk.total_closed_trades)}
            tone="neutral"
          />
        </div>
      </div>
    </div>
  );
}
