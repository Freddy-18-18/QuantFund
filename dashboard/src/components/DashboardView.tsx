import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { TrendingUp, Activity, DollarSign, BarChart3, RefreshCw, Wifi, WifiOff, Clock, AlertCircle } from "lucide-react";

interface MT5AccountInfo {
  login: number;
  server: string;
  balance: number;
  equity: number;
  margin: number;
  free_margin: number;
  profit: number;
  currency: string;
}

interface MT5Position {
  ticket: number;
  symbol: string;
  volume: number;
  profit: number;
  open_price: number;
  open_time: string;
  type: string;
}

interface PortfolioSummary {
  total_profit: number;
  total_volume: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
}

interface RecentActivity {
  id: number;
  type: string;
  symbol: string;
  volume: number;
  price: number;
  profit: number;
  time: string;
}

interface ConnectionStatus {
  connected: boolean;
  server: string;
  lastSync: string;
}

const dummyAccountInfo: MT5AccountInfo = {
  login: 123456,
  server: "Demo Server",
  balance: 125430.0,
  equity: 128920.0,
  margin: 5420.0,
  free_margin: 123500.0,
  profit: 3490.0,
  currency: "USD",
};

const dummyPositions: MT5Position[] = [
  { ticket: 1001, symbol: "EURUSD", volume: 1.0, profit: 125.50, open_price: 1.0850, open_time: "2026-03-06 10:30:00", type: "BUY" },
  { ticket: 1002, symbol: "GBPUSD", volume: 0.5, profit: -45.20, open_price: 1.2650, open_time: "2026-03-06 11:15:00", type: "SELL" },
  { ticket: 1003, symbol: "USDJPY", volume: 2.0, profit: 89.30, open_price: 149.50, open_time: "2026-03-06 12:00:00", type: "BUY" },
];

const dummyRecentActivity: RecentActivity[] = [
  { id: 1, type: "BUY", symbol: "EURUSD", volume: 1.0, price: 1.0850, profit: 125.50, time: "2026-03-06 10:30:00" },
  { id: 2, type: "SELL", symbol: "GBPUSD", volume: 0.5, price: 1.2650, profit: -45.20, time: "2026-03-06 11:15:00" },
  { id: 3, type: "BUY", symbol: "USDJPY", volume: 2.0, price: 149.50, profit: 89.30, time: "2026-03-06 12:00:00" },
  { id: 4, type: "CLOSE", symbol: "AUDUSD", volume: 0.8, price: 0.6550, profit: 67.80, time: "2026-03-06 09:45:00" },
];

export function DashboardView() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [accountInfo, setAccountInfo] = useState<MT5AccountInfo | null>(null);
  const [positions, setPositions] = useState<MT5Position[]>([]);
  const [_portfolioSummary, setPortfolioSummary] = useState<PortfolioSummary | null>(null);
  const [recentActivity, setRecentActivity] = useState<RecentActivity[]>([]);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>({
    connected: false,
    server: "No conectado",
    lastSync: "",
  });

  const fetchData = async () => {
    try {
      setError(null);
      
      const [accountData, positionsData, portfolioData, activityData] = await Promise.allSettled([
        invoke<MT5AccountInfo>("mt5_get_account_info"),
        invoke<MT5Position[]>("mt5_get_positions"),
        invoke<PortfolioSummary>("get_portfolio_summary"),
        invoke<RecentActivity[]>("get_recent_activity"),
      ]);

      if (accountData.status === "fulfilled") {
        setAccountInfo(accountData.value);
        setConnectionStatus(prev => ({
          ...prev,
          connected: true,
          server: accountData.value.server,
          lastSync: new Date().toLocaleTimeString(),
        }));
      }

      if (positionsData.status === "fulfilled") {
        setPositions(positionsData.value);
      }

      if (portfolioData.status === "fulfilled") {
        setPortfolioSummary(portfolioData.value);
      }

      if (activityData.status === "fulfilled") {
        setRecentActivity(activityData.value);
      }

    } catch (err) {
      console.warn("MT5 no disponible, usando datos demo:", err);
      setAccountInfo(dummyAccountInfo);
      setPositions(dummyPositions);
      setRecentActivity(dummyRecentActivity);
      setConnectionStatus({
        connected: false,
        server: "Demo Server",
        lastSync: new Date().toLocaleTimeString(),
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    
    const interval = setInterval(() => {
      fetchData();
    }, 30000);
    
    return () => clearInterval(interval);
  }, []);

  const formatCurrency = (value: number, currency: string = "USD") => {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: currency,
    }).format(value);
  };

  const stats = [
    {
      label: "Balance Total",
      value: accountInfo ? formatCurrency(accountInfo.balance, accountInfo.currency) : dummyAccountInfo.balance.toLocaleString("en-US", { style: "currency", currency: "USD" }),
      change: accountInfo?.profit && accountInfo.profit > 0 ? `+${((accountInfo.profit / accountInfo.balance) * 100).toFixed(2)}%` : "+2.4%",
      positive: (accountInfo?.profit ?? dummyAccountInfo.profit) >= 0,
      icon: <DollarSign size={20} />,
    },
    {
      label: "Equity",
      value: accountInfo ? formatCurrency(accountInfo.equity, accountInfo.currency) : dummyAccountInfo.equity.toLocaleString("en-US", { style: "currency", currency: "USD" }),
      change: "+3.1%",
      positive: true,
      icon: <TrendingUp size={20} />,
    },
    {
      label: "Posiciones Abiertas",
      value: positions.length.toString() || dummyPositions.length.toString(),
      change: "0",
      positive: true,
      icon: <Activity size={20} />,
    },
    {
      label: "Margin",
      value: accountInfo ? formatCurrency(accountInfo.margin, accountInfo.currency) : dummyAccountInfo.margin.toLocaleString("en-US", { style: "currency", currency: "USD" }),
      change: `Libre: ${formatCurrency(accountInfo?.free_margin ?? dummyAccountInfo.free_margin, accountInfo?.currency ?? "USD")}`,
      positive: true,
      icon: <BarChart3 size={20} />,
    },
  ];

  if (loading) {
    return (
      <div className="dashboard-view">
        <div className="view-header">
          <h2><Activity size={24} style={{ marginRight: "0.5rem", verticalAlign: "middle" }} />Dashboard</h2>
          <p>Resumen de tu cuenta y rendimiento</p>
        </div>
        <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "300px" }}>
          <RefreshCw className="spin" size={40} style={{ color: "var(--accent-blue)" }} />
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard-view">
      <div className="view-header">
        <h2><Activity size={24} style={{ marginRight: "0.5rem", verticalAlign: "middle" }} />Dashboard</h2>
        <p>Resumen de tu cuenta y rendimiento</p>
      </div>

      <div style={{ 
        display: "flex", 
        gap: "0.75rem", 
        marginBottom: "1.5rem",
        padding: "0.75rem",
        background: "var(--bg-secondary)",
        borderRadius: "0.5rem",
        alignItems: "center",
        flexWrap: "wrap"
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          {connectionStatus.connected ? (
            <Wifi size={18} style={{ color: "var(--accent-green)" }} />
          ) : (
            <WifiOff size={18} style={{ color: "var(--text-secondary)" }} />
          )}
          <span style={{ fontSize: "0.875rem" }}>
            {connectionStatus.connected ? "Conectado" : "Demo"}
          </span>
        </div>
        <div style={{ borderLeft: "1px solid var(--border-color)", paddingLeft: "0.75rem", fontSize: "0.875rem", color: "var(--text-secondary)" }}>
          <Clock size={14} style={{ marginRight: "0.25rem", verticalAlign: "middle" }} />
          {connectionStatus.server}
        </div>
        <div style={{ borderLeft: "1px solid var(--border-color)", paddingLeft: "0.75rem", fontSize: "0.875rem", color: "var(--text-secondary)" }}>
          Sincronizado: {connectionStatus.lastSync || "N/A"}
        </div>
        <button 
          onClick={fetchData}
          style={{ 
            marginLeft: "auto",
            background: "var(--accent-blue)",
            color: "white",
            border: "none",
            padding: "0.5rem 1rem",
            borderRadius: "0.375rem",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: "0.5rem",
            fontSize: "0.875rem"
          }}
        >
          <RefreshCw size={14} /> Actualizar
        </button>
      </div>

      {error && (
        <div style={{ 
          display: "flex", 
          alignItems: "center", 
          gap: "0.5rem", 
          padding: "0.75rem", 
          background: "rgba(239, 68, 68, 0.1)", 
          borderRadius: "0.5rem",
          marginBottom: "1.5rem",
          color: "var(--accent-red)"
        }}>
          <AlertCircle size={18} />
          {error}
        </div>
      )}

      <div className="card-grid">
        {stats.map((stat, index) => (
          <div key={index} className="stat-card">
            <div className="stat-icon" style={{ color: stat.positive ? "var(--accent-green)" : "var(--accent-red)" }}>
              {stat.icon}
            </div>
            <div className="stat-content">
              <div className="stat-label">{stat.label}</div>
              <div className="stat-value">{stat.value}</div>
              <div style={{ color: stat.positive ? "var(--accent-green)" : "var(--accent-red)", fontSize: "0.75rem" }}>
                {stat.change}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div style={{ marginTop: "1.5rem", display: "grid", gridTemplateColumns: "2fr 1fr", gap: "1.5rem" }}>
        <div style={{ background: "var(--bg-secondary)", borderRadius: "0.75rem", padding: "1.5rem" }}>
          <h3 style={{ marginBottom: "1rem" }}><BarChart3 size={20} style={{ marginRight: "0.5rem" }} /> Equity Curve</h3>
          <div style={{ 
            height: "200px", 
            display: "flex", 
            alignItems: "center", 
            justifyContent: "center",
            background: "var(--bg-primary)",
            borderRadius: "0.5rem",
            color: "var(--text-secondary)"
          }}>
            <div style={{ textAlign: "center" }}>
              <TrendingUp size={48} style={{ marginBottom: "0.5rem", opacity: 0.5 }} />
              <p>Gráfico de Equity</p>
              <p style={{ fontSize: "0.75rem" }}> {accountInfo ? formatCurrency(accountInfo.equity, accountInfo.currency) : formatCurrency(dummyAccountInfo.equity)}</p>
            </div>
          </div>
        </div>

        <div style={{ background: "var(--bg-secondary)", borderRadius: "0.75rem", padding: "1.5rem" }}>
          <h3 style={{ marginBottom: "1rem" }}>Posiciones Abiertas</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {positions.length > 0 ? positions.slice(0, 3).map((pos) => (
              <div key={pos.ticket} style={{ 
                padding: "0.5rem", 
                background: "var(--bg-primary)", 
                borderRadius: "0.375rem",
                fontSize: "0.875rem"
              }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ fontWeight: 600 }}>{pos.symbol}</span>
                  <span style={{ color: pos.profit >= 0 ? "var(--accent-green)" : "var(--accent-red)" }}>
                    {pos.profit >= 0 ? "+" : ""}{formatCurrency(pos.profit)}
                  </span>
                </div>
                <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginTop: "0.25rem" }}>
                  {pos.type} · Vol: {pos.volume} · Precio: {pos.open_price}
                </div>
              </div>
            )) : (
              <div style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}>Sin posiciones abiertas</div>
            )}
          </div>
        </div>
      </div>

      <div style={{ marginTop: "1.5rem", background: "var(--bg-secondary)", borderRadius: "0.75rem", padding: "1.5rem" }}>
        <h3 style={{ marginBottom: "1rem" }}><Activity size={20} style={{ marginRight: "0.5rem" }} /> Actividad Reciente</h3>
        <div className="data-table">
          <div style={{ 
            padding: "0.75rem", 
            borderBottom: "1px solid var(--border-color)", 
            display: "grid", 
            gridTemplateColumns: "1fr 1fr 1fr 1fr 1fr 1fr",
            fontSize: "0.75rem",
            color: "var(--text-secondary)",
            fontWeight: 600
          }}>
            <span>Tipo</span>
            <span>Símbolo</span>
            <span>Volumen</span>
            <span>Precio</span>
            <span>Profit</span>
            <span>Hora</span>
          </div>
          {recentActivity.length > 0 ? recentActivity.map((activity) => (
            <div key={activity.id} style={{ 
              padding: "0.75rem", 
              borderBottom: "1px solid var(--border-color)", 
              display: "grid", 
              gridTemplateColumns: "1fr 1fr 1fr 1fr 1fr 1fr",
              fontSize: "0.875rem"
            }}>
              <span style={{ 
                color: activity.type === "BUY" ? "var(--accent-green)" : activity.type === "SELL" ? "var(--accent-red)" : "var(--accent-blue)",
                fontWeight: 600
              }}>
                {activity.type}
              </span>
              <span>{activity.symbol}</span>
              <span>{activity.volume}</span>
              <span>{activity.price}</span>
              <span style={{ color: activity.profit >= 0 ? "var(--accent-green)" : "var(--accent-red)" }}>
                {activity.profit >= 0 ? "+" : ""}{formatCurrency(activity.profit)}
              </span>
              <span style={{ color: "var(--text-secondary)" }}>{activity.time}</span>
            </div>
          )) : (
            <div style={{ padding: "0.75rem", color: "var(--text-secondary)" }}>
              No hay actividad reciente
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default DashboardView;
