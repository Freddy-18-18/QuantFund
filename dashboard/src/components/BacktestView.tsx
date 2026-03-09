import { useState, useEffect, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  LineChart,
  Play,
  TrendingUp,
  TrendingDown,
  Save,
  Download,
  X,
  BarChart3,
  GitCompare,
} from "lucide-react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  BarChart,
  Bar,
  ComposedChart,
  Line,
} from "recharts";

interface BacktestResult {
  base_result: {
    total_trades: number;
    winning_trades: number;
    losing_trades: number;
    win_rate: number;
    total_pnl: string;
    total_return_pct: number;
    sharpe_ratio: number;
    sortino_ratio: number;
    max_drawdown: number;
    max_drawdown_pct: number;
    calmar_ratio: number;
    profit_factor: number;
    avg_win: string;
    avg_loss: string;
    largest_win: string;
    largest_loss: string;
  };
  equity_curve: [number, number][];
  trades: Trade[];
}

interface Trade {
  id: number;
  entry_time: string;
  exit_time: string;
  symbol: string;
  side: "BUY" | "SELL";
  entry_price: number;
  exit_price: number;
  volume: number;
  pnl: number;
  pnl_pct: number;
  duration_bars: number;
}

interface StrategyConfig {
  name: string;
  strategy_type: string;
  initial_capital: number;
  start_date: string;
  end_date: string;
  params: Record<string, number>;
  risk_params: {
    max_position_size: number;
    max_leverage: number;
    max_drawdown_pct: number;
  };
}

interface SavedConfig {
  id: string;
  name: string;
  config: StrategyConfig;
  created_at: string;
}

interface EquityPoint {
  ts: number;
  equity: number;
  drawdown: number;
}

const STRATEGY_TYPES = [
  { value: "sma_crossover", label: "SMA Crossover" },
  { value: "mean_reversion", label: "Mean Reversion" },
  { value: "momentum_rsi", label: "Momentum RSI" },
  { value: "channel_breakout", label: "Channel Breakout" },
  { value: "bollinger_bands", label: "Bollinger Bands" },
  { value: "macd_divergence", label: "MACD Divergence" },
];

const DEFAULT_PARAMS: Record<string, Record<string, { min: number; max: number; default: number }>> = {
  sma_crossover: {
    fast_period: { min: 5, max: 50, default: 10 },
    slow_period: { min: 20, max: 200, default: 50 },
  },
  mean_reversion: {
    lookback_period: { min: 10, max: 100, default: 20 },
    std_dev_multiplier: { min: 1, max: 3, default: 2 },
  },
  momentum_rsi: {
    rsi_period: { min: 5, max: 30, default: 14 },
    rsi_overbought: { min: 60, max: 90, default: 70 },
    rsi_oversold: { min: 10, max: 40, default: 30 },
  },
  channel_breakout: {
    channel_period: { min: 10, max: 50, default: 20 },
    atr_multiplier: { min: 1, max: 5, default: 2 },
  },
  bollinger_bands: {
    period: { min: 10, max: 50, default: 20 },
    std_dev: { min: 1, max: 3, default: 2 },
  },
  macd_divergence: {
    fast_period: { min: 5, max: 20, default: 12 },
    slow_period: { min: 15, max: 40, default: 26 },
    signal_period: { min: 5, max: 15, default: 9 },
  },
};

export function BacktestView() {
  const [activeTab, setActiveTab] = useState<"config" | "results" | "compare">("config");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  
  const [config, setConfig] = useState<StrategyConfig>({
    name: "My Strategy",
    strategy_type: "sma_crossover",
    initial_capital: 100000,
    start_date: "2024-01-01",
    end_date: "2024-12-31",
    params: {
      fast_period: 10,
      slow_period: 50,
    },
    risk_params: {
      max_position_size: 10,
      max_leverage: 2,
      max_drawdown_pct: 20,
    },
  });

  const [savedConfigs, setSavedConfigs] = useState<SavedConfig[]>([]);
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [configName, setConfigName] = useState("");
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});

  const [tradeFilter, setTradeFilter] = useState<"all" | "winners" | "losers">("all");

  const [compareStrategies, setCompareStrategies] = useState<BacktestResult[]>([]);
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>([]);

  useEffect(() => {
    const saved = localStorage.getItem("backtest_configs");
    if (saved) {
      setSavedConfigs(JSON.parse(saved));
    }
  }, []);

  const validateConfig = useCallback((): boolean => {
    const errors: Record<string, string> = {};
    
    if (config.initial_capital < 1000) {
      errors.initial_capital = "Minimum capital is $1,000";
    }
    if (new Date(config.start_date) >= new Date(config.end_date)) {
      errors.dates = "End date must be after start date";
    }
    if (config.params) {
      const params = DEFAULT_PARAMS[config.strategy_type];
      if (params) {
        Object.entries(config.params).forEach(([key, value]) => {
          const paramDef = params[key];
          if (paramDef && (value < paramDef.min || value > paramDef.max)) {
            errors[key] = `${key} must be between ${paramDef.min} and ${paramDef.max}`;
          }
        });
      }
    }
    
    setValidationErrors(errors);
    return Object.keys(errors).length === 0;
  }, [config]);

  const runBacktest = async () => {
    if (!validateConfig()) return;
    
    setRunning(true);
    setError(null);
    setResult(null);
    
    try {
      const backtestResult = await invoke<BacktestResult>("start_xauusd_backtest", {
        config: {
          strategy_type: config.strategy_type,
          strategy_params: config.params,
          initial_capital: config.initial_capital,
          start_date: config.start_date,
          end_date: config.end_date,
          risk_params: config.risk_params,
        },
      });
      
      setResult(backtestResult);
      setActiveTab("results");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  };

  const saveConfig = () => {
    if (!configName.trim()) return;
    
    const newConfig: SavedConfig = {
      id: Date.now().toString(),
      name: configName,
      config: { ...config },
      created_at: new Date().toISOString(),
    };
    
    const updated = [...savedConfigs, newConfig];
    setSavedConfigs(updated);
    localStorage.setItem("backtest_configs", JSON.stringify(updated));
    setShowSaveModal(false);
    setConfigName("");
  };

  const loadConfig = (saved: SavedConfig) => {
    setConfig({ ...saved.config, name: saved.name });
  };

  const deleteConfig = (id: string) => {
    const updated = savedConfigs.filter((c) => c.id !== id);
    setSavedConfigs(updated);
    localStorage.setItem("backtest_configs", JSON.stringify(updated));
  };

  const addToCompare = () => {
    if (result && compareStrategies.length < 3) {
      setCompareStrategies([...compareStrategies, result]);
      setSelectedStrategies([...selectedStrategies, config.name || config.strategy_type]);
    }
  };

  const removeFromCompare = (index: number) => {
    const updated = compareStrategies.filter((_, i) => i !== index);
    const namesUpdated = selectedStrategies.filter((_, i) => i !== index);
    setCompareStrategies(updated);
    setSelectedStrategies(namesUpdated);
  };

  const prepareEquityData = (): EquityPoint[] => {
    if (!result?.equity_curve) return [];
    
    let peak = result.equity_curve[0]?.[1] || config.initial_capital;
    return result.equity_curve.map(([ts, equity]) => {
      if (equity > peak) peak = equity;
      const drawdown = ((peak - equity) / peak) * 100;
      return { ts, equity, drawdown };
    });
  };

  const prepareDrawdownData = (): EquityPoint[] => {
    if (!result?.equity_curve) return [];
    
    let peak = result.equity_curve[0]?.[1] || config.initial_capital;
    return result.equity_curve.map(([ts, equity]) => {
      if (equity > peak) peak = equity;
      const drawdown = ((peak - equity) / peak) * 100;
      return { ts, equity: -drawdown, drawdown };
    });
  };

  const prepareTradeDistribution = () => {
    if (!result?.trades) return [];
    
    const wins = result.trades.filter((t) => t.pnl > 0).map((t) => t.pnl);
    const losses = result.trades.filter((t) => t.pnl < 0).map((t) => Math.abs(t.pnl));
    
    return [
      { name: "Wins", value: wins.length, avg: wins.length > 0 ? wins.reduce((a, b) => a + b, 0) / wins.length : 0 },
      { name: "Losses", value: losses.length, avg: losses.length > 0 ? losses.reduce((a, b) => a + b, 0) / losses.length : 0 },
    ];
  };

  const filteredTrades = result?.trades?.filter((trade) => {
    if (tradeFilter === "winners") return trade.pnl > 0;
    if (tradeFilter === "losers") return trade.pnl < 0;
    return true;
  }) || [];

  const formatCurrency = (value: string | number) => {
    const num = typeof value === "string" ? parseFloat(value) : value;
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(num);
  };

  const formatPercent = (value: number) => `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;

  const renderMetric = (label: string, value: string | number, highlight?: "good" | "bad" | "neutral") => (
    <div className="metric-item">
      <span className="metric-label">{label}</span>
      <span className={`metric-value ${highlight || ""}`}>{value}</span>
    </div>
  );

  const getAvailableParams = () => DEFAULT_PARAMS[config.strategy_type] || {};

  return (
    <div className="backtest-view">
      <div className="view-header">
        <h2><LineChart size={24} style={{ marginRight: "0.5rem", verticalAlign: "middle" }} />Backtest</h2>
        <p>Configura, ejecuta y compara estrategias de trading</p>
      </div>

      <div className="backtest-tabs">
        <button className={`tab ${activeTab === "config" ? "active" : ""}`} onClick={() => setActiveTab("config")}>
          <Save size={14} /> Configuración
        </button>
        <button className={`tab ${activeTab === "results" ? "active" : ""}`} onClick={() => setActiveTab("results")} disabled={!result}>
          <BarChart3 size={14} /> Resultados
        </button>
        <button className={`tab ${activeTab === "compare" ? "active" : ""}`} onClick={() => setActiveTab("compare")}>
          <GitCompare size={14} /> Comparar
        </button>
      </div>

      {activeTab === "config" && (
        <div className="config-panel">
          <div className="config-grid">
            <div className="card">
              <div className="card-header">
                <span>Parámetros de Estrategia</span>
              </div>
              <div className="card-body">
                <div className="form-group">
                  <label>Nombre de Configuración</label>
                  <input
                    type="text"
                    value={config.name}
                    onChange={(e) => setConfig({ ...config, name: e.target.value })}
                    placeholder="Mi estrategia"
                  />
                </div>
                
                <div className="form-group">
                  <label>Tipo de Estrategia</label>
                  <select
                    value={config.strategy_type}
                    onChange={(e) => {
                      const newType = e.target.value;
                      const defaultP = DEFAULT_PARAMS[newType];
                      setConfig({
                        ...config,
                        strategy_type: newType,
                        params: defaultP ? Object.fromEntries(
                          Object.entries(defaultP).map(([k, v]) => [k, v.default])
                        ) : {},
                      });
                    }}
                  >
                    {STRATEGY_TYPES.map((s) => (
                      <option key={s.value} value={s.value}>{s.label}</option>
                    ))}
                  </select>
                </div>

                {Object.entries(getAvailableParams()).map(([key, param]) => (
                  <div className="form-group" key={key}>
                    <label>{key.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase())}</label>
                    <div className="param-input-group">
                      <input
                        type="number"
                        value={config.params[key] || param.default}
                        onChange={(e) => setConfig({
                          ...config,
                          params: { ...config.params, [key]: parseFloat(e.target.value) },
                        })}
                        min={param.min}
                        max={param.max}
                      />
                      <span className="param-range">({param.min}-{param.max})</span>
                    </div>
                    {validationErrors[key] && <span className="error-text">{validationErrors[key]}</span>}
                  </div>
                ))}
              </div>
            </div>

            <div className="card">
              <div className="card-header">
                <span>Parámetros de Backtest</span>
              </div>
              <div className="card-body">
                <div className="form-row">
                  <div className="form-group">
                    <label>Capital Inicial</label>
                    <input
                      type="number"
                      value={config.initial_capital}
                      onChange={(e) => setConfig({ ...config, initial_capital: parseFloat(e.target.value) })}
                    />
                    {validationErrors.initial_capital && <span className="error-text">{validationErrors.initial_capital}</span>}
                  </div>
                  <div className="form-group">
                    <label>Apalancamiento Max</label>
                    <input
                      type="number"
                      value={config.risk_params.max_leverage}
                      onChange={(e) => setConfig({
                        ...config,
                        risk_params: { ...config.risk_params, max_leverage: parseFloat(e.target.value) },
                      })}
                      min={1}
                      max={100}
                    />
                  </div>
                </div>

                <div className="form-row">
                  <div className="form-group">
                    <label>Fecha Inicio</label>
                    <input
                      type="date"
                      value={config.start_date}
                      onChange={(e) => setConfig({ ...config, start_date: e.target.value })}
                    />
                  </div>
                  <div className="form-group">
                    <label>Fecha Fin</label>
                    <input
                      type="date"
                      value={config.end_date}
                      onChange={(e) => setConfig({ ...config, end_date: e.target.value })}
                    />
                  </div>
                </div>
                {validationErrors.dates && <span className="error-text">{validationErrors.dates}</span>}

                <div className="form-group">
                  <label>Max Drawdown (%)</label>
                  <input
                    type="number"
                    value={config.risk_params.max_drawdown_pct}
                    onChange={(e) => setConfig({
                      ...config,
                      risk_params: { ...config.risk_params, max_drawdown_pct: parseFloat(e.target.value) },
                    })}
                    min={1}
                    max={100}
                  />
                </div>
              </div>
            </div>

            <div className="card">
              <div className="card-header">
                <span>Configuraciones Guardadas</span>
                <button className="btn-icon" onClick={() => setShowSaveModal(true)}>
                  <Save size={14} />
                </button>
              </div>
              <div className="card-body">
                {savedConfigs.length === 0 ? (
                  <p className="empty-text">No hay configuraciones guardadas</p>
                ) : (
                  <div className="saved-list">
                    {savedConfigs.map((saved) => (
                      <div key={saved.id} className="saved-item">
                        <span className="saved-name">{saved.name}</span>
                        <div className="saved-actions">
                          <button className="btn-icon-sm" onClick={() => loadConfig(saved)}>
                            <Download size={12} />
                          </button>
                          <button className="btn-icon-sm danger" onClick={() => deleteConfig(saved.id)}>
                            <X size={12} />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="action-bar">
            {error && <div className="error-message">{error}</div>}
            <button className="btn-run" onClick={runBacktest} disabled={running}>
              <Play size={18} /> {running ? "Ejecutando..." : "Ejecutar Backtest"}
            </button>
          </div>
        </div>
      )}

      {activeTab === "results" && result && (
        <div className="results-panel">
          <div className="results-grid">
            <div className="card metrics-card">
              <div className="card-header">
                <span>Métricas de Rendimiento</span>
              </div>
              <div className="card-body">
                <div className="metrics-grid">
                  {renderMetric("Total Trades", result.base_result.total_trades)}
                  {renderMetric("Win Rate", `${result.base_result.win_rate.toFixed(1)}%`, result.base_result.win_rate > 50 ? "good" : "bad")}
                  {renderMetric("Profit Factor", result.base_result.profit_factor.toFixed(2), result.base_result.profit_factor > 1.5 ? "good" : "bad")}
                  {renderMetric("Total P&L", formatCurrency(result.base_result.total_pnl), result.base_result.total_return_pct >= 0 ? "good" : "bad")}
                  {renderMetric("Return %", formatPercent(result.base_result.total_return_pct), result.base_result.total_return_pct >= 0 ? "good" : "bad")}
                  {renderMetric("Sharpe Ratio", result.base_result.sharpe_ratio.toFixed(2), result.base_result.sharpe_ratio > 1 ? "good" : result.base_result.sharpe_ratio > 0 ? "neutral" : "bad")}
                  {renderMetric("Sortino Ratio", result.base_result.sortino_ratio.toFixed(2), result.base_result.sortino_ratio > 1 ? "good" : "neutral")}
                  {renderMetric("Calmar Ratio", result.base_result.calmar_ratio.toFixed(2), result.base_result.calmar_ratio > 1 ? "good" : "neutral")}
                  {renderMetric("Max Drawdown", `${result.base_result.max_drawdown_pct.toFixed(2)}%`, "bad")}
                  {renderMetric("Avg Win", formatCurrency(result.base_result.avg_win))}
                  {renderMetric("Avg Loss", formatCurrency(result.base_result.avg_loss))}
                  {renderMetric("Largest Win", formatCurrency(result.base_result.largest_win))}
                  {renderMetric("Largest Loss", formatCurrency(result.base_result.largest_loss))}
                </div>
              </div>
            </div>

            <div className="card">
              <div className="card-header">
                <span>Equity Curve</span>
              </div>
              <div className="card-body chart-container">
                <ResponsiveContainer width="100%" height={250}>
                  <AreaChart data={prepareEquityData()} margin={{ top: 10, right: 10, bottom: 0, left: 0 }}>
                    <defs>
                      <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={result.base_result.total_return_pct >= 0 ? "#00e676" : "#ff5252"} stopOpacity={0.3} />
                        <stop offset="95%" stopColor={result.base_result.total_return_pct >= 0 ? "#00e676" : "#ff5252"} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#252535" />
                    <XAxis dataKey="ts" tick={{ fill: "#7070a0", fontSize: 10 }} minTickGap={60} axisLine={false} tickLine={false} tickFormatter={(v) => new Date(v).toLocaleDateString()} />
                    <YAxis tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} tick={{ fill: "#7070a0", fontSize: 10 }} axisLine={false} tickLine={false} width={55} />
                    <Tooltip contentStyle={{ background: "#161620", border: "1px solid #252535", fontFamily: "var(--font-mono)", fontSize: 11 }} formatter={(v: number) => [`$${v.toFixed(2)}`, "Equity"]} labelFormatter={(ts) => new Date(ts as number).toLocaleDateString()} />
                    <ReferenceLine y={config.initial_capital} stroke="#7070a0" strokeDasharray="4 4" />
                    <Area type="monotone" dataKey="equity" stroke={result.base_result.total_return_pct >= 0 ? "#00e676" : "#ff5252"} strokeWidth={1.5} fill="url(#equityGrad)" dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="card">
              <div className="card-header">
                <span>Drawdown</span>
              </div>
              <div className="card-body chart-container">
                <ResponsiveContainer width="100%" height={200}>
                  <AreaChart data={prepareDrawdownData()} margin={{ top: 10, right: 10, bottom: 0, left: 0 }}>
                    <defs>
                      <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#ff5252" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#ff5252" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#252535" />
                    <XAxis dataKey="ts" tick={{ fill: "#7070a0", fontSize: 10 }} minTickGap={60} axisLine={false} tickLine={false} tickFormatter={(v) => new Date(v).toLocaleDateString()} />
                    <YAxis tickFormatter={(v) => `${v.toFixed(0)}%`} tick={{ fill: "#7070a0", fontSize: 10 }} axisLine={false} tickLine={false} width={45} domain={['dataMin - 5', 0]} />
                    <Tooltip contentStyle={{ background: "#161620", border: "1px solid #252535", fontFamily: "var(--font-mono)", fontSize: 11 }} formatter={(v: number) => [`${v.toFixed(2)}%`, "Drawdown"]} />
                    <Area type="monotone" dataKey="equity" stroke="#ff5252" strokeWidth={1.5} fill="url(#ddGrad)" dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="card">
              <div className="card-header">
                <span>Distribución Wins/Losses</span>
              </div>
              <div className="card-body chart-container">
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={prepareTradeDistribution()} layout="vertical" margin={{ top: 10, right: 10, bottom: 0, left: 50 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#252535" />
                    <XAxis type="number" tick={{ fill: "#7070a0", fontSize: 10 }} axisLine={false} tickLine={false} />
                    <YAxis type="category" dataKey="name" tick={{ fill: "#7070a0", fontSize: 11 }} axisLine={false} tickLine={false} width={60} />
                    <Tooltip contentStyle={{ background: "#161620", border: "1px solid #252535", fontFamily: "var(--font-mono)", fontSize: 11 }} />
                    <Bar dataKey="value" fill="#00e676" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="card trades-card">
              <div className="card-header">
                <span>Lista de Trades</span>
                <div className="trade-filters">
                  <button className={`filter-btn ${tradeFilter === "all" ? "active" : ""}`} onClick={() => setTradeFilter("all")}>Todos</button>
                  <button className={`filter-btn ${tradeFilter === "winners" ? "active" : ""}`} onClick={() => setTradeFilter("winners")}>
                    <TrendingUp size={12} /> Winners
                  </button>
                  <button className={`filter-btn ${tradeFilter === "losers" ? "active" : ""}`} onClick={() => setTradeFilter("losers")}>
                    <TrendingDown size={12} /> Losers
                  </button>
                </div>
              </div>
              <div className="card-body">
                <div className="trades-table-container">
                  <table className="trades-table">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Symbol</th>
                        <th>Side</th>
                        <th>Entry</th>
                        <th>Exit</th>
                        <th>Volume</th>
                        <th>P&L</th>
                        <th>%</th>
                        <th>Bars</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredTrades.slice(0, 50).map((trade, idx) => (
                        <tr key={trade.id || idx} className={trade.pnl >= 0 ? "win" : "loss"}>
                          <td>{idx + 1}</td>
                          <td>{trade.symbol}</td>
                          <td><span className={`side-badge ${trade.side.toLowerCase()}`}>{trade.side}</span></td>
                          <td>{trade.entry_price.toFixed(2)}</td>
                          <td>{trade.exit_price.toFixed(2)}</td>
                          <td>{trade.volume}</td>
                          <td className={trade.pnl >= 0 ? "positive" : "negative"}>{formatCurrency(trade.pnl)}</td>
                          <td className={trade.pnl_pct >= 0 ? "positive" : "negative"}>{formatPercent(trade.pnl_pct)}</td>
                          <td>{trade.duration_bars}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {filteredTrades.length > 50 && (
                    <div className="table-note">Mostrando 50 de {filteredTrades.length} trades</div>
                  )}
                </div>
              </div>
            </div>

            <div className="card">
              <div className="card-header">
                <span>Agregar a Comparación</span>
              </div>
              <div className="card-body">
                <p className="desc-text">Compara esta estrategia con otras para ver diferencias de rendimiento.</p>
                <button className="btn-secondary" onClick={addToCompare} disabled={compareStrategies.length >= 3}>
                  <GitCompare size={14} /> Agregar a Comparar ({compareStrategies.length}/3)
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {activeTab === "compare" && (
        <div className="compare-panel">
          <div className="card">
            <div className="card-header">
              <span>Comparación de Estrategias</span>
            </div>
            <div className="card-body">
              {compareStrategies.length === 0 ? (
                <p className="empty-text">Ejecuta un backtest y agrégalo a la comparación</p>
              ) : (
                <div className="compare-table-container">
                  <table className="compare-table">
                    <thead>
                      <tr>
                        <th>Métrica</th>
                        {selectedStrategies.map((name, idx) => (
                          <th key={idx}>
                            {name}
                            <button className="btn-icon-xs" onClick={() => removeFromCompare(idx)}>
                              <X size={10} />
                            </button>
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td>Total Trades</td>
                        {compareStrategies.map((r, i) => <td key={i}>{r.base_result.total_trades}</td>)}
                      </tr>
                      <tr>
                        <td>Win Rate</td>
                        {compareStrategies.map((r, i) => <td key={i} className={r.base_result.win_rate > 50 ? "good" : ""}>{r.base_result.win_rate.toFixed(1)}%</td>)}
                      </tr>
                      <tr>
                        <td>Total Return</td>
                        {compareStrategies.map((r, i) => <td key={i} className={r.base_result.total_return_pct >= 0 ? "good" : "bad"}>{formatPercent(r.base_result.total_return_pct)}</td>)}
                      </tr>
                      <tr>
                        <td>Sharpe Ratio</td>
                        {compareStrategies.map((r, i) => <td key={i} className={r.base_result.sharpe_ratio > 1 ? "good" : r.base_result.sharpe_ratio > 0 ? "neutral" : ""}>{r.base_result.sharpe_ratio.toFixed(2)}</td>)}
                      </tr>
                      <tr>
                        <td>Sortino Ratio</td>
                        {compareStrategies.map((r, i) => <td key={i}>{r.base_result.sortino_ratio.toFixed(2)}</td>)}
                      </tr>
                      <tr>
                        <td>Calmar Ratio</td>
                        {compareStrategies.map((r, i) => <td key={i}>{r.base_result.calmar_ratio.toFixed(2)}</td>)}
                      </tr>
                      <tr>
                        <td>Max Drawdown</td>
                        {compareStrategies.map((r, i) => <td key={i} className="bad">{r.base_result.max_drawdown_pct.toFixed(2)}%</td>)}
                      </tr>
                      <tr>
                        <td>Profit Factor</td>
                        {compareStrategies.map((r, i) => <td key={i} className={r.base_result.profit_factor > 1.5 ? "good" : ""}>{r.base_result.profit_factor.toFixed(2)}</td>)}
                      </tr>
                      <tr>
                        <td>Avg Win</td>
                        {compareStrategies.map((r, i) => <td key={i}>{formatCurrency(r.base_result.avg_win)}</td>)}
                      </tr>
                      <tr>
                        <td>Avg Loss</td>
                        {compareStrategies.map((r, i) => <td key={i}>{formatCurrency(r.base_result.avg_loss)}</td>)}
                      </tr>
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>

          {compareStrategies.length > 1 && (
            <div className="card">
              <div className="card-header">
                <span>Equity Curves Comparadas</span>
              </div>
              <div className="card-body chart-container">
                <ResponsiveContainer width="100%" height={300}>
                  <ComposedChart margin={{ top: 10, right: 10, bottom: 0, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#252535" />
                    <XAxis dataKey="ts" tick={{ fill: "#7070a0", fontSize: 10 }} minTickGap={60} axisLine={false} tickLine={false} tickFormatter={(v) => new Date(v).toLocaleDateString()} />
                    <YAxis tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} tick={{ fill: "#7070a0", fontSize: 10 }} axisLine={false} tickLine={false} width={55} />
                    <Tooltip contentStyle={{ background: "#161620", border: "1px solid #252535", fontFamily: "var(--font-mono)", fontSize: 11 }} formatter={(v: number) => [`$${v.toFixed(2)}`, "Equity"]} />
                    {compareStrategies.map((r, idx) => (
                      <Line key={idx} type="monotone" data={r.equity_curve.map(([ts, eq]) => ({ ts, eq }))} dataKey="eq" stroke={["#00e676", "#2196f3", "#ff9800"][idx]} strokeWidth={1.5} dot={false} name={selectedStrategies[idx]} />
                    ))}
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </div>
      )}

      {showSaveModal && (
        <div className="modal-overlay" onClick={() => setShowSaveModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <span>Guardar Configuración</span>
              <button className="btn-icon" onClick={() => setShowSaveModal(false)}>
                <X size={16} />
              </button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <label>Nombre de la configuración</label>
                <input
                  type="text"
                  value={configName}
                  onChange={(e) => setConfigName(e.target.value)}
                  placeholder="Mi estrategia..."
                  autoFocus
                />
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setShowSaveModal(false)}>Cancelar</button>
              <button className="btn-primary" onClick={saveConfig} disabled={!configName.trim()}>
                <Save size={14} /> Guardar
              </button>
            </div>
          </div>
        </div>
      )}

      <style>{`
        .backtest-tabs {
          display: flex;
          gap: 4px;
          margin-bottom: 1rem;
          background: var(--bg-secondary);
          padding: 4px;
          border-radius: 8px;
        }
        .backtest-tabs .tab {
          flex: 1;
          padding: 10px 16px;
          background: transparent;
          border: none;
          border-radius: 6px;
          color: var(--text-muted);
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          font-size: 13px;
          transition: all 0.2s;
        }
        .backtest-tabs .tab:hover:not(:disabled) {
          background: var(--bg-tertiary);
        }
        .backtest-tabs .tab.active {
          background: var(--accent);
          color: var(--bg-primary);
        }
        .backtest-tabs .tab:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        .config-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
          gap: 1rem;
        }
        .form-group {
          margin-bottom: 1rem;
        }
        .form-group label {
          display: block;
          font-size: 0.75rem;
          color: var(--text-secondary);
          margin-bottom: 0.5rem;
        }
        .form-group input, .form-group select {
          width: 100%;
          padding: 0.625rem;
          background: var(--bg-tertiary);
          border: 1px solid var(--border-color);
          border-radius: 0.5rem;
          color: var(--text-primary);
          font-size: 0.875rem;
        }
        .form-group input:focus, .form-group select:focus {
          outline: none;
          border-color: var(--accent);
        }
        .form-row {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 1rem;
        }
        .param-input-group {
          display: flex;
          align-items: center;
          gap: 0.5rem;
        }
        .param-input-group input {
          width: 80px;
        }
        .param-range {
          font-size: 0.7rem;
          color: var(--text-muted);
        }
        .error-text {
          color: var(--danger);
          font-size: 0.7rem;
          margin-top: 0.25rem;
        }
        .saved-list {
          display: flex;
          flex-direction: column;
          gap: 0.5rem;
        }
        .saved-item {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 0.5rem;
          background: var(--bg-tertiary);
          border-radius: 0.5rem;
        }
        .saved-name {
          font-size: 0.875rem;
        }
        .saved-actions {
          display: flex;
          gap: 0.25rem;
        }
        .btn-icon {
          background: transparent;
          border: none;
          color: var(--text-muted);
          cursor: pointer;
          padding: 4px;
          border-radius: 4px;
        }
        .btn-icon:hover {
          background: var(--bg-tertiary);
          color: var(--text-primary);
        }
        .btn-icon-sm {
          background: transparent;
          border: none;
          color: var(--text-muted);
          cursor: pointer;
          padding: 4px 6px;
          border-radius: 4px;
        }
        .btn-icon-sm:hover {
          background: var(--bg-secondary);
        }
        .btn-icon-sm.danger:hover {
          color: var(--danger);
        }
        .btn-icon-xs {
          background: transparent;
          border: none;
          color: var(--text-muted);
          cursor: pointer;
          padding: 2px 4px;
          margin-left: 4px;
        }
        .action-bar {
          margin-top: 1rem;
          display: flex;
          align-items: center;
          gap: 1rem;
        }
        .btn-run {
          padding: 0.75rem 1.5rem;
          background: var(--accent-blue);
          border: none;
          border-radius: 0.5rem;
          color: white;
          cursor: pointer;
          display: flex;
          align-items: center;
          gap: 0.5rem;
          font-size: 0.875rem;
        }
        .btn-run:hover:not(:disabled) {
          opacity: 0.9;
        }
        .btn-run:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }
        .btn-secondary {
          padding: 0.5rem 1rem;
          background: var(--bg-tertiary);
          border: 1px solid var(--border-color);
          border-radius: 0.5rem;
          color: var(--text-primary);
          cursor: pointer;
          display: flex;
          align-items: center;
          gap: 0.5rem;
          font-size: 0.8rem;
        }
        .btn-primary {
          padding: 0.5rem 1rem;
          background: var(--accent);
          border: none;
          border-radius: 0.5rem;
          color: var(--bg-primary);
          cursor: pointer;
          display: flex;
          align-items: center;
          gap: 0.5rem;
          font-size: 0.8rem;
        }
        .btn-primary:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        .error-message {
          color: var(--danger);
          font-size: 0.875rem;
          flex: 1;
        }
        .empty-text {
          color: var(--text-muted);
          font-size: 0.875rem;
          text-align: center;
          padding: 1rem;
        }
        .desc-text {
          color: var(--text-muted);
          font-size: 0.8rem;
          margin-bottom: 0.75rem;
        }
        .results-grid {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 1rem;
        }
        .metrics-card {
          grid-column: span 2;
        }
        .trades-card {
          grid-column: span 2;
        }
        .metrics-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: 1rem;
        }
        .metric-item {
          display: flex;
          flex-direction: column;
          padding: 0.75rem;
          background: var(--bg-tertiary);
          border-radius: 0.5rem;
        }
        .metric-label {
          font-size: 0.7rem;
          color: var(--text-muted);
          margin-bottom: 0.25rem;
        }
        .metric-value {
          font-size: 1.1rem;
          font-weight: 600;
          font-family: var(--font-mono);
        }
        .metric-value.good { color: var(--accent); }
        .metric-value.bad { color: var(--danger); }
        .metric-value.neutral { color: var(--warning); }
        .chart-container {
          padding: 0.5rem;
        }
        .trade-filters {
          display: flex;
          gap: 0.5rem;
        }
        .filter-btn {
          padding: 4px 8px;
          background: transparent;
          border: 1px solid var(--border-color);
          border-radius: 4px;
          color: var(--text-muted);
          cursor: pointer;
          font-size: 0.7rem;
          display: flex;
          align-items: center;
          gap: 4px;
        }
        .filter-btn.active {
          background: var(--accent);
          border-color: var(--accent);
          color: var(--bg-primary);
        }
        .trades-table-container {
          overflow-x: auto;
          max-height: 400px;
          overflow-y: auto;
        }
        .trades-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 0.75rem;
        }
        .trades-table th, .trades-table td {
          padding: 0.5rem;
          text-align: left;
          border-bottom: 1px solid var(--border-color);
        }
        .trades-table th {
          color: var(--text-muted);
          font-weight: 500;
          position: sticky;
          top: 0;
          background: var(--bg-secondary);
        }
        .trades-table .positive { color: var(--accent); }
        .trades-table .negative { color: var(--danger); }
        .side-badge {
          padding: 2px 6px;
          border-radius: 3px;
          font-size: 0.65rem;
          font-weight: 600;
        }
        .side-badge.buy { background: rgba(0, 230, 118, 0.2); color: var(--accent); }
        .side-badge.sell { background: rgba(255, 82, 82, 0.2); color: var(--danger); }
        .table-note {
          text-align: center;
          color: var(--text-muted);
          font-size: 0.7rem;
          padding: 0.5rem;
        }
        .compare-table-container {
          overflow-x: auto;
        }
        .compare-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 0.875rem;
        }
        .compare-table th, .compare-table td {
          padding: 0.75rem;
          text-align: center;
          border-bottom: 1px solid var(--border-color);
        }
        .compare-table th {
          color: var(--text-primary);
          font-weight: 600;
        }
        .compare-table td:first-child {
          text-align: left;
          color: var(--text-muted);
        }
        .compare-table .good { color: var(--accent); }
        .compare-table .bad { color: var(--danger); }
        .compare-table .neutral { color: var(--warning); }
        .modal-overlay {
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.7);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
        }
        .modal {
          background: var(--bg-secondary);
          border-radius: 0.75rem;
          width: 90%;
          max-width: 400px;
          border: 1px solid var(--border-color);
        }
        .modal-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 1rem;
          border-bottom: 1px solid var(--border-color);
        }
        .modal-header span {
          font-weight: 600;
        }
        .modal-body {
          padding: 1rem;
        }
        .modal-footer {
          display: flex;
          justify-content: flex-end;
          gap: 0.5rem;
          padding: 1rem;
          border-top: 1px solid var(--border-color);
        }
        @media (max-width: 768px) {
          .results-grid {
            grid-template-columns: 1fr;
          }
          .metrics-card, .trades-card {
            grid-column: span 1;
          }
          .config-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  );
}

export default BacktestView;
