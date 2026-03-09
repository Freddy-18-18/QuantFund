import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { RefreshCw, Brain, Newspaper, Clock } from "lucide-react";

interface NewsItem {
  id: string;
  title: string;
  summary: string;
  source: string;
  url: string;
  published_at: string;
  sentiment: string | null;
  symbols: string[];
}

interface AiAnalysis {
  summary: string;
  sentiment: string;
  sentiment_score: number;
  key_events: string[];
  impact_on_xauusd: string;
  trading_recommendation: string;
  risk_level: string;
}

export function NewsPanel() {
  const [news, setNews] = useState<NewsItem[]>([]);
  const [analysis, setAnalysis] = useState<AiAnalysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchNews = async () => {
    setLoading(true);
    setError(null);
    try {
      const items = await invoke<NewsItem[]>("fetch_financial_news");
      setNews(items);
      setLastUpdate(new Date());
    } catch (err) {
      setError(String(err));
      console.error("Failed to fetch news:", err);
    } finally {
      setLoading(false);
    }
  };

  const analyzeWithAI = async () => {
    if (news.length === 0) {
      await fetchNews();
    }
    
    setAnalyzing(true);
    try {
      const result = await invoke<AiAnalysis>("analyze_news_with_ai", { newsItems: news });
      setAnalysis(result);
    } catch (err) {
      setError(String(err));
      console.error("AI analysis failed:", err);
    } finally {
      setAnalyzing(false);
    }
  };

  const getSentimentColor = (sentiment: string | null) => {
    if (!sentiment) return "var(--text-muted)";
    switch (sentiment.toUpperCase()) {
      case "BULLISH":
      case "POSITIVE":
        return "var(--accent)";
      case "BEARISH":
      case "NEGATIVE":
        return "var(--danger)";
      default:
        return "var(--warning)";
    }
  };

  const getRecommendationColor = (rec: string) => {
    switch (rec.toUpperCase()) {
      case "BUY":
        return "var(--accent)";
      case "SELL":
        return "var(--danger)";
      default:
        return "var(--warning)";
    }
  };

  const getRiskColor = (risk: string) => {
    switch (risk.toUpperCase()) {
      case "LOW":
        return "var(--accent)";
      case "MEDIUM":
        return "var(--warning)";
      case "HIGH":
        return "var(--danger)";
      default:
        return "var(--text-muted)";
    }
  };

  const formatTime = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diff = Math.floor((now.getTime() - date.getTime()) / 1000 / 60);
    
    if (diff < 60) return `${diff}m ago`;
    if (diff < 1440) return `${Math.floor(diff / 60)}h ago`;
    return `${Math.floor(diff / 1440)}d ago`;
  };

  useEffect(() => {
    fetchNews();
    const interval = setInterval(fetchNews, 300000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="card" style={{ height: "100%" }}>
      <div className="card-header">
        <span><Newspaper size={14} /> Market News & AI Analysis</span>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            className="btn-icon"
            onClick={fetchNews}
            disabled={loading}
            title="Refresh news"
          >
            <RefreshCw size={14} className={loading ? "spinning" : ""} />
          </button>
        </div>
      </div>
      
      <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {/* AI Analysis Section */}
        <div className="ai-section">
          <div className="ai-header">
            <Brain size={16} />
            <span>AI Market Analysis</span>
            <button
              className="btn-analyze"
              onClick={analyzeWithAI}
              disabled={analyzing || news.length === 0}
            >
              {analyzing ? "Analyzing..." : "Analyze with AI"}
            </button>
          </div>
          
          {analysis ? (
            <div className="ai-content">
              <div className="ai-summary">
                {analysis.summary}
              </div>
              
              <div className="ai-metrics">
                <div className="ai-metric">
                  <span className="metric-label">Sentiment</span>
                  <span className="metric-value" style={{ color: getSentimentColor(analysis.sentiment) }}>
                    {analysis.sentiment_score >= 0 ? "+" : ""}{analysis.sentiment_score.toFixed(2)}
                  </span>
                </div>
                <div className="ai-metric">
                  <span className="metric-label">Impact</span>
                  <span className="metric-value" style={{ color: getSentimentColor(analysis.impact_on_xauusd) }}>
                    {analysis.impact_on_xauusd}
                  </span>
                </div>
                <div className="ai-metric">
                  <span className="metric-label">Risk</span>
                  <span className="metric-value" style={{ color: getRiskColor(analysis.risk_level) }}>
                    {analysis.risk_level}
                  </span>
                </div>
              </div>
              
              <div className="ai-recommendation">
                <span className="rec-label">Recommendation</span>
                <span className="rec-value" style={{ color: getRecommendationColor(analysis.trading_recommendation) }}>
                  {analysis.trading_recommendation}
                </span>
              </div>
              
              {analysis.key_events.length > 0 && (
                <div className="ai-events">
                  <span className="events-label">Key Events:</span>
                  <ul>
                    {analysis.key_events.map((event, idx) => (
                      <li key={idx}>{event}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ) : (
            <div className="ai-placeholder">
              <Brain size={24} />
              <p>Click "Analyze with AI" to get AI-powered market analysis</p>
            </div>
          )}
        </div>

        {/* News List */}
        <div className="news-section">
          <div className="news-header">
            <span>Latest News</span>
            {lastUpdate && (
              <span className="last-update">
                <Clock size={12} /> {formatTime(lastUpdate.toISOString())}
              </span>
            )}
          </div>
          
          {loading && news.length === 0 ? (
            <div className="news-loading">Loading news...</div>
          ) : error && news.length === 0 ? (
            <div className="news-error">{error}</div>
          ) : (
            <div className="news-list">
              {news.map((item) => (
                <div key={item.id} className="news-item">
                  <div className="news-item-header">
                    <span className="news-source">{item.source}</span>
                    <span className="news-time">{formatTime(item.published_at)}</span>
                  </div>
                  <h4 className="news-title">{item.title}</h4>
                  <p className="news-summary">{item.summary}</p>
                  <div className="news-symbols">
                    {item.symbols.map((sym) => (
                      <span key={sym} className="symbol-tag">{sym}</span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <style>{`
        .ai-section {
          background: linear-gradient(135deg, rgba(99, 102, 241, 0.1), rgba(139, 92, 246, 0.1));
          border: 1px solid rgba(99, 102, 241, 0.3);
          border-radius: 8px;
          padding: 12px;
        }
        .ai-header {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 12px;
          font-size: 13px;
          font-weight: 600;
        }
        .btn-analyze {
          margin-left: auto;
          padding: 6px 12px;
          background: linear-gradient(135deg, #6366f1, #8b5cf6);
          color: white;
          border: none;
          border-radius: 4px;
          cursor: pointer;
          font-size: 11px;
          font-weight: 600;
        }
        .btn-analyze:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        .ai-content {
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        .ai-summary {
          font-size: 12px;
          line-height: 1.5;
          color: var(--text-primary);
        }
        .ai-metrics {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 8px;
        }
        .ai-metric {
          display: flex;
          flex-direction: column;
          align-items: center;
          padding: 8px;
          background: var(--bg-secondary);
          border-radius: 4px;
        }
        .ai-metric .metric-label {
          font-size: 10px;
          color: var(--text-muted);
        }
        .ai-metric .metric-value {
          font-size: 14px;
          font-weight: 600;
        }
        .ai-recommendation {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 10px;
          background: var(--bg-secondary);
          border-radius: 4px;
        }
        .rec-label {
          font-size: 12px;
          color: var(--text-muted);
        }
        .rec-value {
          font-size: 16px;
          font-weight: 700;
        }
        .ai-events {
          font-size: 11px;
        }
        .events-label {
          color: var(--text-muted);
          display: block;
          margin-bottom: 4px;
        }
        .ai-events ul {
          margin: 0;
          padding-left: 16px;
        }
        .ai-events li {
          margin-bottom: 2px;
        }
        .ai-placeholder {
          text-align: center;
          padding: 20px;
          color: var(--text-muted);
        }
        .ai-placeholder p {
          font-size: 12px;
          margin-top: 8px;
        }
        .news-section {
          flex: 1;
          display: flex;
          flex-direction: column;
        }
        .news-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 8px;
          font-size: 12px;
          font-weight: 600;
        }
        .last-update {
          display: flex;
          align-items: center;
          gap: 4px;
          font-size: 10px;
          color: var(--text-muted);
          font-weight: normal;
        }
        .news-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
          max-height: 300px;
          overflow-y: auto;
        }
        .news-item {
          padding: 10px;
          background: var(--bg-secondary);
          border-radius: 6px;
        }
        .news-item-header {
          display: flex;
          justify-content: space-between;
          margin-bottom: 4px;
        }
        .news-source {
          font-size: 10px;
          font-weight: 600;
          color: var(--accent);
        }
        .news-time {
          font-size: 10px;
          color: var(--text-muted);
        }
        .news-title {
          font-size: 12px;
          font-weight: 600;
          margin: 0 0 4px 0;
          line-height: 1.3;
        }
        .news-summary {
          font-size: 11px;
          color: var(--text-muted);
          margin: 0 0 6px 0;
          line-height: 1.4;
        }
        .news-symbols {
          display: flex;
          flex-wrap: wrap;
          gap: 4px;
        }
        .symbol-tag {
          font-size: 9px;
          padding: 2px 6px;
          background: var(--bg-primary);
          border-radius: 3px;
          color: var(--text-muted);
        }
        .news-loading, .news-error {
          text-align: center;
          padding: 20px;
          font-size: 12px;
          color: var(--text-muted);
        }
        .news-error {
          color: var(--danger);
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
