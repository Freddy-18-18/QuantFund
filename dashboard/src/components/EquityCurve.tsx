import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { EquityPoint } from "../types";

interface Props {
  data: EquityPoint[];
  initialBalance: number;
}

function fmtTime(ts: number) {
  return new Date(ts).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function EquityCurve({ data, initialBalance }: Props) {
  const latest = data.length > 0 ? data[data.length - 1].equity : initialBalance;
  const pnl = latest - initialBalance;
  const pnlPct = (pnl / initialBalance) * 100;
  const isPositive = pnl >= 0;

  return (
    <div className="card" style={{ height: "100%" }}>
      <div className="card-header">
        <span>Equity Curve</span>
        <span style={{ color: isPositive ? "var(--accent)" : "var(--danger)", fontFamily: "var(--font-mono)" }}>
          {isPositive ? "+" : ""}{pnlPct.toFixed(2)}%&nbsp;&nbsp;
          {isPositive ? "+" : ""}{pnl.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 })}
        </span>
      </div>
      <div className="card-body" style={{ padding: "8px 4px 4px 0" }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#00e676" stopOpacity={0.25} />
                <stop offset="95%" stopColor="#00e676" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#252535" />
            <XAxis
              dataKey="ts"
              tickFormatter={fmtTime}
              tick={{ fill: "#7070a0", fontSize: 10 }}
              minTickGap={60}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
              tick={{ fill: "#7070a0", fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              width={50}
            />
            <Tooltip
              contentStyle={{ background: "#161620", border: "1px solid #252535", fontFamily: "var(--font-mono)", fontSize: 11 }}
              formatter={(v: number) => [`$${v.toFixed(2)}`, "Equity"]}
              labelFormatter={(ts) => new Date(ts as number).toLocaleString()}
            />
            <ReferenceLine y={initialBalance} stroke="#7070a0" strokeDasharray="4 4" />
            <Area
              type="monotone"
              dataKey="equity"
              stroke="#00e676"
              strokeWidth={1.5}
              fill="url(#equityGrad)"
              dot={false}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
