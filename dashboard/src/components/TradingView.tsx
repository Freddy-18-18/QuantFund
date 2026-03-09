import { Target, Zap } from "lucide-react";

export function TradingView() {
  const signals = [
    { type: "BUY", symbol: "XAUUSD", price: "2650.00", time: "10:30", strength: "ALTA" },
    { type: "SELL", symbol: "XAUUSD", price: "2645.00", time: "09:15", strength: "MEDIA" },
  ];

  return (
    <div className="trading-view">
      <div className="view-header">
        <h2><Target size={24} style={{ marginRight: "0.5rem", verticalAlign: "middle" }} />Trading</h2>
        <p>Señales y oportunidades de trading</p>
      </div>

      <div className="card-grid">
        <div style={{ background: "var(--bg-secondary)", borderRadius: "0.75rem", padding: "1.5rem" }}>
          <h3 style={{ marginBottom: "1rem" }}><Zap size={18} style={{ marginRight: "0.5rem" }} />Señales Activas</h3>
          {signals.map((signal, index) => (
            <div key={index} style={{ padding: "0.75rem", background: "var(--bg-tertiary)", borderRadius: "0.5rem", marginBottom: "0.75rem", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <span style={{ background: signal.type === "BUY" ? "var(--accent-green)" : "var(--accent-red)", padding: "0.25rem 0.5rem", borderRadius: "0.25rem", fontSize: "0.75rem", fontWeight: "bold", marginRight: "0.5rem" }}>{signal.type}</span>
                <span style={{ fontWeight: "600" }}>{signal.symbol}</span>
              </div>
              <div style={{ textAlign: "right" }}>
                <div style={{ fontWeight: "600" }}>${signal.price}</div>
                <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)" }}>{signal.time}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default TradingView;
