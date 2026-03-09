import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Database, RefreshCw, Calendar, TrendingUp } from "lucide-react";

interface DataStats {
  total_bars: number;
  start_date: string | null;
  end_date: string | null;
  min_price: number | string | null;
  max_price: number | string | null;
}

export function DataManager() {
  const [stats, setStats] = useState<DataStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const formatError = (err: unknown) => {
    if (err instanceof Error) return err.message;
    if (typeof err === "string") return err;
    try {
      return JSON.stringify(err);
    } catch {
      return String(err);
    }
  };

  const loadStats = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await invoke<DataStats>("fetch_data_stats", {
        symbol: "XAUUSD",
        timeframe: "M1",
      });
      setStats(data);
    } catch (err) {
      setError(formatError(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStats();
  }, []);

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return "N/A";
    return new Date(dateStr).toLocaleDateString();
  };

  const formatNumber = (num: number | null) => {
    if (num === null) return "N/A";
    return num.toLocaleString();
  };

  const formatPrice = (price: number | string | null) => {
    if (price === null || price === undefined) return "N/A";
    const num = typeof price === "string" ? parseFloat(price) : price;
    if (isNaN(num)) return "N/A";
    return `$${num.toFixed(2)}`;
  };

  return (
    <div className="data-manager">
      <div className="panel-header">
        <Database size={20} />
        <h3>XAUUSD Data</h3>
        <button
          className="btn-icon"
          onClick={loadStats}
          disabled={loading}
          title="Refresh"
        >
          <RefreshCw size={16} className={loading ? "spinning" : ""} />
        </button>
      </div>

      {error && (
        <div className="error-message">
          <p>{error}</p>
        </div>
      )}

      {stats && (
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-icon">
              <Database size={24} />
            </div>
            <div className="stat-content">
              <div className="stat-label">Total Bars</div>
              <div className="stat-value">{formatNumber(stats.total_bars)}</div>
            </div>
          </div>

          <div className="stat-card">
            <div className="stat-icon">
              <Calendar size={24} />
            </div>
            <div className="stat-content">
              <div className="stat-label">Date Range</div>
              <div className="stat-value-small">
                {formatDate(stats.start_date)}
                <br />
                to {formatDate(stats.end_date)}
              </div>
            </div>
          </div>

          <div className="stat-card">
            <div className="stat-icon">
              <TrendingUp size={24} />
            </div>
            <div className="stat-content">
              <div className="stat-label">Price Range</div>
              <div className="stat-value-small">
                {formatPrice(stats.min_price)}
                <br />
                to {formatPrice(stats.max_price)}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
