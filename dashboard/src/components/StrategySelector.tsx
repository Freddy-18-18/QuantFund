import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Settings, ChevronDown, Info } from "lucide-react";

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
  /** false = not yet implemented; shown as disabled with a "Coming Soon" badge */
  available: boolean;
  parameters: StrategyParameter[];
}

interface StrategyConfig {
  fast_period?: number;
  slow_period?: number;
  position_size?: number;
  period?: number;
  std_dev?: number;
}

interface Props {
  onConfigChange: (strategyType: string, config: StrategyConfig) => void;
  /** Called whenever the currently selected strategy's availability changes */
  onAvailableChange?: (available: boolean) => void;
}

export function StrategySelector({ onConfigChange, onAvailableChange }: Props) {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState<string>("");
  const [config, setConfig] = useState<StrategyConfig>({});
  const [showDetails, setShowDetails] = useState(false);

  useEffect(() => {
    loadStrategies();
  }, []);

  const loadStrategies = async () => {
    try {
      const data = await invoke<StrategyInfo[]>("load_strategies");
      setStrategies(data);
      // Auto-select the first available strategy
      const first = data.find((s) => s.available) ?? data[0];
      if (first) {
        setSelectedStrategy(first.id);
        initializeConfig(first);
      }
    } catch (err) {
      console.error("Failed to load strategies:", err);
    }
  };

  const initializeConfig = (strategy: StrategyInfo) => {
    const initialConfig: StrategyConfig = {};
    strategy.parameters.forEach((param) => {
      const key = param.name as keyof StrategyConfig;
      initialConfig[key] = parseFloat(param.default_value);
    });
    setConfig(initialConfig);
    onConfigChange(strategy.id, initialConfig);
    onAvailableChange?.(strategy.available);
  };

  const handleStrategyChange = (strategyId: string) => {
    const strategy = strategies.find((s) => s.id === strategyId);
    if (!strategy || !strategy.available) return;
    setSelectedStrategy(strategyId);
    initializeConfig(strategy);
  };

  const handleParamChange = (paramName: string, value: number) => {
    const newConfig = { ...config, [paramName]: value };
    setConfig(newConfig);
    onConfigChange(selectedStrategy, newConfig);
  };

  const currentStrategy = strategies.find((s) => s.id === selectedStrategy);

  return (
    <div className="strategy-selector">
      <div className="panel-header">
        <Settings size={20} />
        <h3>Strategy Configuration</h3>
        <button
          className="btn-icon"
          onClick={() => setShowDetails(!showDetails)}
          title="Toggle details"
        >
          <ChevronDown
            size={16}
            style={{
              transform: showDetails ? "rotate(180deg)" : "rotate(0deg)",
              transition: "transform 0.2s",
            }}
          />
        </button>
      </div>

      <div className="strategy-select-wrapper">
        <label>Strategy Type</label>
        <select
          value={selectedStrategy}
          onChange={(e) => handleStrategyChange(e.target.value)}
          className="strategy-select"
        >
          {strategies.map((strategy) => (
            <option
              key={strategy.id}
              value={strategy.id}
              disabled={!strategy.available}
            >
              {strategy.name}
              {!strategy.available ? " (Coming Soon)" : ""}
            </option>
          ))}
        </select>
      </div>

      {currentStrategy && !currentStrategy.available && (
        <div className="coming-soon-banner">
          This strategy is not yet implemented.
        </div>
      )}

      {currentStrategy && showDetails && (
        <div className="strategy-details">
          <div className="strategy-description">
            <Info size={16} />
            <p>{currentStrategy.description}</p>
          </div>

          <div className="parameters-grid">
            {currentStrategy.parameters.map((param) => (
              <div key={param.name} className="parameter-control">
                <label>{param.name.replace(/_/g, " ").toUpperCase()}</label>
                <input
                  type="number"
                  value={config[param.name as keyof StrategyConfig] || param.default_value}
                  onChange={(e) =>
                    handleParamChange(param.name, parseFloat(e.target.value))
                  }
                  min={param.min}
                  max={param.max}
                  step={param.param_type === "number" ? 0.01 : 1}
                  className="param-input"
                />
                {param.min !== undefined && param.max !== undefined && (
                  <span className="param-range">
                    ({param.min} - {param.max})
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
