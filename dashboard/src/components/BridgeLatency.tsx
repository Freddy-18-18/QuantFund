import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
  ResponsiveContainer,
} from "recharts";
import { LatencySample } from "../types";

interface Props {
  data: LatencySample[];
  mode: string;
}

export function BridgeLatency({ data, mode }: Props) {
  const isSimulation = mode === "SIMULATION";

  return (
    <div className="card" style={{ height: "100%" }}>
      <div className="card-header">
        <span>Bridge Latency (µs)</span>
        {isSimulation && (
          <span style={{ color: "var(--accent)", fontFamily: "var(--font-mono)", fontSize: 10 }}>
            SIM · 0µs
          </span>
        )}
      </div>
      <div className="card-body" style={{ padding: "8px 4px 4px 0" }}>
        {isSimulation && data.every((d) => d.latency_us === 0) ? (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              height: "100%",
              gap: 8,
              color: "var(--text-muted)",
              fontFamily: "var(--font-mono)",
            }}
          >
            <div style={{ fontSize: 28, color: "var(--accent)" }}>0µs</div>
            <div style={{ fontSize: 10, letterSpacing: "0.12em" }}>SIMULATION — NO BRIDGE OVERHEAD</div>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#252535" />
              <XAxis
                dataKey="label"
                tick={{ fill: "#7070a0", fontSize: 10 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: "#7070a0", fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                width={40}
              />
              <Tooltip
                contentStyle={{ background: "#161620", border: "1px solid #252535", fontFamily: "var(--font-mono)", fontSize: 11 }}
                formatter={(v: number) => [`${v}µs`, "Latency"]}
              />
              <Bar dataKey="latency_us" radius={[3, 3, 0, 0]}>
                {data.map((_, i) => (
                  <Cell key={i} fill="#00e676" />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
