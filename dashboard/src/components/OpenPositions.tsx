import { PositionSnapshot } from "../types";

interface Props {
  positions: PositionSnapshot[];
}

export function OpenPositions({ positions }: Props) {
  return (
    <div className="card" style={{ height: "100%" }}>
      <div className="card-header">
        <span>Open Positions</span>
        <span style={{ fontFamily: "var(--font-mono)" }}>{positions.length}</span>
      </div>
      <div className="card-body" style={{ overflowY: "auto" }}>
        {positions.length === 0 ? (
          <div style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 11, paddingTop: 8 }}>
            No open positions
          </div>
        ) : (
          <table className="pos-table">
            <thead>
              <tr>
                <th>Instrument</th>
                <th>Side</th>
                <th>Volume</th>
                <th>Entry</th>
                <th>Unrl. PnL</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p, i) => (
                <tr key={i}>
                  <td>{p.instrument}</td>
                  <td className={p.side === "Buy" ? "side-buy" : "side-sell"}>{p.side}</td>
                  <td>{p.volume.toFixed(2)}</td>
                  <td style={{ fontFamily: "var(--font-mono)" }}>{p.entry_price.toFixed(5)}</td>
                  <td
                    style={{
                      fontFamily: "var(--font-mono)",
                      color: p.unrealized_pnl >= 0 ? "var(--accent)" : "var(--danger)",
                    }}
                  >
                    {p.unrealized_pnl >= 0 ? "+" : ""}
                    {p.unrealized_pnl.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
