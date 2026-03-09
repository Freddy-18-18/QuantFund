import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Play, Settings, TrendingUp, BarChart2, GitBranch, Shuffle } from "lucide-react";

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
  xauusd_metrics: {
    avg_holding_period_bars: number;
    avg_price_move_pips: number;
    best_trade_hour: number | null;
    worst_trade_hour: number | null;
    volatility_adjusted_return: number;
  };
  equity_curve: [number, number][];
}

interface OptimizationConfig {
  strategy_type: string;
  parameters: string[];
  ranges: { min: number; max: number; step: number }[];
}

interface WalkForwardConfig {
  train_pct: number;
  test_pct: number;
  folds: number;
}

interface MonteCarloConfig {
  simulations: number;
  resample_trades: boolean;
}

interface OptimizationResult {
  params: Record<string, number>;
  metrics: {
    sharpe: number;
    return_pct: number;
    max_dd: number;
    win_rate: number;
    profit_factor: number;
  };
}

interface WalkForwardResult {
  fold: number;
  train_period: { start: string; end: string };
  test_period: { start: string; end: string };
  train_metrics: any;
  test_metrics: any;
}

interface MonteCarloResult {
  final_equity_mean: number;
  final_equity_p5: number;
  final_equity_p95: number;
  max_drawdown_mean: number;
  max_drawdown_p5: number;
  max_drawdown_p95: number;
  win_rate_mean: number;
  simulations: [number, number][][];
}

interface Props {
  strategyType: string;
  defaultParams: Record<string, number>;
  onRunOptimization: (results: OptimizationResult[]) => void;
}

export function BacktestAdvanced({ strategyType, defaultParams, onRunOptimization }: Props) {
  const [activeMode, setActiveMode] = useState<"optimize" | "walkforward" | "montecarlo" | "compare">("optimize");
  
  // Optimization state
  const [optConfig, setOptConfig] = useState<OptimizationConfig>({
    strategy_type: strategyType,
    parameters: Object.keys(defaultParams).slice(0, 2),
    ranges: Object.keys(defaultParams).map((_k) => ({ min: 5, max: 50, step: 5 })),
  });
  const [optRunning, setOptRunning] = useState(false);
  const [optResults, setOptResults] = useState<OptimizationResult[]>([]);
  
  // Walk-forward state
  const [wfConfig, setWfConfig] = useState<WalkForwardConfig>({
    train_pct: 70,
    test_pct: 30,
    folds: 3,
  });
  const [wfRunning, setWfRunning] = useState(false);
  const [wfResults, setWfResults] = useState<WalkForwardResult[]>([]);
  
  // Monte Carlo state
  const [mcConfig, setMcConfig] = useState<MonteCarloConfig>({
    simulations: 100,
    resample_trades: true,
  });
  const [mcRunning, setMcRunning] = useState(false);
  const [mcResults, setMcResults] = useState<MonteCarloResult | null>(null);

  const runOptimization = async () => {
    setOptRunning(true);
    setOptResults([]);
    
    try {
      const combinations = generateParamCombinations(optConfig.parameters, optConfig.ranges);
      const results: OptimizationResult[] = [];
      
      for (const combo of combinations.slice(0, 20)) {
        try {
          const result = await invoke<BacktestResult>("start_xauusd_backtest", {
            config: {
              strategy_type: optConfig.strategy_type,
              strategy_params: combo,
              initial_capital: 100000,
              start_date: "2024-01-01",
              end_date: "2024-12-31",
              risk_params: { max_position_size: 10, max_leverage: 2, max_drawdown_pct: 0.2 },
            }
          });
          
          results.push({
            params: combo,
            metrics: {
              sharpe: result.base_result.sharpe_ratio,
              return_pct: result.base_result.total_return_pct,
              max_dd: result.base_result.max_drawdown_pct,
              win_rate: result.base_result.win_rate,
              profit_factor: result.base_result.profit_factor,
            },
          });
        } catch (e) {
          console.error("Backtest error:", e);
        }
      }
      
      results.sort((a, b) => b.metrics.sharpe - a.metrics.sharpe);
      setOptResults(results);
      onRunOptimization(results);
    } catch (err) {
      console.error("Optimization failed:", err);
    } finally {
      setOptRunning(false);
    }
  };

  const runWalkForward = async () => {
    setWfRunning(true);
    setWfResults([]);
    
    try {
      const results: WalkForwardResult[] = [];
      const years = [2022, 2023, 2024];
      const foldSize = Math.floor(years.length / wfConfig.folds);
      
      for (let fold = 0; fold < wfConfig.folds; fold++) {
        const trainYears = years.slice(0, (fold + 1) * foldSize).slice(-wfConfig.folds);
        const testYear = years[(fold + 1) * foldSize];
        
        if (!testYear || trainYears.length === 0) continue;
        
        const trainStart = `${Math.min(...trainYears)}-01-01`;
        const trainEnd = `${Math.max(...trainYears)}-12-31`;
        const testStart = `${testYear}-01-01`;
        const testEnd = `${testYear}-12-31`;
        
        try {
          const trainResult = await invoke<BacktestResult>("start_xauusd_backtest", {
            config: {
              strategy_type: strategyType,
              strategy_params: defaultParams,
              initial_capital: 100000,
              start_date: trainStart,
              end_date: trainEnd,
              risk_params: { max_position_size: 10, max_leverage: 2, max_drawdown_pct: 0.2 },
            }
          });
          
          const testResult = await invoke<BacktestResult>("start_xauusd_backtest", {
            config: {
              strategy_type: strategyType,
              strategy_params: defaultParams,
              initial_capital: 100000,
              start_date: testStart,
              end_date: testEnd,
              risk_params: { max_position_size: 10, max_leverage: 2, max_drawdown_pct: 0.2 },
            }
          });
          
          results.push({
            fold: fold + 1,
            train_period: { start: trainStart, end: trainEnd },
            test_period: { start: testStart, end: testEnd },
            train_metrics: trainResult.base_result,
            test_metrics: testResult.base_result,
          });
        } catch (e) {
          console.error("Walk-forward error:", e);
        }
      }
      
      setWfResults(results);
    } catch (err) {
      console.error("Walk-forward failed:", err);
    } finally {
      setWfRunning(false);
    }
  };

  const runMonteCarlo = async () => {
    setMcRunning(true);
    setMcResults(null);
    
    try {
      const baseResult = await invoke<BacktestResult>("start_xauusd_backtest", {
        config: {
          strategy_type: strategyType,
          strategy_params: defaultParams,
          initial_capital: 100000,
          start_date: "2024-01-01",
          end_date: "2024-12-31",
          risk_params: { max_position_size: 10, max_leverage: 2, max_drawdown_pct: 0.2 },
        }
      });
      
      const trades = extractTradesFromEquity(baseResult.equity_curve);
      const simulations: [number, number][][] = [];
      let equitySum = 0;
      let ddSum = 0;
      let winSum = 0;
      
      for (let sim = 0; sim < mcConfig.simulations; sim++) {
        const shuffled = [...trades].sort(() => Math.random() - 0.5);
        const equityPath = simulateEquityPath(100000, shuffled);
        simulations.push(equityPath);
        
        equitySum += equityPath[equityPath.length - 1][1];
        const maxDD = calculateMaxDrawdown(equityPath);
        ddSum += maxDD;
        winSum += shuffled.filter(t => t > 0).length / shuffled.length;
      }
      
      const equityMean = equitySum / mcConfig.simulations;
      const ddMean = ddSum / mcConfig.simulations;
      
      const sortedEquities = simulations.map(s => s[s.length - 1][1]).sort((a, b) => a - b);
      const sortedDDs = simulations.map(s => calculateMaxDrawdown(s)).sort((a, b) => a - b);
      
      setMcResults({
        final_equity_mean: equityMean,
        final_equity_p5: sortedEquities[Math.floor(mcConfig.simulations * 0.05)],
        final_equity_p95: sortedEquities[Math.floor(mcConfig.simulations * 0.95)],
        max_drawdown_mean: ddMean,
        max_drawdown_p5: sortedDDs[Math.floor(mcConfig.simulations * 0.05)],
        max_drawdown_p95: sortedDDs[Math.floor(mcConfig.simulations * 0.95)],
        win_rate_mean: winSum / mcConfig.simulations,
        simulations: simulations.slice(0, 10),
      });
    } catch (err) {
      console.error("Monte Carlo failed:", err);
    } finally {
      setMcRunning(false);
    }
  };

  const generateParamCombinations = (params: string[], ranges: { min: number; max: number; step: number }[]) => {
    const combinations: Record<string, number>[] = [];
    
    const generate = (index: number, current: Record<string, number>) => {
      if (index === params.length) {
        combinations.push({ ...current });
        return;
      }
      
      const range = ranges[index];
      for (let val = range.min; val <= range.max; val += range.step) {
        current[params[index]] = val;
        generate(index + 1, current);
      }
    };
    
    generate(0, {});
    return combinations;
  };

  const extractTradesFromEquity = (equity: [number, number][]) => {
    const trades: number[] = [];
    let lastEquity = equity[0]?.[1] || 100000;
    for (let i = 1; i < equity.length; i++) {
      const diff = equity[i][1] - lastEquity;
      if (Math.abs(diff) > 1) {
        trades.push(diff);
        lastEquity = equity[i][1];
      }
    }
    return trades.length > 0 ? trades : [0];
  };

  const simulateEquityPath = (initial: number, trades: number[]): [number, number][] => {
    const path: [number, number][] = [[0, initial]];
    let equity = initial;
    for (let i = 0; i < trades.length; i++) {
      equity += trades[i];
      path.push([i + 1, equity]);
    }
    return path;
  };

  const calculateMaxDrawdown = (path: [number, number][]) => {
    let maxDD = 0;
    let peak = path[0]?.[1] || 0;
    for (const [, equity] of path) {
      if (equity > peak) peak = equity;
      const dd = (peak - equity) / peak;
      if (dd > maxDD) maxDD = dd;
    }
    return maxDD * 100;
  };

  return (
    <div className="card">
      <div className="card-header">
        <span><BarChart2 size={14} /> Backtest Advanced</span>
      </div>
      
      <div className="card-body">
        <div className="mode-tabs">
          <button
            className={`tab-btn ${activeMode === "optimize" ? "active" : ""}`}
            onClick={() => setActiveMode("optimize")}
          >
            <Settings size={12} /> Optimize
          </button>
          <button
            className={`tab-btn ${activeMode === "walkforward" ? "active" : ""}`}
            onClick={() => setActiveMode("walkforward")}
          >
            <GitBranch size={12} /> Walk-Forward
          </button>
          <button
            className={`tab-btn ${activeMode === "montecarlo" ? "active" : ""}`}
            onClick={() => setActiveMode("montecarlo")}
          >
            <Shuffle size={12} /> Monte Carlo
          </button>
          <button
            className={`tab-btn ${activeMode === "compare" ? "active" : ""}`}
            onClick={() => setActiveMode("compare")}
          >
            <TrendingUp size={12} /> Compare
          </button>
        </div>

        {/* OPTIMIZATION MODE */}
        {activeMode === "optimize" && (
          <div className="mode-content">
            <div className="config-section">
              <h4>Grid Search Optimization</h4>
              
              <div className="param-config">
                {optConfig.parameters.map((param, idx) => (
                  <div key={param} className="param-row">
                    <label>{param}</label>
                    <input
                      type="number"
                      value={optConfig.ranges[idx].min}
                      onChange={(e) => {
                        const newRanges = [...optConfig.ranges];
                        newRanges[idx].min = parseFloat(e.target.value);
                        setOptConfig({ ...optConfig, ranges: newRanges });
                      }}
                      placeholder="Min"
                    />
                    <span>-</span>
                    <input
                      type="number"
                      value={optConfig.ranges[idx].max}
                      onChange={(e) => {
                        const newRanges = [...optConfig.ranges];
                        newRanges[idx].max = parseFloat(e.target.value);
                        setOptConfig({ ...optConfig, ranges: newRanges });
                      }}
                      placeholder="Max"
                    />
                    <input
                      type="number"
                      value={optConfig.ranges[idx].step}
                      onChange={(e) => {
                        const newRanges = [...optConfig.ranges];
                        newRanges[idx].step = parseFloat(e.target.value);
                        setOptConfig({ ...optConfig, ranges: newRanges });
                      }}
                      placeholder="Step"
                      style={{ width: 50 }}
                    />
                  </div>
                ))}
              </div>
              
              <button
                className="btn-run"
                onClick={runOptimization}
                disabled={optRunning}
              >
                <Play size={14} /> {optRunning ? "Optimizing..." : "Run Optimization"}
              </button>
            </div>
            
            {optResults.length > 0 && (
              <div className="results-section">
                <h4>Top Results</h4>
                <div className="results-table">
                  <div className="results-header">
                    <span>#</span>
                    {optConfig.parameters.map(p => <span key={p}>{p}</span>)}
                    <span>Sharpe</span>
                    <span>Return</span>
                    <span>Max DD</span>
                    <span>Win%</span>
                  </div>
                  {optResults.slice(0, 10).map((r, idx) => (
                    <div key={idx} className="results-row">
                      <span>{idx + 1}</span>
                      {optConfig.parameters.map(p => (
                        <span key={p}>{r.params[p]}</span>
                      ))}
                      <span className={r.metrics.sharpe > 1 ? "good" : r.metrics.sharpe > 0 ? "neutral" : "bad"}>
                        {r.metrics.sharpe.toFixed(2)}
                      </span>
                      <span className={r.metrics.return_pct > 0 ? "good" : "bad"}>
                        {r.metrics.return_pct.toFixed(1)}%
                      </span>
                      <span className="bad">{r.metrics.max_dd.toFixed(1)}%</span>
                      <span>{r.metrics.win_rate.toFixed(1)}%</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* WALK-FORWARD MODE */}
        {activeMode === "walkforward" && (
          <div className="mode-content">
            <div className="config-section">
              <h4>Walk-Forward Validation</h4>
              
              <div className="param-config">
                <div className="param-row">
                  <label>Training %</label>
                  <input
                    type="number"
                    value={wfConfig.train_pct}
                    onChange={(e) => setWfConfig({ ...wfConfig, train_pct: parseFloat(e.target.value) })}
                  />
                </div>
                <div className="param-row">
                  <label>Test %</label>
                  <input
                    type="number"
                    value={wfConfig.test_pct}
                    onChange={(e) => setWfConfig({ ...wfConfig, test_pct: parseFloat(e.target.value) })}
                  />
                </div>
                <div className="param-row">
                  <label>Folds</label>
                  <input
                    type="number"
                    value={wfConfig.folds}
                    onChange={(e) => setWfConfig({ ...wfConfig, folds: parseInt(e.target.value) })}
                    min={1}
                    max={5}
                  />
                </div>
              </div>
              
              <button
                className="btn-run"
                onClick={runWalkForward}
                disabled={wfRunning}
              >
                <Play size={14} /> {wfRunning ? "Running..." : "Run Walk-Forward"}
              </button>
            </div>
            
            {wfResults.length > 0 && (
              <div className="results-section">
                <h4>Results by Fold</h4>
                {wfResults.map((r, idx) => (
                  <div key={idx} className="fold-result">
                    <div className="fold-header">
                      <span>Fold {r.fold}</span>
                      <span>Train: {r.train_period.start} - {r.train_period.end}</span>
                      <span>Test: {r.test_period.start} - {r.test_period.end}</span>
                    </div>
                    <div className="fold-metrics">
                      <div className="metric-group">
                        <span className="metric-label">Training</span>
                        <span>Return: {r.train_metrics.total_return_pct.toFixed(1)}%</span>
                        <span>Sharpe: {r.train_metrics.sharpe_ratio.toFixed(2)}</span>
                      </div>
                      <div className="metric-group">
                        <span className="metric-label">Test</span>
                        <span className={r.test_metrics.total_return_pct > 0 ? "good" : "bad"}>
                          Return: {r.test_metrics.total_return_pct.toFixed(1)}%
                        </span>
                        <span>Sharpe: {r.test_metrics.sharpe_ratio.toFixed(2)}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* MONTE CARLO MODE */}
        {activeMode === "montecarlo" && (
          <div className="mode-content">
            <div className="config-section">
              <h4>Monte Carlo Simulation</h4>
              
              <div className="param-config">
                <div className="param-row">
                  <label>Simulations</label>
                  <input
                    type="number"
                    value={mcConfig.simulations}
                    onChange={(e) => setMcConfig({ ...mcConfig, simulations: parseInt(e.target.value) })}
                    min={10}
                    max={1000}
                  />
                </div>
                <div className="param-row">
                  <label>
                    <input
                      type="checkbox"
                      checked={mcConfig.resample_trades}
                      onChange={(e) => setMcConfig({ ...mcConfig, resample_trades: e.target.checked })}
                    />
                    Resample trades
                  </label>
                </div>
              </div>
              
              <button
                className="btn-run"
                onClick={runMonteCarlo}
                disabled={mcRunning}
              >
                <Play size={14} /> {mcRunning ? "Simulating..." : "Run Monte Carlo"}
              </button>
            </div>
            
            {mcResults && (
              <div className="results-section">
                <h4>Results</h4>
                <div className="mc-summary">
                  <div className="mc-metric">
                    <span className="mc-label">Final Equity</span>
                    <span className="mc-value">${mcResults.final_equity_mean.toFixed(0)}</span>
                    <span className="mc-range">
                      (${mcResults.final_equity_p5.toFixed(0)} - ${mcResults.final_equity_p95.toFixed(0)})
                    </span>
                  </div>
                  <div className="mc-metric">
                    <span className="mc-label">Max Drawdown</span>
                    <span className="mc-value">{mcResults.max_drawdown_mean.toFixed(1)}%</span>
                    <span className="mc-range">
                      ({mcResults.max_drawdown_p5.toFixed(1)}% - {mcResults.max_drawdown_p95.toFixed(1)}%)
                    </span>
                  </div>
                  <div className="mc-metric">
                    <span className="mc-label">Win Rate</span>
                    <span className="mc-value">{(mcResults.win_rate_mean * 100).toFixed(1)}%</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* COMPARE MODE */}
        {activeMode === "compare" && (
          <div className="mode-content">
            <div className="config-section">
              <h4>Strategy Comparison</h4>
              <p className="desc">Compare multiple strategies side by side</p>
              
              <button
                className="btn-run"
                disabled
              >
                Add Strategy to Compare
              </button>
            </div>
            
            <div className="results-section">
              <p className="empty-text">Select strategies above to compare their performance</p>
            </div>
          </div>
        )}
      </div>

      <style>{`
        .mode-tabs {
          display: flex;
          gap: 4px;
          margin-bottom: 12px;
        }
        .tab-btn {
          flex: 1;
          padding: 8px 4px;
          background: var(--bg-secondary);
          border: none;
          border-radius: 4px;
          color: var(--text-muted);
          font-size: 11px;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 4px;
        }
        .tab-btn.active {
          background: var(--accent);
          color: var(--bg-primary);
        }
        .mode-content {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .config-section h4 {
          font-size: 13px;
          margin-bottom: 8px;
        }
        .desc {
          font-size: 11px;
          color: var(--text-muted);
          margin-bottom: 8px;
        }
        .param-config {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .param-row {
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .param-row label {
          flex: 1;
          font-size: 11px;
          color: var(--text-muted);
        }
        .param-row input[type="number"] {
          width: 50px;
          padding: 4px;
          background: var(--bg-secondary);
          border: 1px solid var(--border);
          border-radius: 3px;
          color: var(--text-primary);
          font-size: 11px;
        }
        .param-row input[type="checkbox"] {
          margin-right: 6px;
        }
        .btn-run {
          width: 100%;
          padding: 10px;
          background: var(--accent);
          color: white;
          border: none;
          border-radius: 4px;
          cursor: pointer;
          font-size: 12px;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          margin-top: 8px;
        }
        .btn-run:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }
        .results-section h4 {
          font-size: 12px;
          margin-bottom: 8px;
        }
        .results-table {
          font-size: 11px;
        }
        .results-header, .results-row {
          display: grid;
          grid-template-columns: 30px repeat(3, 1fr) 50px 50px 40px;
          gap: 4px;
          padding: 4px;
        }
        .results-header {
          color: var(--text-muted);
          font-size: 10px;
        }
        .results-row {
          background: var(--bg-secondary);
          border-radius: 3px;
        }
        .good { color: var(--accent); }
        .bad { color: var(--danger); }
        .neutral { color: var(--warning); }
        .fold-result {
          background: var(--bg-secondary);
          border-radius: 4px;
          padding: 8px;
          margin-bottom: 6px;
        }
        .fold-header {
          display: flex;
          justify-content: space-between;
          font-size: 10px;
          color: var(--text-muted);
          margin-bottom: 6px;
        }
        .fold-metrics {
          display: flex;
          gap: 12px;
        }
        .metric-group {
          display: flex;
          flex-direction: column;
          gap: 2px;
          font-size: 11px;
        }
        .metric-label {
          color: var(--text-muted);
          font-size: 10px;
        }
        .mc-summary {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .mc-metric {
          display: flex;
          flex-direction: column;
          background: var(--bg-secondary);
          padding: 8px;
          border-radius: 4px;
        }
        .mc-label {
          font-size: 10px;
          color: var(--text-muted);
        }
        .mc-value {
          font-size: 16px;
          font-weight: 600;
        }
        .mc-range {
          font-size: 10px;
          color: var(--text-muted);
        }
        .empty-text {
          text-align: center;
          color: var(--text-muted);
          font-size: 11px;
          padding: 20px;
        }
      `}</style>
    </div>
  );
}
