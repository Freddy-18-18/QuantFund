import { useRef, useEffect } from "react";
import { OrderLogEntry } from "../types";

interface Props {
  entries: OrderLogEntry[];
}

function fmtTs(ts: number) {
  return new Date(ts).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function OrderLog({ entries }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new entries.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries.length]);

  return (
    <div className="card" style={{ height: "100%" }}>
      <div className="card-header">
        <span>Order / Fill Log</span>
        <span style={{ fontFamily: "var(--font-mono)" }}>{entries.length} events</span>
      </div>
      <div className="card-body" style={{ padding: 0 }}>
        <div className="order-log" style={{ padding: "4px 8px" }}>
          {entries.length === 0 && (
            <div style={{ color: "var(--text-muted)", paddingTop: 8 }}>Waiting for events…</div>
          )}
          {entries.map((e, i) => (
            <div className="log-entry" key={i}>
              <span className="log-ts">{fmtTs(e.ts)}</span>
              <span className={`log-badge badge-${e.event_type.toLowerCase()}`}>
                {e.event_type}
              </span>
              <span className="log-body">
                <span className={e.side === "Buy" ? "side-buy" : "side-sell"}>{e.side}</span>
                &nbsp;{e.volume.toFixed(2)} {e.instrument} @ {e.price.toFixed(5)}
                &nbsp;<span style={{ color: "var(--text-muted)" }}>{e.note}</span>
              </span>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  );
}
