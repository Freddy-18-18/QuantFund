import { ConnectionStatus as ConnStatus } from "../types";

interface Props {
  connection: ConnStatus;
}

function modeCls(mode: string) {
  if (mode === "SIMULATION") return "mode-sim";
  if (mode === "PAPER") return "mode-paper";
  return "mode-live";
}

export function ConnectionStatus({ connection }: Props) {
  return (
    <div className="card" style={{ height: "100%" }}>
      <div className="card-header">
        <span>MT5 Connection</span>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: connection.connected ? "var(--accent)" : "var(--danger)",
          }}
        >
          {connection.connected ? "CONNECTED" : "DISCONNECTED"}
        </span>
      </div>
      <div className="card-body">
        <div className="conn-wrap">
          <div>
            <span className={`mode-badge ${modeCls(connection.mode)}`}>{connection.mode}</span>
          </div>
          <div className="conn-row">
            <span>Ping</span>
            <span className="conn-val" style={{ fontFamily: "var(--font-mono)" }}>
              {connection.ping_ms === 0 ? "—" : `${connection.ping_ms.toFixed(1)}ms`}
            </span>
          </div>
          <div>
            <div className="conn-row" style={{ marginBottom: 4 }}>
              <span>Symbols</span>
              <span className="conn-val">{connection.symbols.length}</span>
            </div>
            <div className="symbols-list">
              {connection.symbols.map((s) => (
                <span key={s} className="symbol-chip">{s}</span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
