import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Plus, X, RefreshCw, Wifi, WifiOff, Users } from "lucide-react";

interface BrokerConnection {
  id: string;
  name: string;
  broker_type: string;
  server: string;
  connected: boolean;
  account_info?: {
    login: number;
    server: string;
    currency: string;
    balance: number;
    equity: number;
    margin: number;
    free_margin: number;
    profit: number;
    leverage: number;
  };
  last_sync?: string;
}

interface PortfolioSummary {
  total_equity: number;
  total_balance: number;
  total_profit: number;
  broker_count: number;
  connected_count: number;
  brokers: {
    id: string;
    name: string;
    connected: boolean;
    equity: number;
    balance: number;
  }[];
}

interface Position {
  ticket: number;
  symbol: string;
  volume: number;
  open_price: number;
  current_price: number;
  profit: number;
  side: string;
  broker: string;
}

export function MultiBrokerPanel() {
  const [brokers, setBrokers] = useState<BrokerConnection[]>([]);
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [newBroker, setNewBroker] = useState({ name: "", broker_type: "MT5", server: "" });
  const [activeTab, setActiveTab] = useState<"brokers" | "positions" | "portfolio">("brokers");

  const loadBrokers = async () => {
    setLoading(true);
    try {
      const data = await invoke<BrokerConnection[]>("get_broker_connections");
      setBrokers(data);
    } catch (err) {
      console.error("Failed to load brokers:", err);
    } finally {
      setLoading(false);
    }
  };

  const loadPortfolio = async () => {
    try {
      const summary = await invoke<PortfolioSummary>("get_portfolio_summary");
      setPortfolio(summary);
    } catch (err) {
      console.error("Failed to load portfolio:", err);
    }
  };

  const loadPositions = async () => {
    try {
      const pos = await invoke<Position[]>("get_all_positions");
      setPositions(pos);
    } catch (err) {
      console.error("Failed to load positions:", err);
    }
  };

  const handleConnect = async () => {
    setLoading(true);
    try {
      const broker = await invoke<BrokerConnection>("connect_broker", { config: newBroker });
      setBrokers(prev => [...prev, broker]);
      setShowAdd(false);
      setNewBroker({ name: "", broker_type: "MT5", server: "" });
      await loadPortfolio();
    } catch (err) {
      console.error("Failed to connect:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleDisconnect = async (brokerId: string) => {
    try {
      await invoke("disconnect_broker", { brokerId });
      await loadBrokers();
      await loadPortfolio();
    } catch (err) {
      console.error("Failed to disconnect:", err);
    }
  };

  // const handleRemove = async (brokerId: string) => {
  //   try {
  //     await invoke("remove_broker", { brokerId });
  //     await loadBrokers();
  //     await loadPortfolio();
  //   } catch (err) {
  //     console.error("Failed to remove:", err);
  //   }
  // };

  const handleSync = async (brokerId: string) => {
    setSyncing(brokerId);
    try {
      await invoke("sync_broker", { brokerId });
      await loadBrokers();
      await loadPortfolio();
      await loadPositions();
    } catch (err) {
      console.error("Failed to sync:", err);
    } finally {
      setSyncing(null);
    }
  };

  useEffect(() => {
    loadBrokers();
    loadPortfolio();
    loadPositions();
    const interval = setInterval(() => {
      loadBrokers();
      loadPortfolio();
    }, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="card" style={{ height: "100%" }}>
      <div className="card-header">
        <span><Users size={14} /> Multi-Broker Management</span>
        <button className="btn-icon" onClick={() => { loadBrokers(); loadPortfolio(); loadPositions(); }}>
          <RefreshCw size={14} />
        </button>
      </div>
      
      <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {/* Portfolio Summary */}
        {portfolio && (
          <div className="portfolio-summary">
            <div className="summary-item">
              <span className="summary-label">Total Equity</span>
              <span className="summary-value">${portfolio.total_equity.toFixed(2)}</span>
            </div>
            <div className="summary-item">
              <span className="summary-label">Total Profit</span>
              <span className={`summary-value ${portfolio.total_profit >= 0 ? "profit-pos" : "profit-neg"}`}>
                ${portfolio.total_profit.toFixed(2)}
              </span>
            </div>
            <div className="summary-item">
              <span className="summary-label">Brokers</span>
              <span className="summary-value">{portfolio.connected_count}/{portfolio.broker_count}</span>
            </div>
          </div>
        )}

        {/* Tabs */}
        <div className="broker-tabs">
          <button
            className={`tab-btn ${activeTab === "brokers" ? "active" : ""}`}
            onClick={() => setActiveTab("brokers")}
          >
            Brokers
          </button>
          <button
            className={`tab-btn ${activeTab === "positions" ? "active" : ""}`}
            onClick={() => setActiveTab("positions")}
          >
            Positions ({positions.length})
          </button>
          <button
            className={`tab-btn ${activeTab === "portfolio" ? "active" : ""}`}
            onClick={() => setActiveTab("portfolio")}
          >
            Portfolio
          </button>
        </div>

        {/* Brokers List */}
        {activeTab === "brokers" && (
          <div className="brokers-list">
            {brokers.map((broker) => (
              <div key={broker.id} className="broker-item">
                <div className="broker-header">
                  <div className="broker-info">
                    {broker.connected ? (
                      <Wifi size={14} className="status-icon connected" />
                    ) : (
                      <WifiOff size={14} className="status-icon disconnected" />
                    )}
                    <span className="broker-name">{broker.name}</span>
                    <span className="broker-type">{broker.broker_type}</span>
                  </div>
                  <div className="broker-actions">
                    <button
                      className="btn-icon"
                      onClick={() => handleSync(broker.id)}
                      disabled={syncing === broker.id}
                      title="Sync"
                    >
                      <RefreshCw size={12} className={syncing === broker.id ? "spinning" : ""} />
                    </button>
                    {broker.id !== "default" && (
                      <button
                        className="btn-icon"
                        onClick={() => handleDisconnect(broker.id)}
                        title="Disconnect"
                      >
                        <X size={12} />
                      </button>
                    )}
                  </div>
                </div>
                
                {broker.account_info && (
                  <div className="broker-details">
                    <div className="detail-row">
                      <span>Account</span>
                      <span>{broker.account_info.login}</span>
                    </div>
                    <div className="detail-row">
                      <span>Balance</span>
                      <span>${broker.account_info.balance.toFixed(2)}</span>
                    </div>
                    <div className="detail-row">
                      <span>Equity</span>
                      <span>${broker.account_info.equity.toFixed(2)}</span>
                    </div>
                    <div className="detail-row">
                      <span>Profit</span>
                      <span className={broker.account_info.profit >= 0 ? "profit-pos" : "profit-neg"}>
                        ${broker.account_info.profit.toFixed(2)}
                      </span>
                    </div>
                  </div>
                )}
                
                {broker.last_sync && (
                  <div className="broker-sync">
                    Last sync: {new Date(broker.last_sync).toLocaleTimeString()}
                  </div>
                )}
              </div>
            ))}
            
            {showAdd ? (
              <div className="add-broker-form">
                <input
                  type="text"
                  placeholder="Broker Name"
                  value={newBroker.name}
                  onChange={(e) => setNewBroker({ ...newBroker, name: e.target.value })}
                />
                <select
                  value={newBroker.broker_type}
                  onChange={(e) => setNewBroker({ ...newBroker, broker_type: e.target.value })}
                >
                  <option value="MT5">MetaTrader 5</option>
                  <option value="MT4">MetaTrader 4</option>
                  <option value="CTrader">cTrader</option>
                </select>
                <div className="form-actions">
                  <button className="btn btn-secondary" onClick={() => setShowAdd(false)}>Cancel</button>
                  <button className="btn btn-primary" onClick={handleConnect} disabled={loading}>Connect</button>
                </div>
              </div>
            ) : (
              <button className="btn-add-broker" onClick={() => setShowAdd(true)}>
                <Plus size={14} /> Add Broker
              </button>
            )}
          </div>
        )}

        {/* Positions */}
        {activeTab === "positions" && (
          <div className="positions-list">
            {positions.length === 0 ? (
              <p className="empty-text">No open positions</p>
            ) : (
              positions.map((pos) => (
                <div key={`${pos.broker}-${pos.ticket}`} className="position-row">
                  <span className={`side-badge ${pos.side}`}>{pos.side.toUpperCase()}</span>
                  <span className="symbol">{pos.symbol}</span>
                  <span className="volume">{pos.volume.toFixed(2)}</span>
                  <span className="profit">${pos.profit.toFixed(2)}</span>
                  <span className="broker-tag">{pos.broker}</span>
                </div>
              ))
            )}
          </div>
        )}

        {/* Portfolio */}
        {activeTab === "portfolio" && portfolio && (
          <div className="portfolio-details">
            <div className="portfolio-chart">
              {portfolio.brokers.map((broker) => (
                <div key={broker.id} className="broker-bar">
                  <div className="bar-label">
                    <span>{broker.name}</span>
                    <span className={broker.connected ? "connected" : "disconnected"}>
                      {broker.connected ? "●" : "○"}
                    </span>
                  </div>
                  <div className="bar-container">
                    <div
                      className="bar-fill"
                      style={{
                        width: `${(broker.equity / portfolio.total_equity) * 100}%`,
                        background: broker.connected ? "var(--accent)" : "var(--text-muted)"
                      }}
                    />
                  </div>
                  <span className="bar-value">${broker.equity.toFixed(0)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <style>{`
        .portfolio-summary {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 8px;
          padding: 10px;
          background: linear-gradient(135deg, rgba(99, 102, 241, 0.1), rgba(139, 92, 246, 0.1));
          border-radius: 6px;
        }
        .summary-item {
          display: flex;
          flex-direction: column;
          align-items: center;
        }
        .summary-label {
          font-size: 10px;
          color: var(--text-muted);
        }
        .summary-value {
          font-size: 16px;
          font-weight: 700;
        }
        .profit-pos { color: var(--accent); }
        .profit-neg { color: var(--danger); }
        .broker-tabs {
          display: flex;
          gap: 4px;
        }
        .tab-btn {
          flex: 1;
          padding: 8px;
          background: var(--bg-secondary);
          border: none;
          border-radius: 4px;
          color: var(--text-muted);
          font-size: 11px;
          cursor: pointer;
        }
        .tab-btn.active {
          background: var(--accent);
          color: var(--bg-primary);
        }
        .brokers-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .broker-item {
          background: var(--bg-secondary);
          border-radius: 6px;
          padding: 10px;
        }
        .broker-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 8px;
        }
        .broker-info {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .status-icon.connected { color: var(--accent); }
        .status-icon.disconnected { color: var(--text-muted); }
        .broker-name {
          font-weight: 600;
          font-size: 13px;
        }
        .broker-type {
          font-size: 10px;
          color: var(--text-muted);
          padding: 2px 6px;
          background: var(--bg-primary);
          border-radius: 3px;
        }
        .broker-actions {
          display: flex;
          gap: 4px;
        }
        .broker-details {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 4px;
          font-size: 11px;
        }
        .detail-row {
          display: flex;
          justify-content: space-between;
        }
        .detail-row span:first-child {
          color: var(--text-muted);
        }
        .broker-sync {
          font-size: 10px;
          color: var(--text-muted);
          margin-top: 6px;
        }
        .add-broker-form {
          display: flex;
          flex-direction: column;
          gap: 8px;
          padding: 10px;
          background: var(--bg-secondary);
          border-radius: 6px;
        }
        .add-broker-form input, .add-broker-form select {
          padding: 8px;
          background: var(--bg-primary);
          border: 1px solid var(--border);
          border-radius: 4px;
          color: var(--text-primary);
          font-size: 12px;
        }
        .form-actions {
          display: flex;
          gap: 8px;
        }
        .btn-add-broker {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          padding: 10px;
          background: var(--bg-secondary);
          border: 1px dashed var(--border);
          border-radius: 6px;
          color: var(--text-muted);
          cursor: pointer;
          font-size: 12px;
        }
        .btn-add-broker:hover {
          border-color: var(--accent);
          color: var(--accent);
        }
        .positions-list {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .position-row {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 8px;
          background: var(--bg-secondary);
          border-radius: 4px;
          font-size: 11px;
        }
        .side-badge {
          padding: 2px 6px;
          border-radius: 3px;
          font-size: 9px;
          font-weight: 600;
        }
        .side-badge.buy { background: var(--accent); color: white; }
        .side-badge.sell { background: var(--danger); color: white; }
        .symbol { font-weight: 600; }
        .volume { color: var(--text-muted); }
        .profit { margin-left: auto; }
        .broker-tag {
          font-size: 9px;
          padding: 2px 4px;
          background: var(--bg-primary);
          border-radius: 3px;
        }
        .portfolio-chart {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .broker-bar {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .bar-label {
          width: 80px;
          font-size: 11px;
          display: flex;
          justify-content: space-between;
        }
        .bar-container {
          flex: 1;
          height: 12px;
          background: var(--bg-secondary);
          border-radius: 3px;
          overflow: hidden;
        }
        .bar-fill {
          height: 100%;
          border-radius: 3px;
          transition: width 0.3s;
        }
        .bar-value {
          width: 60px;
          text-align: right;
          font-size: 11px;
          font-weight: 600;
        }
        .empty-text {
          text-align: center;
          color: var(--text-muted);
          font-size: 12px;
          padding: 20px;
        }
        .spinning {
          animation: spin 1s linear infinite;
        }
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
