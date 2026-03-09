import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Settings, Play, Save, Zap } from "lucide-react";

interface StrategyParameter {
  name: string;
  param_type: string;
  default_value: string;
  min?: number;
  max?: number;
}

interface StrategyInfo {
  id: string;
  name: string;
  description: string;
  available: boolean;
  parameters: StrategyParameter[];
}

interface StrategyConfig {
  id: string;
  name: string;
  params: Record<string, number | string>;
}

interface OptimizationResult {
  params: Record<string, number | string>;
  sharpe: number;
  return_pct: number;
  max_dd: number;
  win_rate: number;
}

interface Props {
  currentConfig: StrategyConfig | null;
  onConfigChange: (config: StrategyConfig) => void;
  onRunBacktest: () => void;
  isRunning: boolean;
}

export function StrategyEditor({ currentConfig, onConfigChange, onRunBacktest, isRunning }: Props) {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState<StrategyInfo | null>(null);
  const [params, setParams] = useState<Record<string, number | string>>({});
  const [savedConfigs, setSavedConfigs] = useState<StrategyConfig[]>([]);
  // const [showOptimizer, setShowOptimizer] = useState(false);
  const [optimizing, setOptimizing] = useState(false);
  const [optimizationResults, setOptimizationResults] = useState<OptimizationResult[]>([]);
  const [activeTab, setActiveTab] = useState<"config" | "optimizer" | "saved">("config");

  useEffect(() => {
    loadStrategies();
    loadSavedConfigs();
  }, []);

  useEffect(() => {
    if (currentConfig) {
      const strategy = strategies.find(s => s.id === currentConfig.id);
      if (strategy) {
        setSelectedStrategy(strategy);
        setParams(currentConfig.params);
      }
    }
  }, [currentConfig, strategies]);

  const loadStrategies = async () => {
    try {
      const infos = await invoke<StrategyInfo[]>("load_strategies");
      setStrategies(infos);
      if (infos.length > 0 && !selectedStrategy) {
        setSelectedStrategy(infos[0]);
        const defaultParams: Record<string, number | string> = {};
        infos[0].parameters.forEach(p => {
          defaultParams[p.name] = parseFloat(p.default_value);
        });
        setParams(defaultParams);
      }
    } catch (err) {
      console.error("Failed to load strategies:", err);
    }
  };

  const loadSavedConfigs = async () => {
    try {
      const config = await invoke<StrategyConfig | null>("load_strategy_config");
      if (config) {
        setSavedConfigs(prev => {
          const exists = prev.some(c => c.id === config.id && JSON.stringify(c.params) === JSON.stringify(config.params));
          if (!exists) return [...prev, config];
          return prev;
        });
      }
    } catch (err) {
      console.error("Failed to load saved configs:", err);
    }
  };

  const handleStrategyChange = (strategyId: string) => {
    const strategy = strategies.find(s => s.id === strategyId);
    if (strategy) {
      setSelectedStrategy(strategy);
      const defaultParams: Record<string, number | string> = {};
      strategy.parameters.forEach(p => {
        defaultParams[p.name] = parseFloat(p.default_value);
      });
      setParams(defaultParams);
      onConfigChange({
        id: strategy.id,
        name: strategy.name,
        params: defaultParams,
      });
    }
  };

  const handleParamChange = (name: string, value: number | string) => {
    const newParams = { ...params, [name]: value };
    setParams(newParams);
    if (selectedStrategy) {
      onConfigChange({
        id: selectedStrategy.id,
        name: selectedStrategy.name,
        params: newParams,
      });
    }
  };

  const handleSaveConfig = async () => {
    if (!selectedStrategy) return;
    
    const config: StrategyConfig = {
      id: selectedStrategy.id,
      name: `${selectedStrategy.name} - ${new Date().toLocaleDateString()}`,
      params,
    };

    try {
      await invoke("save_strategy_config", {
        config: {
          strategy_type: selectedStrategy.id,
          strategy_params: params,
          initial_capital: 100000,
          risk_params: { max_position_size: 10, max_leverage: 2, max_drawdown_pct: 0.2 },
        }
      });
      
      setSavedConfigs(prev => [...prev, config]);
    } catch (err) {
      console.error("Failed to save config:", err);
    }
  };

  const handleLoadConfig = (config: StrategyConfig) => {
    const strategy = strategies.find(s => s.id === config.id);
    if (strategy) {
      setSelectedStrategy(strategy);
      setParams(config.params);
      onConfigChange(config);
    }
  };

  const runOptimization = async () => {
    if (!selectedStrategy) return;
    
    setOptimizing(true);
    setOptimizationResults([]);

    try {
      const paramCombinations = generateParamCombinations(selectedStrategy.parameters);
      const results: OptimizationResult[] = [];

      for (const combo of paramCombinations.slice(0, 50)) {
        const result = await invoke<any>("start_xauusd_backtest", {
          config: {
            strategy_type: selectedStrategy.id,
            strategy_params: combo,
            initial_capital: 100000,
            start_date: "2024-01-01",
            end_date: "2024-12-31",
            risk_params: { max_position_size: 10, max_leverage: 2, max_drawdown_pct: 0.2 },
          }
        });
        
        results.push({
          params: combo,
          sharpe: result.base_result.sharpe_ratio,
          return_pct: result.base_result.total_return_pct,
          max_dd: result.base_result.max_drawdown_pct,
          win_rate: result.base_result.win_rate,
        });
      }

      results.sort((a, b) => b.sharpe - a.sharpe);
      setOptimizationResults(results.slice(0, 10));
    } catch (err) {
      console.error("Optimization failed:", err);
    } finally {
      setOptimizing(false);
    }
  };

  const generateParamCombinations = (parameters: StrategyParameter[]): Record<string, number>[] => {
    const combinations: Record<string, number>[] = [];
    const steps = 3;
    
    const ranges = parameters.map(p => {
      const min = p.min || 1;
      const max = p.max || 100;
      const step = (max - min) / steps;
      const values: number[] = [];
      for (let i = 0; i <= steps; i++) {
        values.push(Math.round((min + step * i) * 10) / 10);
      }
      return values;
    });

    const generate = (index: number, current: Record<string, number>) => {
      if (index === parameters.length) {
        combinations.push({ ...current });
        return;
      }
      for (const val of ranges[index]) {
        current[parameters[index].name] = val;
        generate(index + 1, current);
      }
    };

    generate(0, {});
    return combinations;
  };

  return (
    <div className="card">
      <div className="card-header">
        <span><Settings size={14} /> Strategy Editor</span>
      </div>
      
      <div className="card-body">
        <div className="strategy-tabs">
          <button
            className={`tab-btn ${activeTab === "config" ? "active" : ""}`}
            onClick={() => setActiveTab("config")}
          >
            Config
          </button>
          <button
            className={`tab-btn ${activeTab === "optimizer" ? "active" : ""}`}
            onClick={() => setActiveTab("optimizer")}
          >
            Optimizer
          </button>
          <button
            className={`tab-btn ${activeTab === "saved" ? "active" : ""}`}
            onClick={() => setActiveTab("saved")}
          >
            Saved
          </button>
        </div>

        {activeTab === "config" && (
          <div className="strategy-config">
            <div className="config-row">
              <label>Strategy</label>
              <select
                value={selectedStrategy?.id || ""}
                onChange={(e) => handleStrategyChange(e.target.value)}
                className="config-select"
              >
                {strategies.map(s => (
                  <option key={s.id} value={s.id} disabled={!s.available}>
                    {s.name} {!s.available ? "(Coming Soon)" : ""}
                  </option>
                ))}
              </select>
            </div>

            {selectedStrategy && (
              <div className="params-section">
                <label className="params-label">Parameters</label>
                {selectedStrategy.parameters.map(param => (
                  <div key={param.name} className="param-row">
                    <label>{param.name.replace("_", " ")}</label>
                    <input
                      type="number"
                      value={params[param.name] || ""}
                      onChange={(e) => handleParamChange(param.name, parseFloat(e.target.value))}
                      min={param.min}
                      max={param.max}
                      step={1}
                      className="param-input"
                    />
                    <span className="param-range">
                      {param.min} - {param.max}
                    </span>
                  </div>
                ))}
              </div>
            )}

            <div className="config-actions">
              <button className="btn btn-secondary" onClick={handleSaveConfig}>
                <Save size={14} /> Save
              </button>
              <button
                className="btn btn-primary"
                onClick={onRunBacktest}
                disabled={isRunning}
              >
                <Play size={14} /> {isRunning ? "Running..." : "Run"}
              </button>
            </div>
          </div>
        )}

        {activeTab === "optimizer" && (
          <div className="optimizer-section">
            <div className="optimizer-header">
              <Zap size={16} />
              <span>Parameter Optimization</span>
            </div>
            <p className="optimizer-desc">
              Test multiple parameter combinations to find optimal settings
            </p>
            
            {selectedStrategy && (
              <div className="optimizer-params">
                <label>Parameters to optimize:</label>
                {selectedStrategy.parameters.map(param => (
                  <div key={param.name} className="optimizer-param">
                    <input type="checkbox" defaultChecked />
                    <span>{param.name}</span>
                    <span className="param-range">[{param.min} - {param.max}]</span>
                  </div>
                ))}
              </div>
            )}

            <button
              className="btn btn-optimize"
              onClick={runOptimization}
              disabled={optimizing}
            >
              {optimizing ? (
                <>Optimizing...</>
              ) : (
                <><Zap size={14} /> Start Optimization</>
              )}
            </button>

            {optimizationResults.length > 0 && (
              <div className="optimizer-results">
                <label>Top Results:</label>
                {optimizationResults.map((result, idx) => (
                  <div
                    key={idx}
                    className="result-item"
                    onClick={() => {
                      setParams(result.params);
                      if (selectedStrategy) {
                        onConfigChange({
                          id: selectedStrategy.id,
                          name: selectedStrategy.name,
                          params: result.params,
                        });
                      }
                    }}
                  >
                    <span className="result-rank">#{idx + 1}</span>
                    <span className="result-sharpe">SR: {result.sharpe.toFixed(2)}</span>
                    <span className="result-return">{result.return_pct.toFixed(1)}%</span>
                    <span className="result-dd">DD: {result.max_dd.toFixed(1)}%</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === "saved" && (
          <div className="saved-section">
            {savedConfigs.length === 0 ? (
              <p className="empty-text">No saved configurations</p>
            ) : (
              savedConfigs.map((config, idx) => (
                <div
                  key={idx}
                  className="saved-item"
                  onClick={() => handleLoadConfig(config)}
                >
                  <div className="saved-header">
                    <span className="saved-name">{config.name}</span>
                    <span className="saved-strategy">{config.id}</span>
                  </div>
                  <div className="saved-params">
                    {Object.entries(config.params).map(([k, v]) => (
                      <span key={k} className="param-chip">
                        {k}: {v}
                      </span>
                    ))}
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      <style>{`
        .strategy-tabs {
          display: flex;
          gap: 4px;
          margin-bottom: 12px;
        }
        .tab-btn {
          flex: 1;
          padding: 8px;
          background: var(--bg-secondary);
          border: none;
          border-radius: 4px;
          color: var(--text-muted);
          font-size: 12px;
          cursor: pointer;
        }
        .tab-btn.active {
          background: var(--accent);
          color: var(--bg-primary);
        }
        .config-row {
          margin-bottom: 12px;
        }
        .config-row label {
          display: block;
          font-size: 11px;
          color: var(--text-muted);
          margin-bottom: 4px;
        }
        .config-select {
          width: 100%;
          padding: 8px;
          background: var(--bg-secondary);
          border: 1px solid var(--border);
          border-radius: 4px;
          color: var(--text-primary);
          font-size: 13px;
        }
        .params-section {
          margin-bottom: 12px;
        }
        .params-label {
          display: block;
          font-size: 11px;
          color: var(--text-muted);
          margin-bottom: 8px;
        }
        .param-row {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 6px;
        }
        .param-row label {
          flex: 1;
          font-size: 11px;
          color: var(--text-muted);
        }
        .param-input {
          width: 60px;
          padding: 4px 6px;
          background: var(--bg-secondary);
          border: 1px solid var(--border);
          border-radius: 3px;
          color: var(--text-primary);
          font-size: 12px;
          text-align: right;
        }
        .param-range {
          font-size: 9px;
          color: var(--text-muted);
          width: 50px;
        }
        .config-actions {
          display: flex;
          gap: 8px;
        }
        .optimizer-section {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .optimizer-header {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 14px;
          font-weight: 600;
        }
        .optimizer-desc {
          font-size: 11px;
          color: var(--text-muted);
        }
        .optimizer-params {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .optimizer-param {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 11px;
        }
        .btn-optimize {
          background: linear-gradient(135deg, #6366f1, #8b5cf6);
          color: white;
          border: none;
          padding: 10px;
          border-radius: 4px;
          cursor: pointer;
          font-weight: 600;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
        }
        .btn-optimize:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }
        .optimizer-results {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .result-item {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 6px 8px;
          background: var(--bg-secondary);
          border-radius: 4px;
          font-size: 11px;
          cursor: pointer;
        }
        .result-item:hover {
          background: var(--accent);
          color: var(--bg-primary);
        }
        .result-rank { font-weight: 600; }
        .result-sharpe { color: var(--accent); }
        .result-return { color: var(--success); }
        .result-dd { color: var(--danger); }
        .saved-section {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .empty-text {
          text-align: center;
          color: var(--text-muted);
          font-size: 12px;
          padding: 20px;
        }
        .saved-item {
          padding: 8px;
          background: var(--bg-secondary);
          border-radius: 4px;
          cursor: pointer;
        }
        .saved-item:hover {
          border: 1px solid var(--accent);
        }
        .saved-header {
          display: flex;
          justify-content: space-between;
          margin-bottom: 4px;
        }
        .saved-name {
          font-size: 12px;
          font-weight: 600;
        }
        .saved-strategy {
          font-size: 10px;
          color: var(--text-muted);
        }
        .saved-params {
          display: flex;
          flex-wrap: wrap;
          gap: 4px;
        }
        .param-chip {
          font-size: 9px;
          padding: 2px 4px;
          background: var(--bg-primary);
          border-radius: 3px;
        }
      `}</style>
    </div>
  );
}
