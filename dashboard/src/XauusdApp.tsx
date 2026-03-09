import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { Play, Square, Download } from "lucide-react";

// Components - Navigation
import { Sidebar, ViewType } from "./components/Sidebar";

// Components - Views
import { DashboardView } from "./components/DashboardView";
import { BacktestView } from "./components/BacktestView";
import { TradingView } from "./components/TradingView";
import { MacroDataPanel, DataSource } from "./components/MacroDataPanel";
import { NewsView } from "./components/NewsView";
import { PortfolioView } from "./components/PortfolioView";
import { SettingsView } from "./components/SettingsView";

// Components - Original
import { DataManager } from "./components/DataManager";
import { StrategySelector } from "./components/StrategySelector";

interface BacktestConfig {
  initial_capital: number;
  start_date: string | null;
  end_date: string | null;
  strategy_type: string;
  strategy_params: {
    fast_period: number;
    slow_period: number;
    position_size: number;
  };
  risk_params: {
    max_position_size: number;
    max_leverage: number;
    max_drawdown_pct: number;
  };
}

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

export default function XauusdApp() {
  // Navigation state
  const [activeView, setActiveView] = useState<ViewType>("dashboard");
  const [activeSource, setActiveSource] = useState<DataSource>("fred");
  
  // Backtest state
  const [config, setConfig] = useState<BacktestConfig>({
    initial_capital: 100000,
    start_date: null,
    end_date: null,
    strategy_type: "sma_crossover",
    strategy_params: {
      fast_period: 20,
      slow_period: 50,
      position_size: 0.1,
    },
    risk_params: {
      max_position_size: 10.0,
      max_leverage: 2.0,
      max_drawdown_pct: 0.2,
    },
  });

  const [result, setResult] = useState<BacktestResult | null>(null);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState("");
  const [showSettings] = useState(false);
  const [strategyAvailable, setStrategyAvailable] = useState(true);

  useEffect(() => {
    const unlisten = listen<[number, string]>("backtest-progress", (event) => {
      const [prog, msg] = event.payload;
      setProgress(prog);
      setProgressMessage(msg);
    });

    return () => {
      unlisten.then((fn) => fn());
    };
  }, []);

  const handleStrategyChange = (strategyType: string, strategyConfig: any) => {
    setConfig({
      ...config,
      strategy_type: strategyType,
      strategy_params: {
        ...config.strategy_params,
        ...strategyConfig,
      },
    });
  };

  const cancelBacktest = async () => {
    try {
      await invoke("cancel_backtest");
    } catch (err) {
      console.error("Failed to send cancel:", err);
    }
  };

  const runBacktest = async () => {
    setRunning(true);
    setProgress(0);
    setProgressMessage("Starting backtest...");
    setResult(null);

    try {
      const backtestResult = await invoke<BacktestResult>("start_xauusd_backtest", {
        config,
      });
      setResult(backtestResult);
      setProgressMessage("Backtest complete!");
    } catch (err) {
      if (err === "Cancelled") {
        setProgressMessage("Backtest cancelled.");
      } else {
        console.error("Backtest failed:", err);
        setProgressMessage(`Error: ${err}`);
      }
    } finally {
      setRunning(false);
    }
  };

  const exportResults = () => {
    if (!result) return;
    const json = JSON.stringify(result, null, 2);
    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `xauusd_backtest_${new Date().toISOString()}.json`;
    a.click();
  };

  // Render the appropriate view
  const renderView = () => {
    switch (activeView) {
      case "dashboard":
        return <DashboardView />;
      case "backtest":
        return (
          <div className="backtest-full">
            <BacktestView />
            {/* Add original backtest functionality */}
            <div style={{ marginTop: "1.5rem" }}>
              <div className="sidebar" style={{ background: "var(--bg-secondary)", borderRadius: "0.75rem", padding: "1rem" }}>
                <DataManager />
                <StrategySelector
                  onConfigChange={handleStrategyChange}
                  onAvailableChange={setStrategyAvailable}
                />
                {showSettings && (
                  <div className="settings-panel">
                    <h3>Risk Parameters</h3>
                    <div className="settings-grid">
                      <div className="setting-item">
                        <label>Initial Capital</label>
                        <input
                          type="number"
                          value={config.initial_capital}
                          onChange={(e) =>
                            setConfig({
                              ...config,
                              initial_capital: parseFloat(e.target.value),
                            })
                          }
                          className="setting-input"
                        />
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      case "trading":
        return <TradingView />;
      case "macro":
        return <MacroDataPanel activeSource={activeSource} onSourceChange={setActiveSource} />;
      case "news":
        return <NewsView />;
      case "portfolio":
        return <PortfolioView />;
      case "settings":
        return <SettingsView />;
      default:
        return <DashboardView />;
    }
  };

  return (
    <div className="app-layout">
      {/* Sidebar Navigation */}
      <Sidebar activeView={activeView} onViewChange={setActiveView} />

      {/* Main Content Area */}
      <div className="main-area">
        {/* Header */}
        <header className="app-header">
          <div className="header-left">
            {activeView === "macro" ? (
              <div style={{ display: "flex", alignItems: "center", gap: "1.5rem" }}>
                <div style={{ display: "flex", flexDirection: "column" }}>
                  <h1 style={{ fontSize: "1.2rem" }}>Macro Insights</h1>
                  <span className="subtitle">Global Economic Intelligence</span>
                </div>
                <div style={{ display: "flex", gap: "0.5rem", marginLeft: "1rem", background: "rgba(0,0,0,0.2)", padding: "0.25rem", borderRadius: "0.6rem" }}>
                  <button 
                    onClick={() => setActiveSource("fred")} 
                    className={`btn ${activeSource === "fred" ? "btn-primary" : "btn-secondary"}`}
                    style={{ padding: "0.4rem 0.8rem", fontSize: "0.75rem", minWidth: "100px", border: "none" }}
                  >
                    FRED (EE.UU)
                  </button>
                  <button 
                    onClick={() => setActiveSource("imf")} 
                    className={`btn ${activeSource === "imf" ? "btn-primary" : "btn-secondary"}`}
                    style={{ padding: "0.4rem 0.8rem", fontSize: "0.75rem", minWidth: "80px", border: "none" }}
                  >
                    FMI
                  </button>
                  <button 
                    onClick={() => setActiveSource("worldbank")} 
                    className={`btn ${activeSource === "worldbank" ? "btn-primary" : "btn-secondary"}`}
                    style={{ padding: "0.4rem 0.8rem", fontSize: "0.75rem", minWidth: "100px", border: "none" }}
                  >
                    BANCO MUNDIAL
                  </button>
                </div>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column" }}>
                <h1>QuantFund Terminal</h1>
                <span className="subtitle">Institutional Quantitative Analysis</span>
              </div>
            )}
          </div>

          <div className="header-controls">
            {activeView === "backtest" && (
              <>
                {!running ? (
                  <button
                    className="btn btn-primary"
                    onClick={runBacktest}
                    disabled={!strategyAvailable}
                    title={!strategyAvailable ? "Selected strategy is not yet implemented" : undefined}
                  >
                    <Play size={18} />
                    Run Backtest
                  </button>
                ) : (
                  <button className="btn btn-danger" onClick={cancelBacktest}>
                    <Square size={18} />
                    Stop
                  </button>
                )}

                {result && (
                  <button className="btn btn-secondary" onClick={exportResults}>
                    <Download size={18} />
                    Export
                  </button>
                )}
              </>
            )}
          </div>
        </header>

        {/* Progress Bar */}
        {running && (
          <div className="progress-section">
            <div className="progress-bar">
              <div
                className="progress-fill"
                style={{ width: `${progress}%` }}
              />
            </div>
            <span className="progress-text">{progressMessage}</span>
          </div>
        )}

        {/* Content Area */}
        <div className="content-area" style={{ padding: activeView === "macro" ? "0" : "1.5rem" }}>
          {renderView()}
        </div>
      </div>
    </div>
  );
}
