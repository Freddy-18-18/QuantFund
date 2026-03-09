import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Activity, Wallet, TrendingUp, AlertTriangle, X, ArrowUp, ArrowDown } from "lucide-react";
import type { Mt5AccountInfo, Mt5Position, Mt5Deal, Mt5Order } from "../types";

interface Mt5TradeResult {
  success: boolean;
  order_ticket: number | null;
  deal_ticket: number | null;
  message: string;
}

interface Mt5OrderRequest {
  symbol: string;
  volume: number;
  side: string;
  price: number | null;
  sl: number | null;
  tp: number | null;
  comment: string | null;
}

interface Props {
  onConnectionChange: (connected: boolean) => void;
}

export function Mt5Panel({ onConnectionChange }: Props) {
  const [account, setAccount] = useState<Mt5AccountInfo | null>(null);
  const [positions, setPositions] = useState<Mt5Position[]>([]);
  const [orders, setOrders] = useState<Mt5Order[]>([]);
  const [deals, setDeals] = useState<Mt5Deal[]>([]);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"account" | "positions" | "orders" | "history" | "trade">("account");

  const checkConnection = async () => {
    try {
      const initialized = await invoke<boolean>("mt5_is_initialized");
      setConnected(initialized);
      onConnectionChange(initialized);
      if (initialized) {
        await fetchAccountInfo();
      }
    } catch (err) {
      console.error("Connection check failed:", err);
      setConnected(false);
      onConnectionChange(false);
    }
  };

  const fetchAccountInfo = async () => {
    try {
      const info = await invoke<Mt5AccountInfo | null>("mt5_get_account_info");
      setAccount(info);
    } catch (err) {
      console.error("Failed to fetch account info:", err);
    }
  };

  const fetchPositions = async () => {
    try {
      const pos = await invoke<Mt5Position[]>("mt5_get_positions");
      setPositions(pos);
    } catch (err) {
      console.error("Failed to fetch positions:", err);
    }
  };

  const fetchOrders = async () => {
    try {
      const ord = await invoke<Mt5Order[]>("mt5_get_orders");
      setOrders(ord);
    } catch (err) {
      console.error("Failed to fetch orders:", err);
    }
  };

  const fetchDeals = async () => {
    try {
      const d = await invoke<Mt5Deal[]>("mt5_get_deals", { fromDate: null, toDate: null });
      setDeals(d);
    } catch (err) {
      console.error("Failed to fetch deals:", err);
    }
  };

  const handleConnect = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await invoke<boolean>("mt5_initialize", { path: null });
      if (result) {
        setConnected(true);
        onConnectionChange(true);
        await fetchAccountInfo();
      } else {
        setError("Failed to initialize MT5");
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  };

  const handleDisconnect = async () => {
    setLoading(true);
    try {
      await invoke<boolean>("mt5_shutdown");
      setConnected(false);
      onConnectionChange(false);
      setAccount(null);
    } catch (err) {
      console.error("Failed to shutdown MT5:", err);
    } finally {
      setLoading(false);
    }
  };

  const [tradeForm, setTradeForm] = useState({
    symbol: "XAUUSD",
    volume: 0.01,
    side: "buy" as "buy" | "sell",
    sl: 0,
    tp: 0,
    useSl: false,
    useTp: false,
  });
  const [placingOrder, setPlacingOrder] = useState(false);

  const handlePlaceOrder = async () => {
    setPlacingOrder(true);
    setError(null);
    try {
      const request: Mt5OrderRequest = {
        symbol: tradeForm.symbol,
        volume: tradeForm.volume,
        side: tradeForm.side,
        price: null,
        sl: tradeForm.useSl ? tradeForm.sl : null,
        tp: tradeForm.useTp ? tradeForm.tp : null,
        comment: "QuantFund Dashboard",
      };
      const result = await invoke<Mt5TradeResult>("mt5_place_order", { request });
      if (result.success) {
        await fetchPositions();
        await fetchAccountInfo();
      } else {
        setError(result.message);
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setPlacingOrder(false);
    }
  };

  const handleClosePosition = async (ticket: number) => {
    setLoading(true);
    setError(null);
    try {
      const result = await invoke<Mt5TradeResult>("mt5_close_position", { ticket, volume: null });
      if (result.success) {
        await fetchPositions();
        await fetchAccountInfo();
      } else {
        setError(result.message);
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  };

  const handleCancelOrder = async (ticket: number) => {
    setLoading(true);
    setError(null);
    try {
      const result = await invoke<Mt5TradeResult>("mt5_cancel_order", { ticket });
      if (result.success) {
        await fetchOrders();
      } else {
        setError(result.message);
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    checkConnection();
    const interval = setInterval(checkConnection, 30000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (connected) {
      if (activeTab === "account") fetchAccountInfo();
      if (activeTab === "positions") fetchPositions();
      if (activeTab === "orders") fetchOrders();
      if (activeTab === "history") fetchDeals();
    }
  }, [connected, activeTab]);

  return (
    <div className="card" style={{ height: "100%" }}>
      <div className="card-header">
        <span>MT5 Trading</span>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: connected ? "var(--accent)" : "var(--danger)",
          }}
        >
          {connected ? "CONNECTED" : "DISCONNECTED"}
        </span>
      </div>
      
      <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {!connected ? (
          <div style={{ textAlign: "center", padding: 20 }}>
            <Activity size={32} style={{ marginBottom: 8, opacity: 0.5 }} />
            <p style={{ marginBottom: 12, color: "var(--text-muted)" }}>
              Connect to MT5 to view account and trade
            </p>
            <button
              className="btn btn-primary"
              onClick={handleConnect}
              disabled={loading}
            >
              {loading ? "Connecting..." : "Connect to MT5"}
            </button>
            {error && <p style={{ color: "var(--danger)", marginTop: 8 }}>{error}</p>}
          </div>
        ) : (
          <>
            <div className="tab-row">
              <button
                className={`tab-btn ${activeTab === "account" ? "active" : ""}`}
                onClick={() => setActiveTab("account")}
              >
                Account
              </button>
              <button
                className={`tab-btn ${activeTab === "trade" ? "active" : ""}`}
                onClick={() => setActiveTab("trade")}
              >
                Trade
              </button>
              <button
                className={`tab-btn ${activeTab === "positions" ? "active" : ""}`}
                onClick={() => setActiveTab("positions")}
              >
                Positions ({positions.length})
              </button>
              <button
                className={`tab-btn ${activeTab === "orders" ? "active" : ""}`}
                onClick={() => setActiveTab("orders")}
              >
                Orders ({orders.length})
              </button>
              <button
                className={`tab-btn ${activeTab === "history" ? "active" : ""}`}
                onClick={() => setActiveTab("history")}
              >
                History
              </button>
            </div>

            {activeTab === "account" && account && (
              <div className="account-info">
                <div className="account-row">
                  <span><Wallet size={14} /> Account</span>
                  <span>{account.login}</span>
                </div>
                <div className="account-row">
                  <span>Server</span>
                  <span>{account.server}</span>
                </div>
                <div className="account-row highlight">
                  <span><TrendingUp size={14} /> Balance</span>
                  <span>${account.balance.toFixed(2)}</span>
                </div>
                <div className="account-row">
                  <span>Equity</span>
                  <span style={{ color: account.equity >= account.balance ? "var(--accent)" : "var(--danger)" }}>
                    ${account.equity.toFixed(2)}
                  </span>
                </div>
                <div className="account-row">
                  <span>Margin</span>
                  <span>${account.margin.toFixed(2)}</span>
                </div>
                <div className="account-row">
                  <span>Free Margin</span>
                  <span>${account.free_margin.toFixed(2)}</span>
                </div>
                <div className="account-row">
                  <span>Margin Level</span>
                  <span style={{ 
                    color: account.margin_level > 150 ? "var(--accent)" : 
                           account.margin_level > 100 ? "var(--warning)" : "var(--danger)" 
                  }}>
                    {account.margin_level.toFixed(1)}%
                  </span>
                </div>
                <div className="account-row">
                  <span><AlertTriangle size={14} /> P&L Today</span>
                  <span style={{ color: account.profit >= 0 ? "var(--accent)" : "var(--danger)" }}>
                    ${account.profit.toFixed(2)}
                  </span>
                </div>
                <div className="account-row">
                  <span>Leverage</span>
                  <span>1:{account.leverage}</span>
                </div>
              </div>
            )}

            {activeTab === "trade" && (
              <div className="trade-panel">
                <div className="trade-form">
                  <div className="trade-row">
                    <label>Symbol</label>
                    <select
                      value={tradeForm.symbol}
                      onChange={(e) => setTradeForm({ ...tradeForm, symbol: e.target.value })}
                      className="trade-input"
                    >
                      <option value="XAUUSD">XAUUSD</option>
                      <option value="EURUSD">EURUSD</option>
                      <option value="GBPUSD">GBPUSD</option>
                      <option value="USDJPY">USDJPY</option>
                      <option value="BTCUSD">BTCUSD</option>
                    </select>
                  </div>
                  <div className="trade-row">
                    <label>Volume (lots)</label>
                    <input
                      type="number"
                      step="0.01"
                      min="0.01"
                      value={tradeForm.volume}
                      onChange={(e) => setTradeForm({ ...tradeForm, volume: parseFloat(e.target.value) })}
                      className="trade-input"
                    />
                  </div>
                  <div className="trade-row">
                    <label>Stop Loss</label>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <input
                        type="checkbox"
                        checked={tradeForm.useSl}
                        onChange={(e) => setTradeForm({ ...tradeForm, useSl: e.target.checked })}
                      />
                      {tradeForm.useSl && (
                        <input
                          type="number"
                          step="0.01"
                          value={tradeForm.sl}
                          onChange={(e) => setTradeForm({ ...tradeForm, sl: parseFloat(e.target.value) })}
                          className="trade-input"
                        />
                      )}
                    </div>
                  </div>
                  <div className="trade-row">
                    <label>Take Profit</label>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <input
                        type="checkbox"
                        checked={tradeForm.useTp}
                        onChange={(e) => setTradeForm({ ...tradeForm, useTp: e.target.checked })}
                      />
                      {tradeForm.useTp && (
                        <input
                          type="number"
                          step="0.01"
                          value={tradeForm.tp}
                          onChange={(e) => setTradeForm({ ...tradeForm, tp: parseFloat(e.target.value) })}
                          className="trade-input"
                        />
                      )}
                    </div>
                  </div>
                  <div className="trade-buttons">
                    <button
                      className="btn btn-buy"
                      onClick={() => { setTradeForm({ ...tradeForm, side: "buy" }); handlePlaceOrder(); }}
                      disabled={placingOrder}
                    >
                      <ArrowUp size={16} /> Buy
                    </button>
                    <button
                      className="btn btn-sell"
                      onClick={() => { setTradeForm({ ...tradeForm, side: "sell" }); handlePlaceOrder(); }}
                      disabled={placingOrder}
                    >
                      <ArrowDown size={16} /> Sell
                    </button>
                  </div>
                </div>
              </div>
            )}

            {activeTab === "positions" && (
              <div className="positions-list">
                {positions.length === 0 ? (
                  <p style={{ textAlign: "center", color: "var(--text-muted)" }}>No open positions</p>
                ) : (
                  positions.map((pos) => (
                    <div key={pos.ticket} className="position-item">
                      <div className="position-header">
                        <span className={`side-badge ${pos.side.toLowerCase()}`}>{pos.side}</span>
                        <span className="symbol">{pos.symbol}</span>
                        <span className="volume">{pos.volume.toFixed(2)} lots</span>
                      </div>
                      <div className="position-details">
                        <span>Entry: ${pos.open_price.toFixed(5)}</span>
                        <span>Current: ${pos.current_price.toFixed(5)}</span>
                        <span className={pos.profit >= 0 ? "profit-pos" : "profit-neg"}>
                          ${pos.profit.toFixed(2)}
                        </span>
                      </div>
                      <button
                        className="btn-close"
                        onClick={() => handleClosePosition(pos.ticket)}
                        disabled={loading}
                        title="Close position"
                      >
                        <X size={12} />
                      </button>
                    </div>
                  ))
                )}
              </div>
            )}

            {activeTab === "orders" && (
              <div className="orders-list">
                {orders.length === 0 ? (
                  <p style={{ textAlign: "center", color: "var(--text-muted)" }}>No pending orders</p>
                ) : (
                  orders.map((order) => (
                    <div key={order.ticket} className="order-item">
                      <span className="order-type">{order.order_type}</span>
                      <span className="symbol">{order.symbol}</span>
                      <span>{order.volume.toFixed(2)} @ ${order.price.toFixed(5)}</span>
                      <button
                        className="btn-close"
                        onClick={() => handleCancelOrder(order.ticket)}
                        disabled={loading}
                        title="Cancel order"
                      >
                        <X size={12} />
                      </button>
                    </div>
                  ))
                )}
              </div>
            )}

            {activeTab === "history" && (
              <div className="history-list">
                {deals.length === 0 ? (
                  <p style={{ textAlign: "center", color: "var(--text-muted)" }}>No deals in last 30 days</p>
                ) : (
                  deals.slice(0, 20).map((deal) => (
                    <div key={deal.ticket} className="deal-item">
                      <span className={`entry-badge ${deal.entry.toLowerCase()}`}>{deal.entry}</span>
                      <span className={`side-badge ${deal.side.toLowerCase()}`}>{deal.side}</span>
                      <span className="symbol">{deal.symbol}</span>
                      <span>{deal.volume.toFixed(2)}</span>
                      <span className={deal.profit >= 0 ? "profit-pos" : "profit-neg"}>
                        ${deal.profit.toFixed(2)}
                      </span>
                    </div>
                  ))
                )}
              </div>
            )}

            <button className="btn btn-secondary" onClick={handleDisconnect} style={{ marginTop: "auto" }}>
              Disconnect
            </button>
          </>
        )}
      </div>

      <style>{`
        .tab-row {
          display: flex;
          gap: 4px;
          margin-bottom: 8px;
        }
        .tab-btn {
          flex: 1;
          padding: 6px 8px;
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
        .account-info {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .account-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 6px 8px;
          background: var(--bg-secondary);
          border-radius: 4px;
          font-size: 12px;
        }
        .account-row.highlight {
          background: var(--accent);
          color: var(--bg-primary);
        }
        .account-row span:first-child {
          display: flex;
          align-items: center;
          gap: 6px;
          color: var(--text-muted);
        }
        .positions-list, .orders-list, .history-list {
          display: flex;
          flex-direction: column;
          gap: 6px;
          max-height: 250px;
          overflow-y: auto;
        }
        .position-item, .order-item, .deal-item {
          padding: 8px;
          background: var(--bg-secondary);
          border-radius: 4px;
          font-size: 11px;
        }
        .position-header {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 4px;
        }
        .position-details {
          display: flex;
          justify-content: space-between;
          color: var(--text-muted);
        }
        .side-badge {
          padding: 2px 6px;
          border-radius: 3px;
          font-size: 10px;
          font-weight: 600;
        }
        .side-badge.buy {
          background: var(--accent);
          color: var(--bg-primary);
        }
        .side-badge.sell {
          background: var(--danger);
          color: white;
        }
        .entry-badge {
          padding: 2px 4px;
          border-radius: 3px;
          font-size: 9px;
          margin-right: 4px;
        }
        .entry-badge.in {
          background: var(--accent);
          color: var(--bg-primary);
        }
        .entry-badge.out {
          background: var(--warning);
          color: var(--bg-primary);
        }
        .profit-pos { color: var(--accent); }
        .profit-neg { color: var(--danger); }
        .trade-panel {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .trade-form {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .trade-row {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .trade-row label {
          font-size: 11px;
          color: var(--text-muted);
        }
        .trade-input {
          padding: 6px 8px;
          background: var(--bg-secondary);
          border: 1px solid var(--border);
          border-radius: 4px;
          color: var(--text-primary);
          font-size: 12px;
        }
        .trade-buttons {
          display: flex;
          gap: 8px;
          margin-top: 8px;
        }
        .btn-buy {
          flex: 1;
          background: var(--accent);
          color: white;
          border: none;
          padding: 10px;
          border-radius: 4px;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          font-weight: 600;
        }
        .btn-buy:hover {
          opacity: 0.9;
        }
        .btn-buy:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        .btn-sell {
          flex: 1;
          background: var(--danger);
          color: white;
          border: none;
          padding: 10px;
          border-radius: 4px;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          font-weight: 600;
        }
        .btn-sell:hover {
          opacity: 0.9;
        }
        .btn-sell:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        .btn-close {
          background: transparent;
          border: none;
          color: var(--text-muted);
          cursor: pointer;
          padding: 4px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: 4px;
        }
        .btn-close:hover {
          background: var(--danger);
          color: white;
        }
        .position-item, .order-item {
          display: flex;
          flex-direction: column;
          gap: 4px;
          position: relative;
        }
        .position-item .btn-close, .order-item .btn-close {
          position: absolute;
          top: 4px;
          right: 4px;
        }
      `}</style>
    </div>
  );
}
