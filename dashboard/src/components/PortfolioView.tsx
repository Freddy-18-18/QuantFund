import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Briefcase, Plus, X, RefreshCw, TrendingUp, TrendingDown, Wallet, BarChart3 } from "lucide-react";

interface BrokerConnection {
  id: string;
  name: string;
  server: string;
  connected: boolean;
  balance?: number;
  equity?: number;
}

interface Position {
  ticket: number;
  symbol: string;
  volume: number;
  open_price: number;
  current_price: number;
  profit: number;
  type: "buy" | "sell";
  time: string;
}

interface Order {
  ticket: number;
  symbol: string;
  volume: number;
  open_price: number;
  type: "buy_limit" | "sell_limit" | "buy_stop" | "sell_stop";
  time: string;
}

interface Deal {
  ticket: number;
  symbol: string;
  volume: number;
  open_price: number;
  close_price: number;
  profit: number;
  type: "buy" | "sell";
  time: string;
}

export function PortfolioView() {
  const [connections, setConnections] = useState<BrokerConnection[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [deals, setDeals] = useState<Deal[]>([]);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [closingPosition, setClosingPosition] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<"positions" | "orders" | "history">("positions");

  const fetchData = async () => {
    setLoading(true);
    try {
      const [conns, poss, ords, ds] = await Promise.all([
        invoke<BrokerConnection[]>("get_broker_connections").catch(() => []),
        invoke<Position[]>("mt5_get_positions").catch(() => []),
        invoke<Order[]>("mt5_get_orders").catch(() => []),
        invoke<Deal[]>("mt5_get_deals").catch(() => [])
      ]);
      setConnections(conns);
      setPositions(poss);
      setOrders(ords);
      setDeals(ds);
    } catch (error) {
      console.error("Error fetching portfolio data:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleConnectBroker = async () => {
    setConnecting(true);
    try {
      await invoke("connect_broker");
      await fetchData();
    } catch (error) {
      console.error("Error connecting broker:", error);
    } finally {
      setConnecting(false);
    }
  };

  const handleClosePosition = async (ticket: number) => {
    setClosingPosition(ticket);
    try {
      await invoke("mt5_close_position", { ticket });
      await fetchData();
    } catch (error) {
      console.error("Error closing position:", error);
    } finally {
      setClosingPosition(null);
    }
  };

  const totalEquity = connections.reduce((sum, c) => sum + (c.equity || c.balance || 0), 0);
  const totalProfit = positions.reduce((sum, p) => sum + p.profit, 0);
  const exposureBySymbol = positions.reduce((acc, p) => {
    acc[p.symbol] = (acc[p.symbol] || 0) + p.volume;
    return acc;
  }, {} as Record<string, number>);

  const dummyConnections: BrokerConnection[] = [
    { id: "demo-1", name: "Primary MT5", server: "Demo-Demo", connected: false, balance: 0, equity: 0 }
  ];

  const dummyPositions: Position[] = [];
  const dummyOrders: Order[] = [];
  const dummyDeals: Deal[] = [];

  const displayConnections = connections.length > 0 ? connections : dummyConnections;
  const displayPositions = positions.length > 0 || connections.length === 0 ? positions : dummyPositions;
  const displayOrders = orders.length > 0 || connections.length === 0 ? orders : dummyOrders;
  const displayDeals = deals.length > 0 || connections.length === 0 ? deals : dummyDeals;

  const isConnected = connections.some(c => c.connected);

  return (
    <div className="portfolio-view">
      <div className="view-header">
        <h2><Briefcase size={24} style={{ marginRight: "0.5rem", verticalAlign: "middle" }} />Portafolio</h2>
        <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
          <p>Gestiona tus cuentas y posiciones</p>
          <button
            onClick={fetchData}
            disabled={loading}
            style={{ padding: "0.5rem", background: "var(--bg-tertiary)", border: "none", borderRadius: "0.5rem", cursor: "pointer", display: "flex", alignItems: "center" }}
            title="Actualizar"
          >
            <RefreshCw size={18} style={{ animation: loading ? "spin 1s linear infinite" : "none" }} />
          </button>
        </div>
      </div>

      <div className="card-grid">
        <div style={{ background: "var(--bg-secondary)", borderRadius: "0.75rem", padding: "1.5rem" }}>
          <h3 style={{ marginBottom: "1rem" }}>Cuentas Conectadas</h3>
          {displayConnections.map((conn) => (
            <div key={conn.id} style={{ padding: "1rem", background: "var(--bg-tertiary)", borderRadius: "0.5rem", marginBottom: "0.75rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.5rem" }}>
                <span style={{ fontWeight: "600" }}>{conn.name}</span>
                <span style={{ color: conn.connected ? "var(--accent-green)" : "var(--text-secondary)", fontSize: "0.75rem" }}>
                  ● {conn.connected ? "Conectado" : "Desconectado"}
                </span>
              </div>
              <div style={{ fontSize: "0.875rem", color: "var(--text-secondary)" }}>
                {conn.connected ? (
                  <>
                    <div>Server: {conn.server}</div>
                    <div>Balance: ${conn.balance?.toFixed(2) || "0.00"}</div>
                    <div>Equity: ${conn.equity?.toFixed(2) || "0.00"}</div>
                  </>
                ) : (
                  <div>Sin conexión</div>
                )}
              </div>
            </div>
          ))}
          <button
            onClick={handleConnectBroker}
            disabled={connecting}
            style={{ width: "100%", padding: "0.625rem", background: "var(--bg-tertiary)", border: "1px dashed var(--border-color)", borderRadius: "0.5rem", color: "var(--text-secondary)", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: "0.5rem" }}
          >
            <Plus size={18} /> {connecting ? "Conectando..." : "Agregar Cuenta"}
          </button>
        </div>

        <div style={{ background: "var(--bg-secondary)", borderRadius: "0.75rem", padding: "1.5rem" }}>
          <h3 style={{ marginBottom: "1rem" }}>Métricas del Portafolio</h3>
          <div style={{ display: "grid", gap: "1rem" }}>
            <div style={{ padding: "1rem", background: "var(--bg-tertiary)", borderRadius: "0.5rem" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem" }}>
                <Wallet size={18} />
                <span style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}>Total Equity</span>
              </div>
              <div style={{ fontSize: "1.5rem", fontWeight: "600" }}>${totalEquity.toFixed(2)}</div>
            </div>
            <div style={{ padding: "1rem", background: "var(--bg-tertiary)", borderRadius: "0.5rem" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem" }}>
                {totalProfit >= 0 ? <TrendingUp size={18} style={{ color: "var(--accent-green)" }} /> : <TrendingDown size={18} style={{ color: "var(--accent-red)" }} />}
                <span style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}>Profit/Pérdida</span>
              </div>
              <div style={{ fontSize: "1.5rem", fontWeight: "600", color: totalProfit >= 0 ? "var(--accent-green)" : "var(--accent-red)" }}>
                {totalProfit >= 0 ? "+" : ""}{totalProfit.toFixed(2)}
              </div>
            </div>
            <div style={{ padding: "1rem", background: "var(--bg-tertiary)", borderRadius: "0.5rem" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem" }}>
                <BarChart3 size={18} />
                <span style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}>Exposición por Símbolo</span>
              </div>
              {Object.keys(exposureBySymbol).length > 0 ? (
                <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
                  {Object.entries(exposureBySymbol).map(([symbol, volume]) => (
                    <span key={symbol} style={{ padding: "0.25rem 0.5rem", background: "var(--bg-secondary)", borderRadius: "0.25rem", fontSize: "0.75rem" }}>
                      {symbol}: {volume}
                    </span>
                  ))}
                </div>
              ) : (
                <div style={{ fontSize: "0.875rem", color: "var(--text-secondary)" }}>Sin exposición</div>
              )}
            </div>
          </div>
        </div>
      </div>

      <div style={{ background: "var(--bg-secondary)", borderRadius: "0.75rem", padding: "1.5rem", marginTop: "1rem" }}>
        <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
          <button
            onClick={() => setActiveTab("positions")}
            style={{ padding: "0.5rem 1rem", background: activeTab === "positions" ? "var(--accent-blue)" : "var(--bg-tertiary)", border: "none", borderRadius: "0.5rem", color: "var(--text-primary)", cursor: "pointer" }}
          >
            Posiciones ({displayPositions.length})
          </button>
          <button
            onClick={() => setActiveTab("orders")}
            style={{ padding: "0.5rem 1rem", background: activeTab === "orders" ? "var(--accent-blue)" : "var(--bg-tertiary)", border: "none", borderRadius: "0.5rem", color: "var(--text-primary)", cursor: "pointer" }}
          >
            Órdenes Pendientes ({displayOrders.length})
          </button>
          <button
            onClick={() => setActiveTab("history")}
            style={{ padding: "0.5rem 1rem", background: activeTab === "history" ? "var(--accent-blue)" : "var(--bg-tertiary)", border: "none", borderRadius: "0.5rem", color: "var(--text-primary)", cursor: "pointer" }}
          >
            Historial ({displayDeals.length})
          </button>
        </div>

        {loading ? (
          <div style={{ textAlign: "center", padding: "2rem", color: "var(--text-secondary)" }}>Cargando...</div>
        ) : !isConnected ? (
          <div style={{ textAlign: "center", padding: "2rem", color: "var(--text-secondary)" }}>
            MT5 no conectado. Conecta una cuenta para ver posiciones.
          </div>
        ) : (
          <>
            {activeTab === "positions" && (
              displayPositions.length > 0 ? (
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ borderBottom: "1px solid var(--border-color)" }}>
                        <th style={{ padding: "0.75rem", textAlign: "left", fontSize: "0.875rem", color: "var(--text-secondary)" }}>Símbolo</th>
                        <th style={{ padding: "0.75rem", textAlign: "right", fontSize: "0.875rem", color: "var(--text-secondary)" }}>Volumen</th>
                        <th style={{ padding: "0.75rem", textAlign: "right", fontSize: "0.875rem", color: "var(--text-secondary)" }}>Apertura</th>
                        <th style={{ padding: "0.75rem", textAlign: "right", fontSize: "0.875rem", color: "var(--text-secondary)" }}>Actual</th>
                        <th style={{ padding: "0.75rem", textAlign: "right", fontSize: "0.875rem", color: "var(--text-secondary)" }}>Profit</th>
                        <th style={{ padding: "0.75rem", textAlign: "center", fontSize: "0.875rem", color: "var(--text-secondary)" }}>Tipo</th>
                        <th style={{ padding: "0.75rem", textAlign: "center", fontSize: "0.875rem", color: "var(--text-secondary)" }}>Acción</th>
                      </tr>
                    </thead>
                    <tbody>
                      {displayPositions.map((pos) => (
                        <tr key={pos.ticket} style={{ borderBottom: "1px solid var(--border-color)" }}>
                          <td style={{ padding: "0.75rem", fontWeight: "600" }}>{pos.symbol}</td>
                          <td style={{ padding: "0.75rem", textAlign: "right" }}>{pos.volume}</td>
                          <td style={{ padding: "0.75rem", textAlign: "right" }}>{pos.open_price.toFixed(5)}</td>
                          <td style={{ padding: "0.75rem", textAlign: "right" }}>{pos.current_price.toFixed(5)}</td>
                          <td style={{ padding: "0.75rem", textAlign: "right", color: pos.profit >= 0 ? "var(--accent-green)" : "var(--accent-red)" }}>
                            {pos.profit >= 0 ? "+" : ""}{pos.profit.toFixed(2)}
                          </td>
                          <td style={{ padding: "0.75rem", textAlign: "center" }}>
                            <span style={{ padding: "0.25rem 0.5rem", borderRadius: "0.25rem", fontSize: "0.75rem", background: pos.type === "buy" ? "rgba(34, 197, 94, 0.2)" : "rgba(239, 68, 68, 0.2)", color: pos.type === "buy" ? "var(--accent-green)" : "var(--accent-red)" }}>
                              {pos.type.toUpperCase()}
                            </span>
                          </td>
                          <td style={{ padding: "0.75rem", textAlign: "center" }}>
                            <button
                              onClick={() => handleClosePosition(pos.ticket)}
                              disabled={closingPosition === pos.ticket}
                              style={{ padding: "0.375rem 0.75rem", background: "var(--accent-red)", border: "none", borderRadius: "0.375rem", color: "white", cursor: "pointer", fontSize: "0.75rem", display: "inline-flex", alignItems: "center", gap: "0.25rem" }}
                            >
                              <X size={14} /> {closingPosition === pos.ticket ? "Cerrando..." : "Cerrar"}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div style={{ textAlign: "center", padding: "2rem", color: "var(--text-secondary)" }}>No hay posiciones abiertas</div>
              )
            )}

            {activeTab === "orders" && (
              displayOrders.length > 0 ? (
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ borderBottom: "1px solid var(--border-color)" }}>
                        <th style={{ padding: "0.75rem", textAlign: "left", fontSize: "0.875rem", color: "var(--text-secondary)" }}>Símbolo</th>
                        <th style={{ padding: "0.75rem", textAlign: "right", fontSize: "0.875rem", color: "var(--text-secondary)" }}>Volumen</th>
                        <th style={{ padding: "0.75rem", textAlign: "right", fontSize: "0.875rem", color: "var(--text-secondary)" }}>Precio</th>
                        <th style={{ padding: "0.75rem", textAlign: "center", fontSize: "0.875rem", color: "var(--text-secondary)" }}>Tipo</th>
                        <th style={{ padding: "0.75rem", textAlign: "left", fontSize: "0.875rem", color: "var(--text-secondary)" }}>Fecha</th>
                      </tr>
                    </thead>
                    <tbody>
                      {displayOrders.map((order) => (
                        <tr key={order.ticket} style={{ borderBottom: "1px solid var(--border-color)" }}>
                          <td style={{ padding: "0.75rem", fontWeight: "600" }}>{order.symbol}</td>
                          <td style={{ padding: "0.75rem", textAlign: "right" }}>{order.volume}</td>
                          <td style={{ padding: "0.75rem", textAlign: "right" }}>{order.open_price.toFixed(5)}</td>
                          <td style={{ padding: "0.75rem", textAlign: "center" }}>
                            <span style={{ padding: "0.25rem 0.5rem", borderRadius: "0.25rem", fontSize: "0.75rem", background: "var(--bg-tertiary)" }}>
                              {order.type.replace("_", " ").toUpperCase()}
                            </span>
                          </td>
                          <td style={{ padding: "0.75rem", fontSize: "0.875rem", color: "var(--text-secondary)" }}>{order.time}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div style={{ textAlign: "center", padding: "2rem", color: "var(--text-secondary)" }}>No hay órdenes pendientes</div>
              )
            )}

            {activeTab === "history" && (
              displayDeals.length > 0 ? (
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ borderBottom: "1px solid var(--border-color)" }}>
                        <th style={{ padding: "0.75rem", textAlign: "left", fontSize: "0.875rem", color: "var(--text-secondary)" }}>Símbolo</th>
                        <th style={{ padding: "0.75rem", textAlign: "right", fontSize: "0.875rem", color: "var(--text-secondary)" }}>Volumen</th>
                        <th style={{ padding: "0.75rem", textAlign: "right", fontSize: "0.875rem", color: "var(--text-secondary)" }}>Apertura</th>
                        <th style={{ padding: "0.75rem", textAlign: "right", fontSize: "0.875rem", color: "var(--text-secondary)" }}>Cierre</th>
                        <th style={{ padding: "0.75rem", textAlign: "right", fontSize: "0.875rem", color: "var(--text-secondary)" }}>Profit</th>
                        <th style={{ padding: "0.75rem", textAlign: "center", fontSize: "0.875rem", color: "var(--text-secondary)" }}>Tipo</th>
                      </tr>
                    </thead>
                    <tbody>
                      {displayDeals.map((deal) => (
                        <tr key={deal.ticket} style={{ borderBottom: "1px solid var(--border-color)" }}>
                          <td style={{ padding: "0.75rem", fontWeight: "600" }}>{deal.symbol}</td>
                          <td style={{ padding: "0.75rem", textAlign: "right" }}>{deal.volume}</td>
                          <td style={{ padding: "0.75rem", textAlign: "right" }}>{deal.open_price.toFixed(5)}</td>
                          <td style={{ padding: "0.75rem", textAlign: "right" }}>{deal.close_price.toFixed(5)}</td>
                          <td style={{ padding: "0.75rem", textAlign: "right", color: deal.profit >= 0 ? "var(--accent-green)" : "var(--accent-red)" }}>
                            {deal.profit >= 0 ? "+" : ""}{deal.profit.toFixed(2)}
                          </td>
                          <td style={{ padding: "0.75rem", textAlign: "center" }}>
                            <span style={{ padding: "0.25rem 0.5rem", borderRadius: "0.25rem", fontSize: "0.75rem", background: deal.type === "buy" ? "rgba(34, 197, 94, 0.2)" : "rgba(239, 68, 68, 0.2)", color: deal.type === "buy" ? "var(--accent-green)" : "var(--accent-red)" }}>
                              {deal.type.toUpperCase()}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div style={{ textAlign: "center", padding: "2rem", color: "var(--text-secondary)" }}>No hay historial de operaciones</div>
              )
            )}
          </>
        )}
      </div>

      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}

export default PortfolioView;
