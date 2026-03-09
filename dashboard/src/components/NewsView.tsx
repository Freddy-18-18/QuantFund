import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Newspaper, Brain, RefreshCw, Calendar, X, TrendingUp, TrendingDown, Minus, AlertTriangle, Clock, Globe, Activity, BarChart3, Users } from "lucide-react";

interface NewsItem {
  id: string;
  title: string;
  summary: string;
  source: string;
  published_at: string;
  symbols: string[];
  url?: string;
}

interface NewsAnalysis {
  news_id: string;
  sentiment: "BULLISH" | "BEARISH" | "NEUTRAL";
  sentiment_score: number;
  key_events: string[];
  impact_on_xauusd: string;
  trading_recommendation: string;
  risk_level: "LOW" | "MEDIUM" | "HIGH";
}

interface MarketSentiment {
  overall_sentiment: "BULLISH" | "BEARISH" | "NEUTRAL";
  sentiment_score: number;
  dominant_theme: string;
  xauusd_outlook: string;
  key_drivers: string[];
}

interface EconomicEvent {
  id: string;
  event: string;
  date: string;
  time?: string;
  country: string;
  currency: string;
  impact: "HIGH" | "MEDIUM" | "LOW";
  actual?: string;
  previous?: string;
  forecast?: string;
}

interface MarketStatus {
  is_open: boolean;
  session: string;
  market_type: string;
}

interface SocialSentiment {
  symbol: string;
  reddit_sentiment: number;
  twitter_sentiment: number;
  reddit_posts: number;
  twitter_posts: number;
}

interface Recommendation {
  period: string;
  strong_buy: number;
  buy: number;
  hold: number;
  sell: number;
  strong_sell: number;
  total: number;
  buy_percent: number;
}

const NEWS_CATEGORIES = [
  { value: "general", label: "General" },
  { value: "forex", label: "Forex" },
  { value: "crypto", label: "Crypto" },
  { value: "merger", label: "M&A" },
  { value: "stock", label: "Stocks" },
];

export function NewsView() {
  const [news, setNews] = useState<NewsItem[]>([]);
  const [analysis, setAnalysis] = useState<Record<string, NewsAnalysis>>({});
  const [sentiment, setSentiment] = useState<MarketSentiment | null>(null);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState("forex");
  const [selectedNews, setSelectedNews] = useState<NewsItem | null>(null);
  const [selectedAnalysis, setSelectedAnalysis] = useState<NewsAnalysis | null>(null);
  
  const [economicEvents, setEconomicEvents] = useState<EconomicEvent[]>([]);
  const [marketStatus, setMarketStatus] = useState<MarketStatus | null>(null);
  const [socialSentiment, setSocialSentiment] = useState<SocialSentiment | null>(null);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [activeTab, setActiveTab] = useState<"news" | "economic" | "sentiment">("news");

  const fetchNews = async () => {
    setLoading(true);
    try {
      const result = await invoke<NewsItem[]>("finnhub_get_market_news", {
        category: selectedCategory,
      });
      setNews(result);
    } catch (error) {
      console.error("Error fetching news:", error);
      try {
        const fallback = await invoke<NewsItem[]>("fetch_financial_news");
        setNews(fallback);
      } catch (fallbackError) {
        console.error("Fallback also failed:", fallbackError);
      }
    } finally {
      setLoading(false);
    }
  };

  const fetchEconomicCalendar = async () => {
    try {
      const events = await invoke<EconomicEvent[]>("finnhub_get_economic_calendar", {
        from: null,
        to: null,
      });
      setEconomicEvents(events);
    } catch (error) {
      console.error("Error fetching economic calendar:", error);
    }
  };

  const fetchMarketStatus = async () => {
    try {
      const status = await invoke<MarketStatus>("finnhub_get_market_status");
      setMarketStatus(status);
    } catch (error) {
      console.error("Error fetching market status:", error);
    }
  };

  const fetchSocialSentiment = async () => {
    try {
      const sentiment = await invoke<SocialSentiment>("finnhub_get_social_sentiment", {
        symbol: "GOLD",
      });
      setSocialSentiment(sentiment);
    } catch (error) {
      console.error("Error fetching social sentiment:", error);
    }
  };

  const fetchRecommendations = async () => {
    try {
      const recs = await invoke<Recommendation[]>("finnhub_get_recommendations", {
        symbol: "AAPL",
      });
      setRecommendations(recs);
    } catch (error) {
      console.error("Error fetching recommendations:", error);
    }
  };

  const fetchSentiment = async () => {
    try {
      const result = await invoke<MarketSentiment>("get_market_sentiment");
      setSentiment(result);
    } catch (error) {
      console.error("Error fetching sentiment:", error);
    }
  };

  const analyzeNews = async (newsItem: NewsItem) => {
    setAnalyzing(true);
    try {
      const result = await invoke<NewsAnalysis>("analyze_news_with_ai", {
        newsItems: [newsItem],
      });
      setAnalysis((prev) => ({ ...prev, [newsItem.id]: result }));
      setSelectedAnalysis(result);
    } catch (error) {
      console.error("Error analyzing news:", error);
    } finally {
      setAnalyzing(false);
    }
  };

  const handleNewsClick = async (newsItem: NewsItem) => {
    setSelectedNews(newsItem);
    if (analysis[newsItem.id]) {
      setSelectedAnalysis(analysis[newsItem.id]);
    } else {
      setSelectedAnalysis(null);
      await analyzeNews(newsItem);
    }
  };

  useEffect(() => {
    fetchNews();
    fetchSentiment();
    fetchMarketStatus();
  }, [selectedCategory]);

  useEffect(() => {
    if (activeTab === "economic") {
      fetchEconomicCalendar();
    } else if (activeTab === "sentiment") {
      fetchSocialSentiment();
      fetchRecommendations();
    }
  }, [activeTab]);

  const filteredNews = news;

  const getSentimentColor = (sent: string) => {
    switch (sent) {
      case "BULLISH": return "var(--accent-green)";
      case "BEARISH": return "var(--accent-red)";
      default: return "var(--text-secondary)";
    }
  };

  const getSentimentIcon = (sent: string) => {
    switch (sent) {
      case "BULLISH": return <TrendingUp size={16} />;
      case "BEARISH": return <TrendingDown size={16} />;
      default: return <Minus size={16} />;
    }
  };

  const getRiskColor = (risk: string) => {
    switch (risk) {
      case "LOW": return "var(--accent-green)";
      case "MEDIUM": return "var(--accent-yellow)";
      case "HIGH": return "var(--accent-red)";
      default: return "var(--text-secondary)";
    }
  };

  const getImpactColor = (impact: string) => {
    switch (impact) {
      case "HIGH": return "var(--accent-red)";
      case "MEDIUM": return "var(--accent-yellow)";
      default: return "var(--text-secondary)";
    }
  };

  const formatTime = (dateStr: string) => {
    if (!dateStr || dateStr === "N/A") return "N/A";
    const date = new Date(dateStr);
    const now = new Date();
    const diff = Math.floor((now.getTime() - date.getTime()) / 1000 / 60);
    if (diff < 60) return `${diff}m ago`;
    if (diff < 1440) return `${Math.floor(diff / 60)}h ago`;
    return `${Math.floor(diff / 1440)}d ago`;
  };

  return (
    <div className="news-view">
      <div className="view-header">
        <h2><Newspaper size={24} style={{ marginRight: "0.5rem", verticalAlign: "middle" }} />Noticias Finnhub</h2>
        <p>Datos en tiempo real del mercado financiero</p>
      </div>

      <div style={{ display: "flex", gap: "1rem", marginBottom: "1.5rem", flexWrap: "wrap", alignItems: "center" }}>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button
            onClick={() => setActiveTab("news")}
            style={{
              padding: "0.5rem 1rem",
              background: activeTab === "news" ? "var(--accent-primary)" : "var(--bg-secondary)",
              color: activeTab === "news" ? "white" : "var(--text-primary)",
              border: "none",
              borderRadius: "0.375rem",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
            }}
          >
            <Newspaper size={16} /> Noticias
          </button>
          <button
            onClick={() => setActiveTab("economic")}
            style={{
              padding: "0.5rem 1rem",
              background: activeTab === "economic" ? "var(--accent-primary)" : "var(--bg-secondary)",
              color: activeTab === "economic" ? "white" : "var(--text-primary)",
              border: "none",
              borderRadius: "0.375rem",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
            }}
          >
            <Calendar size={16} /> Calendario
          </button>
          <button
            onClick={() => setActiveTab("sentiment")}
            style={{
              padding: "0.5rem 1rem",
              background: activeTab === "sentiment" ? "var(--accent-primary)" : "var(--bg-secondary)",
              color: activeTab === "sentiment" ? "white" : "var(--text-primary)",
              border: "none",
              borderRadius: "0.375rem",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
            }}
          >
            <Activity size={16} /> Sentimiento
          </button>
        </div>

        {activeTab === "news" && (
          <>
            <select
              value={selectedCategory}
              onChange={(e) => setSelectedCategory(e.target.value)}
              style={{
                background: "var(--bg-secondary)",
                color: "var(--text-primary)",
                border: "1px solid var(--border-color)",
                borderRadius: "0.375rem",
                padding: "0.5rem 0.75rem",
                cursor: "pointer",
              }}
            >
              {NEWS_CATEGORIES.map((cat) => (
                <option key={cat.value} value={cat.value}>{cat.label}</option>
              ))}
            </select>
            <button
              onClick={() => { fetchNews(); fetchSentiment(); }}
              disabled={loading}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "0.5rem",
                background: "var(--accent-primary)",
                color: "white",
                border: "none",
                borderRadius: "0.375rem",
                padding: "0.5rem 1rem",
                cursor: loading ? "not-allowed" : "pointer",
                opacity: loading ? 0.7 : 1,
              }}
            >
              <RefreshCw size={16} className={loading ? "spin" : ""} />
              Actualizar
            </button>
          </>
        )}

        {marketStatus && (
          <div style={{
            marginLeft: "auto",
            padding: "0.5rem 1rem",
            background: marketStatus.is_open ? "rgba(34, 197, 94, 0.1)" : "rgba(239, 68, 68, 0.1)",
            borderRadius: "0.375rem",
            display: "flex",
            alignItems: "center",
            gap: "0.5rem",
          }}>
            <div style={{
              width: "8px",
              height: "8px",
              borderRadius: "50%",
              background: marketStatus.is_open ? "var(--accent-green)" : "var(--accent-red)",
            }} />
            <span style={{ fontSize: "0.875rem" }}>
              {marketStatus.is_open ? "Mercado Abierto" : "Mercado Cerrado"}
            </span>
            <span style={{ fontSize: "0.75rem", color: "var(--text-secondary)" }}>
              {marketStatus.session}
            </span>
          </div>
        )}
      </div>

      {loading && (
        <div style={{ textAlign: "center", padding: "2rem", color: "var(--text-secondary)" }}>
          <RefreshCw size={24} className="spin" />
          <p>Cargando datos de Finnhub...</p>
        </div>
      )}

      {!loading && activeTab === "news" && (
        <div className="card-grid">
          <div style={{ background: "var(--bg-secondary)", borderRadius: "0.75rem", padding: "1.5rem", gridColumn: "span 2" }}>
            <h3 style={{ marginBottom: "1rem" }}><Brain size={18} style={{ marginRight: "0.5rem" }} />Sentimiento de Mercado</h3>
            {sentiment ? (
              <div style={{ padding: "1rem", background: "var(--bg-tertiary)", borderRadius: "0.5rem", marginBottom: "1rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
                  <span style={{ fontWeight: "600" }}>Sentimiento General</span>
                  <span style={{ color: getSentimentColor(sentiment.overall_sentiment), fontWeight: "bold", display: "flex", alignItems: "center", gap: "0.25rem" }}>
                    {getSentimentIcon(sentiment.overall_sentiment)}
                    {sentiment.overall_sentiment}
                  </span>
                </div>
                <div style={{ fontSize: "0.875rem", color: "var(--text-secondary)", marginBottom: "0.75rem" }}>
                  {sentiment.dominant_theme || "N/A"}
                </div>
                <div style={{ fontSize: "0.875rem", marginBottom: "0.5rem" }}>
                  <strong>Score:</strong> {sentiment.sentiment_score?.toFixed(2) || "N/A"}/100
                </div>
                <div style={{ fontSize: "0.875rem", marginBottom: "0.5rem" }}>
                  <strong>XAUUSD:</strong> {sentiment.xauusd_outlook || "N/A"}
                </div>
                <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)" }}>
                  <strong>Drivers:</strong> {sentiment.key_drivers?.join(", ") || "N/A"}
                </div>
              </div>
            ) : (
              <div style={{ padding: "1rem", background: "var(--bg-tertiary)", borderRadius: "0.5rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.75rem" }}>
                  <span style={{ fontWeight: "600" }}>Sentimiento General</span>
                  <span style={{ color: "var(--accent-green)", fontWeight: "bold" }}>BULLISH</span>
                </div>
                <div style={{ fontSize: "0.875rem", color: "var(--text-secondary)" }}>
                  Obteniendo datos...
                </div>
              </div>
            )}
          </div>

          <div style={{ background: "var(--bg-secondary)", borderRadius: "0.75rem", padding: "1.5rem", gridColumn: "span 2" }}>
            <h3 style={{ marginBottom: "1rem" }}><Newspaper size={18} style={{ marginRight: "0.5rem" }} />Últimas Noticias</h3>
            {filteredNews.length > 0 ? (
              filteredNews.map((item, index) => (
                <div
                  key={item.id || index}
                  onClick={() => handleNewsClick(item)}
                  style={{
                    padding: "0.75rem",
                    borderBottom: "1px solid var(--border-color)",
                    cursor: "pointer",
                    background: selectedNews?.id === item.id ? "var(--bg-tertiary)" : "transparent",
                    borderRadius: "0.25rem",
                  }}
                >
                  <div style={{ fontWeight: "500", marginBottom: "0.25rem" }}>{item.title}</div>
                  <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", display: "flex", gap: "0.5rem", alignItems: "center" }}>
                    <span>{item.source}</span>
                    <span>•</span>
                    <span>{formatTime(item.published_at)}</span>
                    {item.symbols && item.symbols.length > 0 && (
                      <>
                        <span>•</span>
                        <span style={{ color: "var(--accent-primary)" }}>{item.symbols.slice(0, 3).join(", ")}</span>
                      </>
                    )}
                  </div>
                  {analysis[item.id] && (
                    <div style={{ marginTop: "0.5rem", display: "flex", gap: "0.5rem" }}>
                      <span style={{ color: getSentimentColor(analysis[item.id].sentiment), fontSize: "0.75rem", fontWeight: "bold" }}>
                        {analysis[item.id].sentiment}
                      </span>
                      <span style={{ color: getRiskColor(analysis[item.id].risk_level), fontSize: "0.75rem" }}>
                        Risk: {analysis[item.id].risk_level}
                      </span>
                    </div>
                  )}
                </div>
              ))
            ) : (
              <div style={{ padding: "1rem", color: "var(--text-secondary)", textAlign: "center" }}>
                No hay noticias disponibles
              </div>
            )}
          </div>

          <div style={{ background: "var(--bg-secondary)", borderRadius: "0.75rem", padding: "1.5rem", gridColumn: "span 2" }}>
            <h3 style={{ marginBottom: "1rem" }}><Calendar size={18} style={{ marginRight: "0.5rem" }} />Próximos Eventos Económicos</h3>
            <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginBottom: "0.5rem" }}>
              Vista previa - Click en "Calendario" para ver más
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              {economicEvents.slice(0, 3).map((event) => (
                <div
                  key={event.id}
                  style={{
                    padding: "0.75rem",
                    background: "var(--bg-tertiary)",
                    borderRadius: "0.5rem",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                >
                  <div>
                    <div style={{ fontWeight: "500", marginBottom: "0.25rem", fontSize: "0.875rem" }}>{event.event}</div>
                    <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", display: "flex", alignItems: "center", gap: "0.5rem" }}>
                      <Clock size={12} /> {event.date} {event.time || ""}
                      <span style={{ color: "var(--accent-primary)" }}>{event.currency}</span>
                    </div>
                  </div>
                  <div style={{
                    fontSize: "0.75rem",
                    fontWeight: "bold",
                    color: getImpactColor(event.impact),
                    display: "flex",
                    alignItems: "center",
                    gap: "0.25rem",
                  }}>
                    {event.impact === "HIGH" && <AlertTriangle size={12} />}
                    {event.impact}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {!loading && activeTab === "economic" && (
        <div style={{ background: "var(--bg-secondary)", borderRadius: "0.75rem", padding: "1.5rem" }}>
          <h3 style={{ marginBottom: "1rem" }}><Calendar size={18} style={{ marginRight: "0.5rem" }} />Calendario Económico</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {economicEvents.length > 0 ? (
              economicEvents.map((event) => (
                <div
                  key={event.id}
                  style={{
                    padding: "1rem",
                    background: "var(--bg-tertiary)",
                    borderRadius: "0.5rem",
                    display: "grid",
                    gridTemplateColumns: "1fr 1fr 1fr 1fr",
                    gap: "1rem",
                    alignItems: "center",
                  }}
                >
                  <div>
                    <div style={{ fontWeight: "500", marginBottom: "0.25rem" }}>{event.event}</div>
                    <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", display: "flex", alignItems: "center", gap: "0.5rem" }}>
                      <Globe size={12} /> {event.country} • {event.currency}
                    </div>
                  </div>
                  <div style={{ fontSize: "0.875rem" }}>
                    <div style={{ color: "var(--text-secondary)", fontSize: "0.75rem" }}>Fecha</div>
                    <div>{event.date} {event.time || ""}</div>
                  </div>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)" }}>Anterior</div>
                    <div style={{ fontWeight: "500" }}>{event.previous || "N/A"}</div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div style={{
                      fontSize: "0.75rem",
                      fontWeight: "bold",
                      color: getImpactColor(event.impact),
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "flex-end",
                      gap: "0.25rem",
                    }}>
                      {event.impact === "HIGH" && <AlertTriangle size={12} />}
                      {event.impact}
                    </div>
                    {event.forecast && (
                      <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)" }}>
                        Forecast: {event.forecast}
                      </div>
                    )}
                  </div>
                </div>
              ))
            ) : (
              <div style={{ padding: "2rem", textAlign: "center", color: "var(--text-secondary)" }}>
                No hay eventos económicos disponibles
              </div>
            )}
          </div>
        </div>
      )}

      {!loading && activeTab === "sentiment" && (
        <div className="card-grid">
          <div style={{ background: "var(--bg-secondary)", borderRadius: "0.75rem", padding: "1.5rem" }}>
            <h3 style={{ marginBottom: "1rem" }}><Users size={18} style={{ marginRight: "0.5rem" }} />Sentimiento Social</h3>
            {socialSentiment ? (
              <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                <div style={{ padding: "1rem", background: "var(--bg-tertiary)", borderRadius: "0.5rem" }}>
                  <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginBottom: "0.5rem" }}>Reddit</div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div>
                      <div style={{ fontSize: "1.5rem", fontWeight: "bold" }}>{socialSentiment.reddit_sentiment.toFixed(2)}</div>
                      <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)" }}>Sentimiento</div>
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <div style={{ fontSize: "1.5rem", fontWeight: "bold" }}>{socialSentiment.reddit_posts.toLocaleString()}</div>
                      <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)" }}>Posts</div>
                    </div>
                  </div>
                </div>
                <div style={{ padding: "1rem", background: "var(--bg-tertiary)", borderRadius: "0.5rem" }}>
                  <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginBottom: "0.5rem" }}>Twitter</div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div>
                      <div style={{ fontSize: "1.5rem", fontWeight: "bold" }}>{socialSentiment.twitter_sentiment.toFixed(2)}</div>
                      <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)" }}>Sentimiento</div>
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <div style={{ fontSize: "1.5rem", fontWeight: "bold" }}>{socialSentiment.twitter_posts.toLocaleString()}</div>
                      <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)" }}>Posts</div>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div style={{ padding: "1rem", color: "var(--text-secondary)", textAlign: "center" }}>
                Obteniendo datos...
              </div>
            )}
          </div>

          <div style={{ background: "var(--bg-secondary)", borderRadius: "0.75rem", padding: "1.5rem", gridColumn: "span 2" }}>
            <h3 style={{ marginBottom: "1rem" }}><BarChart3 size={18} style={{ marginRight: "0.5rem" }} />Recomendaciones de Analistas</h3>
            {recommendations.length > 0 ? (
              <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                {recommendations.slice(0, 4).map((rec, index) => (
                  <div key={index} style={{ padding: "1rem", background: "var(--bg-tertiary)", borderRadius: "0.5rem" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
                      <span style={{ fontWeight: "500" }}>{rec.period}</span>
                      <span style={{ 
                        fontWeight: "bold", 
                        color: rec.buy_percent >= 50 ? "var(--accent-green)" : rec.buy_percent >= 30 ? "var(--accent-yellow)" : "var(--accent-red)" 
                      }}>
                        {rec.buy_percent.toFixed(1)}% Buy
                      </span>
                    </div>
                    <div style={{ display: "flex", gap: "0.5rem", height: "8px", borderRadius: "4px", overflow: "hidden" }}>
                      <div style={{ width: `${(rec.strong_buy / rec.total) * 100}%`, background: "#22c55e" }} />
                      <div style={{ width: `${(rec.buy / rec.total) * 100}%`, background: "#86efac" }} />
                      <div style={{ width: `${(rec.hold / rec.total) * 100}%`, background: "#f59e0b" }} />
                      <div style={{ width: `${(rec.sell / rec.total) * 100}%`, background: "#f87171" }} />
                      <div style={{ width: `${(rec.strong_sell / rec.total) * 100}%`, background: "#ef4444" }} />
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", marginTop: "0.5rem", fontSize: "0.7rem", color: "var(--text-secondary)" }}>
                      <span>SB: {rec.strong_buy}</span>
                      <span>B: {rec.buy}</span>
                      <span>H: {rec.hold}</span>
                      <span>S: {rec.sell}</span>
                      <span>SS: {rec.strong_sell}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ padding: "1rem", color: "var(--text-secondary)", textAlign: "center" }}>
                Obteniendo recomendaciones...
              </div>
            )}
          </div>
        </div>
      )}

      {selectedNews && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0,0,0,0.8)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
          onClick={() => setSelectedNews(null)}
        >
          <div
            style={{
              background: "var(--bg-secondary)",
              borderRadius: "0.75rem",
              padding: "1.5rem",
              maxWidth: "600px",
              width: "90%",
              maxHeight: "80vh",
              overflow: "auto",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1rem" }}>
              <h3 style={{ margin: 0, flex: 1 }}>{selectedNews.title}</h3>
              <button
                onClick={() => setSelectedNews(null)}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "var(--text-secondary)",
                  cursor: "pointer",
                  padding: "0.25rem",
                }}
              >
                <X size={20} />
              </button>
            </div>
            <div style={{ fontSize: "0.875rem", color: "var(--text-secondary)", marginBottom: "1rem", display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <span>{selectedNews.source}</span>
              <span>•</span>
              <span>{selectedNews.published_at}</span>
              {selectedNews.symbols && selectedNews.symbols.length > 0 && (
                <>
                  <span>•</span>
                  <span style={{ color: "var(--accent-primary)" }}>{selectedNews.symbols.join(", ")}</span>
                </>
              )}
            </div>
            <div style={{ marginBottom: "1.5rem", lineHeight: "1.6" }}>
              {selectedNews.summary}
            </div>

            {analyzing && (
              <div style={{ textAlign: "center", padding: "1rem", color: "var(--text-secondary)" }}>
                <RefreshCw size={24} className="spin" />
                <p>Analizando con IA...</p>
              </div>
            )}

            {selectedAnalysis && !analyzing && (
              <div style={{ padding: "1rem", background: "var(--bg-tertiary)", borderRadius: "0.5rem" }}>
                <h4 style={{ marginBottom: "1rem", display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <Brain size={16} /> Análisis IA
                </h4>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginBottom: "1rem" }}>
                  <div>
                    <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginBottom: "0.25rem" }}>Sentimiento</div>
                    <div style={{ color: getSentimentColor(selectedAnalysis.sentiment), fontWeight: "bold", display: "flex", alignItems: "center", gap: "0.25rem" }}>
                      {getSentimentIcon(selectedAnalysis.sentiment)}
                      {selectedAnalysis.sentiment}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginBottom: "0.25rem" }}>Score</div>
                    <div style={{ fontWeight: "bold" }}>{selectedAnalysis.sentiment_score.toFixed(2)}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginBottom: "0.25rem" }}>Nivel de Riesgo</div>
                    <div style={{ color: getRiskColor(selectedAnalysis.risk_level), fontWeight: "bold" }}>{selectedAnalysis.risk_level}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginBottom: "0.25rem" }}>Impacto XAUUSD</div>
                    <div style={{ fontWeight: "bold" }}>{selectedAnalysis.impact_on_xauusd}</div>
                  </div>
                </div>
                <div style={{ marginBottom: "1rem" }}>
                  <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginBottom: "0.5rem" }}>Eventos Clave</div>
                  <ul style={{ margin: 0, paddingLeft: "1.25rem", fontSize: "0.875rem" }}>
                    {selectedAnalysis.key_events.map((event, i) => (
                      <li key={i}>{event}</li>
                    ))}
                  </ul>
                </div>
                <div style={{ padding: "0.75rem", background: "var(--bg-secondary)", borderRadius: "0.375rem" }}>
                  <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginBottom: "0.25rem" }}>Recomendación de Trading</div>
                  <div style={{ fontWeight: "600" }}>{selectedAnalysis.trading_recommendation}</div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <style>{`
        .spin {
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

export default NewsView;
