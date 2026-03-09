import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { invoke } from "@tauri-apps/api/core";
import { 
  Search, 
  RefreshCw, 
  BarChart3,
  Loader2,
  Info,
  Layers,
  ArrowUpRight,
  ArrowDownRight,
  Activity,
  Zap,
  Folder,
  Plus,
  Calendar,
  Building2,
  Tag,
  LayoutGrid,
  ArrowLeft,
  ExternalLink,
  Map as MapIcon,
  Clock,
  TrendingUp,
  Table,
  Database,
  CloudDownload
} from "lucide-react";
import { 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer,
  Area,
  AreaChart,
  Brush,
  ReferenceLine,
  LineChart,
  Line,
  BarChart,
  Bar
} from "recharts";

import { MacroChart } from "./MacroChart";
import { DataContextCard } from "./DataContextCard";
import { CorrelationHeatmap } from "./CorrelationHeatmap";

export type DataSource = "fred" | "imf" | "worldbank";
type FredMode = "categories" | "releases" | "sources" | "tags" | "maps";
type ChartStyle = "area" | "line" | "bar";

interface SeriesPoint {
  date: string;
  value: number;
}

interface AnalyzedSeries {
  id: string;
  title: string;
  data: SeriesPoint[];
  stats: {
    min: number;
    max: number;
    mean: number;
    current_value: number;
    z_score_current: number;
    percentile_current: number;
  };
  transformations: {
    yoy_change: SeriesPoint[];
    mom_change: SeriesPoint[];
  };
}

interface CorrelationMatrix {
  series_ids: string[];
  matrix: number[][];
}

interface MacroObservation {
  date: string;
  value: number;
}

interface FredCategory {
  id: number;
  name: string;
}

interface FredSeriesInfo {
  id: string;
  title: string;
}

interface FredRelease {
  id: number;
  name: string;
  realtime_start: string;
}

interface FredSource {
  id: number;
  name: string;
  link?: string;
}

interface FredTag {
  name: string;
  series_count: number;
  popularity: number;
}

interface MacroDataPanelProps {
  activeSource: DataSource;
  onSourceChange: (source: DataSource) => void;
}

export function MacroDataPanel({ activeSource }: MacroDataPanelProps) {
  // --- UI STATES ---
  const [loading, setLoading] = useState(false);
  const [explorerLoading, setExplorerLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chartStyle, setChartStyle] = useState<ChartStyle>("area");
  const [timePeriod, setTimePeriod] = useState<string>("5Y");
  const [fredMode, setFredMode] = useState<FredMode>("categories");
  const [aiAnalyzing, setAiAnalyzing] = useState(false);
  const [corrLoading, setCorrLoading] = useState(false);

  // --- DATABASE SYNC STATE ---
  const [dbStatus, setDbStatus] = useState<{
    initialized: boolean;
    lastSync: string | null;
    needsUpdate: boolean;
  }>({ initialized: false, lastSync: null, needsUpdate: false });

  // --- DATA STATES ---
  const [observations, setObservations] = useState<MacroObservation[]>([]);
  const [analyzedData, setAnalyzedData] = useState<AnalyzedSeries | null>(null);
  const [correlationMatrix, setCorrelationMatrix] = useState<CorrelationMatrix | null>(null);
  const [metadata, setMetadata] = useState<{
    title: string, 
    units: string, 
    notes: string, 
    last_updated?: string, 
    frequency?: string,
    id?: string
  } | null>(null);
  
  const [seriesCategories, setSeriesCategories] = useState<FredCategory[]>([]);
  const [seriesRelease, setSeriesRelease] = useState<FredRelease | null>(null);
  const [vintageDates, setVintageDates] = useState<string[]>([]);

  // --- SELECTION STATES ---
  const [selectedFred, setSelectedFred] = useState("FEDFUNDS");
  const [selectedImf, setSelectedImf] = useState("PGold");
  const [selectedWb, setSelectedWb] = useState("NY.GDP.MKTP.CD");
  const [selectedCountry, setSelectedCountry] = useState("USA");

  // --- EXPLORER DATA ---
  const [categoryPath, setCategoryPath] = useState<FredCategory[]>([]);
  const [selectedRelease, setSelectedRelease] = useState<FredRelease | null>(null);
  const [selectedSource, setSelectedSource] = useState<FredSource | null>(null);
  const [selectedTag, setSelectedTag] = useState<FredTag | null>(null);
  
  const [explorerItems, setExplorerItems] = useState<{
    categories: FredCategory[], 
    series: FredSeriesInfo[],
    releases: FredRelease[],
    sources: FredSource[],
    tags: FredTag[]
  }>({
    categories: [], 
    series: [], 
    releases: [], 
    sources: [], 
    tags: []
  });

  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<FredSeriesInfo[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);

  const lastLoadedRef = useRef<string>("");

  const timePeriods = [
    { value: "1Y", label: "1A" },
    { value: "5Y", label: "5A" },
    { value: "10Y", label: "10A" },
    { value: "ALL", label: "MAX" },
  ];

  const fredCatalog = {
    "Regional / Mapas": [
      { id: "ALUR", name: "Unemployment AL", desc: "Desempleo en Alabama." },
      { id: "NYUR", name: "Unemployment NY", desc: "Desempleo en New York." },
      { id: "TXUR", name: "Unemployment TX", desc: "Desempleo en Texas." },
      { id: "CAUR", name: "Unemployment CA", desc: "Desempleo en California." },
    ],
    "Tasas e Interés": [
      { id: "FEDFUNDS", name: "Fed Funds Rate", desc: "Tasa base de la FED." },
      { id: "DGS10", name: "10Y Treasury", desc: "Bono a 10 años." },
      { id: "T10Y2Y", name: "Yield Curve", desc: "Spread 10Y-2Y." }
    ]
  };

  const handleAiDeepAnalysis = async () => {
    if (!analyzedData) return;
    setAiAnalyzing(true);
    
    try {
      const analysisContext = `
      FICHA TÉCNICA INSTITUCIONAL:
      Serie: ${analyzedData.title} (${analyzedData.id})
      Valor Actual: ${analyzedData.stats.current_value}
      Percentil Histórico: ${analyzedData.stats.percentile_current.toFixed(1)}%
      Z-Score (Desviación): ${analyzedData.stats.z_score_current.toFixed(2)}
      Cambio 12 Periodos (YoY): ${analyzedData.transformations.yoy_change.slice(-1)[0]?.value.toFixed(2)}%
      Rango Histórico: ${analyzedData.stats.min} - ${analyzedData.stats.max}
      Promedio Largo Plazo: ${analyzedData.stats.mean.toFixed(2)}
      `;

      const aiResponse = await invoke<any>("analyze_news_with_ai", { 
        newsItems: [{
          id: "analysis-request",
          title: `ANÁLISIS MACRO: ${analyzedData.title}`,
          summary: analysisContext,
          source: "QuantFund Macro Engine (Rust)",
          url: "",
          published_at: new Date().toISOString(),
          symbols: [analyzedData.id],
          sentiment: null
        }]
      });

      alert(`ANÁLISIS PROFESIONAL:\n\n${aiResponse.summary}\n\nRECOMENDACIÓN: ${aiResponse.trading_recommendation}\nNIVEL DE RIESGO: ${aiResponse.risk_level}`);
    } catch (err) {
      console.error("AI Analysis error:", err);
    } finally {
      setAiAnalyzing(false);
    }
  };

  const calculateCorrelation = async () => {
    if (!selectedFred) return;
    setCorrLoading(true);
    try {
      // Comparamos el activo seleccionado con benchmarks clave
      const seriesToCompare = [
        selectedFred,
        "DGS10", // 10Y Yield
        "DTWEXBGS", // Dollar Index
        "GOLDAMGBD228NLBM", // Gold
        "SP500", // S&P 500
        "UNRATE" // Unemployment
      ];
      
      const matrix = await invoke<CorrelationMatrix>("fred_get_correlation_matrix", { 
        seriesIds: seriesToCompare 
      });
      setCorrelationMatrix(matrix);
    } catch (err) {
      console.error("Correlation error:", err);
    } finally {
      setCorrLoading(false);
    }
  };

  const initDatabase = async () => {
    try {
      await invoke("fred_persistence_init");
      setDbStatus(prev => ({ ...prev, initialized: true }));
    } catch (err) {
      console.error("DB Init error:", err);
    }
  };

  const syncSeries = async (seriesId: string) => {
    try {
      setLoading(true);
      const apiKey = "YOUR_API_KEY";
      const result = await invoke("fred_sync_series", { seriesId, apiKey });
      setDbStatus(prev => ({ 
        ...prev, 
        lastSync: new Date().toISOString(),
        needsUpdate: false 
      }));
      return result;
    } catch (err) {
      console.error("Sync error:", err);
    } finally {
      setLoading(false);
    }
  };

  // --- CORE LOAD FUNCTION ---
  const loadActiveData = useCallback(async () => {
    setLoading(true);
    setError(null);
    setCorrelationMatrix(null);
    try {
      let startDate = "1970-01-01";
      if (timePeriod === "1Y") startDate = new Date(new Date().setFullYear(new Date().getFullYear() - 1)).toISOString().split("T")[0];
      else if (timePeriod === "5Y") startDate = new Date(new Date().setFullYear(new Date().getFullYear() - 5)).toISOString().split("T")[0];
      else if (timePeriod === "10Y") startDate = new Date(new Date().setFullYear(new Date().getFullYear() - 10)).toISOString().split("T")[0];

      let obs: MacroObservation[] = [];
      let meta = { title: "", units: "", notes: "", last_updated: "", frequency: "", id: "" };

      if (activeSource === "fred") {
        const [analysisRes, m] = await Promise.all([
          invoke<AnalyzedSeries>("fred_get_series_analysis", { seriesId: selectedFred }),
          invoke<any>("fred_get_series", { seriesId: selectedFred })
        ]);
        
        setAnalyzedData(analysisRes);
        obs = analysisRes.data;
        meta = { title: m.title, units: m.units, notes: m.notes || "Sin notas.", last_updated: m.last_updated, frequency: m.frequency, id: m.id };
        
        const [catsRes, relRes, vintageRes] = await Promise.allSettled([
          invoke<any>("fred_get_series_categories", { seriesId: selectedFred }),
          invoke<any>("fred_get_series_release", { seriesId: selectedFred }),
          invoke<any>("fred_get_series_vintagedates", { seriesId: selectedFred, limit: 10 })
        ]);
        
        setSeriesCategories(catsRes.status === "fulfilled" ? (catsRes.value.categories || []) : []);
        setSeriesRelease(relRes.status === "fulfilled" ? (relRes.value.releases?.[0] || null) : null);
        setVintageDates(vintageRes.status === "fulfilled" ? (vintageRes.value.vintage_dates || []) : []);
      }
      else if (activeSource === "imf") {
        const p = { start: startDate, end: new Date().toISOString().split("T")[0] };
        const res: any = await invoke(selectedImf === "PGold" ? "imf_get_gold_price" : selectedImf === "PSilver" ? "imf_get_silver_price" : "imf_get_oil_price", p);
        obs = (res.observations || []).map((o: any) => ({ date: o.date, value: o.value }));
        meta = { title: `FMI: ${selectedImf}`, units: "USD", notes: "Datos oficiales del Fondo Monetario Internacional.", last_updated: "", frequency: "M", id: selectedImf };
      }
      else {
        const res = await invoke<any>("wb_get_indicator_data", { params: { indicatorId: selectedWb, countryCode: selectedCountry, dateStart: startDate.split("-")[0], perPage: 100 } });
        obs = (res.data || []).map((o: any) => ({ date: o.date, value: o.value })).reverse();
        meta = { title: `Banco Mundial: ${selectedWb}`, units: "Value", notes: `Indicadores para ${selectedCountry}.`, last_updated: "", frequency: "A", id: selectedWb };
      }

      setObservations(obs.filter(o => !isNaN(o.value)));
      setMetadata(meta);
      lastLoadedRef.current = `${activeSource}-${selectedFred}-${selectedImf}-${selectedWb}-${selectedCountry}-${timePeriod}`;
    } catch (err) {
      console.error("Data load error:", err);
      setError(`Error de carga: ${err}`);
    } finally {
      setLoading(false);
    }
  }, [activeSource, selectedFred, selectedImf, selectedWb, selectedCountry, timePeriod, fredMode]);

  // --- EXPLORER FUNCTIONS ---
  
  const loadFredStructure = async (mode: FredMode, targetId: number | string = 0, isLoadMore = false) => {
    setExplorerLoading(true);
    setError(null);
    if (!isLoadMore) setIsSearching(false);

    try {
      const currentOffset = isLoadMore ? offset + 50 : 0;
      const limit = 50;

      if (mode === "categories") {
        const id = Number(targetId);
        const [catRes, serRes] = await Promise.allSettled([
          id === 0 ? invoke<any>("fred_get_categories") : invoke<any>("fred_get_category_children", { categoryId: id }),
          invoke<any>("fred_get_category_series", { categoryId: id, limit, offset: currentOffset })
        ]);

        let cats = catRes.status === "fulfilled" ? (catRes.value.categories || []) : [];
        const sers = serRes.status === "fulfilled" ? (serRes.value.seriess || serRes.value.series || []) : [];
        const totalCount = serRes.status === "fulfilled" ? (serRes.value.count || 0) : 0;

        if (id === 0 && cats.length === 0) {
          cats = [
            { id: 32991, name: "Money, Banking, & Finance" },
            { id: 10, name: "Population, Employment, & Labor Markets" },
            { id: 32992, name: "National Accounts" },
            { id: 1, name: "Production & Business Activity" },
            { id: 32455, name: "Prices" },
            { id: 32263, name: "International Data" }
          ];
        }

        setExplorerItems(prev => ({
          ...prev,
          categories: isLoadMore ? prev.categories : cats,
          series: isLoadMore ? [...prev.series, ...sers] : sers
        }));
        setHasMore(sers.length === limit && (currentOffset + limit) < totalCount);
        
        if (!isLoadMore) {
          if (id === 0) setCategoryPath([]);
          else {
            const name = cats.length > 0 ? "Folder" : (explorerItems.categories.find(c => c.id === id)?.name || "Folder");
            setCategoryPath(prev => {
              const idx = prev.findIndex(c => c.id === id);
              return idx !== -1 ? prev.slice(0, idx + 1) : [...prev, { id, name }];
            });
          }
        }
      } 
      else if (mode === "releases") {
        if (targetId !== 0) {
          const id = Number(targetId);
          const res = await invoke<any>("fred_get_release_series", { releaseId: id, limit, offset: currentOffset });
          const sers = res.seriess || res.series || [];
          setExplorerItems(prev => ({ ...prev, series: isLoadMore ? [...prev.series, ...sers] : sers, releases: isLoadMore ? prev.releases : [] }));
          setHasMore(sers.length === limit);
          if (!isLoadMore) {
            const rel = explorerItems.releases.find(r => r.id === id);
            if (rel) setSelectedRelease(rel);
          }
        } else {
          const res = await invoke<any>("fred_get_releases", { limit, offset: currentOffset });
          const data = res.releases || [];
          setExplorerItems(prev => ({ ...prev, releases: isLoadMore ? [...prev.releases, ...data] : data, series: [] }));
          setHasMore(data.length === limit);
          setSelectedRelease(null);
        }
      }
      else if (mode === "sources") {
        if (targetId !== 0) {
          const id = Number(targetId);
          const res = await invoke<any>("fred_get_source_releases", { sourceId: id, limit, offset: currentOffset });
          const rels = res.releases || [];
          setExplorerItems(prev => ({ ...prev, releases: isLoadMore ? [...prev.releases, ...rels] : rels, sources: isLoadMore ? prev.sources : [] }));
          setHasMore(rels.length === limit);
          if (!isLoadMore) {
            const src = explorerItems.sources.find(s => s.id === id);
            if (src) setSelectedSource(src);
          }
        } else {
          const res = await invoke<any>("fred_get_sources", { limit, offset: currentOffset });
          const data = res.sources || [];
          setExplorerItems(prev => ({ ...prev, sources: isLoadMore ? [...prev.sources, ...data] : data, releases: [], series: [] }));
          setHasMore(data.length === limit);
          setSelectedSource(null);
        }
      }
      else if (mode === "tags") {
        if (targetId !== 0) {
          const tagName = String(targetId);
          const res = await invoke<any>("fred_get_tag_series", { tagNames: tagName, limit, offset: currentOffset });
          const sers = res.seriess || res.series || [];
          setExplorerItems(prev => ({ ...prev, series: isLoadMore ? [...prev.series, ...sers] : sers, tags: isLoadMore ? prev.tags : [] }));
          setHasMore(sers.length === limit);
          if (!isLoadMore) {
            const tag = explorerItems.tags.find(t => t.name === tagName);
            if (tag) setSelectedTag(tag);
          }
        } else {
          const res = await invoke<any>("fred_get_tags", { limit, offset: currentOffset });
          const data = res.tags || [];
          setExplorerItems(prev => ({ ...prev, tags: isLoadMore ? [...prev.tags, ...data] : data, series: [] }));
          setHasMore(data.length === limit);
          setSelectedTag(null);
        }
      }
      else if (mode === "maps") {
        const res = await invoke<any>("fred_search_series", { params: { query: "state unemployment", limit: 50, offset: currentOffset } });
        const sers = res.seriess || res.series || [];
        setExplorerItems(prev => ({ ...prev, series: isLoadMore ? [...prev.series, ...sers] : sers }));
        setHasMore(sers.length === 50);
      }

      setOffset(currentOffset);
    } catch (err: any) {
      setError(`Error FRED: ${err.message || err}`);
    } finally {
      setExplorerLoading(false);
    }
  };

  const handleFredModeChange = (mode: FredMode) => {
    setFredMode(mode);
    setOffset(0);
    setCategoryPath([]);
    setSelectedRelease(null);
    setSelectedSource(null);
    setSelectedTag(null);
    loadFredStructure(mode, 0);
  };

  const runFredSearch = async () => {
    if (!searchQuery.trim()) return;
    setExplorerLoading(true);
    setIsSearching(true);
    setError(null);
    try {
      const result = await invoke<any>("fred_search_series", { params: { query: searchQuery, limit: 100 } });
      setSearchResults(result.seriess || result.series || []);
    } catch (err) {
      setError(`Error búsqueda: ${err}`);
    } finally { setExplorerLoading(false); }
  };

  // --- EFFECTS ---
  useEffect(() => {
    const key = `${activeSource}-${selectedFred}-${selectedImf}-${selectedWb}-${selectedCountry}-${timePeriod}`;
    if (lastLoadedRef.current !== key) loadActiveData();
  }, [loadActiveData, activeSource, selectedFred, selectedImf, selectedWb, selectedCountry, timePeriod]);

  useEffect(() => { 
    if (activeSource === "fred") loadFredStructure("categories", 0); 
  }, [activeSource]);

  const stats = useMemo(() => {
    if (observations.length < 2) return null;
    const vals = observations.map(o => o.value);
    const curr = vals[vals.length - 1];
    const prev = vals[vals.length - 2];
    return { 
      curr, 
      pct: ((curr - prev) / Math.abs(prev)) * 100, 
      max: Math.max(...vals), 
      min: Math.min(...vals), 
      avg: vals.reduce((a,b) => a+b, 0) / vals.length, 
      count: observations.length 
    };
  }, [observations]);

  return (
    <div className="macro-terminal" style={{ display: "grid", gridTemplateColumns: "350px 1fr", height: "100%", background: "#0a0e17", color: "#e4e7eb", overflow: "hidden" }}>
      
      {/* SIDEBAR: EXPLORADOR MULTIMODAL */}
      <div style={{ background: "#0d1117", borderRight: "1px solid #30363d", display: "flex", flexDirection: "column", overflow: "hidden" }}>
        
        {/* Fred Navigation Tabs */}
        {activeSource === "fred" && (
          <div style={{ display: "flex", background: "#161b22", padding: "0.5rem", gap: "0.25rem", borderBottom: "1px solid #30363d" }}>
            {[
              { id: "categories", icon: <LayoutGrid size={14}/>, label: "Explorar" },
              { id: "releases", icon: <Calendar size={14}/>, label: "Releases" },
              { id: "sources", icon: <Building2 size={14}/>, label: "Fuentes" },
              { id: "tags", icon: <Tag size={14}/>, label: "Tags" },
              { id: "maps", icon: <MapIcon size={14}/>, label: "Mapas" }
            ].map(tab => (
              <button 
                key={tab.id}
                onClick={() => handleFredModeChange(tab.id as FredMode)}
                style={{ 
                  flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: "0.3rem",
                  padding: "0.5rem 0", borderRadius: "0.4rem", border: "none",
                  background: fredMode === tab.id ? "#30363d" : "transparent",
                  color: fredMode === tab.id ? "#58a6ff" : "#8b949e",
                  cursor: "pointer", transition: "all 0.2s"
                }}
              >
                {tab.icon}
                <span style={{ fontSize: "0.6rem", fontWeight: 700 }}>{tab.label}</span>
              </button>
            ))}
          </div>
        )}

        {/* Database Init Button */}
        {!dbStatus.initialized && (
          <div style={{ padding: "0.75rem", borderBottom: "1px solid #30363d" }}>
            <button 
              onClick={initDatabase}
              style={{ 
                width: "100%", padding: "0.75rem", borderRadius: "0.5rem", border: "1px solid #30363d",
                background: "#238636", color: "white", fontWeight: 700, fontSize: "0.75rem",
                cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: "0.5rem"
              }}
            >
              <Database size={14} /> Initialize Database
            </button>
          </div>
        )}

        {/* Database Sync Status */}
        {dbStatus.initialized && (
          <div style={{ padding: "0.5rem 0.75rem", borderBottom: "1px solid #30363d", display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.65rem", color: "#3fb950" }}>
            <div style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#3fb950" }} />
            DB Connected
            {dbStatus.lastSync && (
              <span style={{ color: "#8b949e", marginLeft: "auto" }}>
                Last sync: {new Date(dbStatus.lastSync).toLocaleTimeString()}
              </span>
            )}
          </div>
        )}

        <div style={{ flex: 1, overflowY: "auto", padding: "0.75rem", display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          {activeSource === "fred" ? (
            <>
              <div style={{ padding: "0.25rem 0 0.75rem 0" }}>
                <div style={{ position: "relative" }}>
                  <Search size={14} style={{ position: "absolute", left: "0.6rem", top: "50%", transform: "translateY(-50%)", opacity: 0.5 }} />
                  <input 
                    type="text" placeholder={`Buscar en ${fredMode}...`} value={searchQuery} 
                    onChange={(e) => setSearchQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && runFredSearch()} 
                    style={{ width: "100%", padding: "0.5rem 0.5rem 0.5rem 2rem", background: "#161b22", border: "1px solid #30363d", borderRadius: "0.4rem", color: "white", fontSize: "0.8rem" }} 
                  />
                </div>
              </div>

              {(categoryPath.length > 0 || selectedRelease || selectedSource || selectedTag) && !isSearching && (
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", padding: "0.25rem", marginBottom: "0.5rem" }}>
                  <button 
                    onClick={() => {
                      if (fredMode === "categories") {
                        if (categoryPath.length > 1) loadFredStructure("categories", categoryPath[categoryPath.length-2].id);
                        else loadFredStructure("categories", 0);
                      } else if (fredMode === "releases") {
                        loadFredStructure("releases", 0);
                      } else if (fredMode === "sources") {
                        loadFredStructure("sources", 0);
                      } else if (fredMode === "tags") {
                        loadFredStructure("tags", 0);
                      }
                    }} 
                    style={{ background: "#161b22", border: "1px solid #30363d", color: "#8b949e", padding: "0.3rem 0.6rem", borderRadius: "0.3rem", fontSize: "0.7rem", cursor: "pointer" }}
                  >
                    <ArrowLeft size={12} />
                  </button>
                  <div style={{ flex: 1, fontSize: "0.7rem", color: "#58a6ff", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {fredMode === "categories" ? (
                      <>
                        <span onClick={() => loadFredStructure("categories", 0)} style={{ cursor: "pointer" }}>Root</span>
                        {categoryPath.map((c) => (
                          <span key={c.id}> / <span onClick={() => loadFredStructure("categories", c.id)} style={{ cursor: "pointer" }}>{c.name}</span></span>
                        ))}
                      </>
                    ) : (
                      <span>{selectedRelease?.name || selectedSource?.name || selectedTag?.name}</span>
                    )}
                  </div>
                </div>
              )}
              
              {explorerLoading && !explorerItems.series.length && !explorerItems.releases.length && !explorerItems.sources.length && !explorerItems.tags.length ? 
                <div style={{ textAlign: "center", padding: "2rem" }}><Loader2 size={24} className="spinning" color="#58a6ff" /></div> :
               isSearching ? (
                 <div>
                   <h4 style={{ fontSize: "0.7rem", color: "#8b949e", textTransform: "uppercase", padding: "0.5rem", display: "flex", justifyContent: "space-between" }}>RESULTADOS <span onClick={() => setIsSearching(false)} style={{ cursor: "pointer", color: "#58a6ff" }}>VOLVER</span></h4>
                   <div style={{ display: "flex", flexDirection: "column", gap: "0.2rem" }}>
                    {searchResults.length > 0 ? searchResults.map(s => <div key={s.id} onClick={() => setSelectedFred(s.id)} style={{ padding: "0.6rem", borderRadius: "0.3rem", cursor: "pointer", background: selectedFred === s.id ? "#1f6feb22" : "transparent", fontSize: "0.75rem", border: `1px solid ${selectedFred === s.id ? "#1f6feb" : "transparent"}` }}>{s.title}</div>) : <div style={{ padding: "1rem", textAlign: "center" }}>No se encontraron series.</div>}
                   </div>
                 </div>
               ) : (
                 <div style={{ display: "flex", flexDirection: "column", gap: "0.2rem" }}>
                   {error && <div style={{ padding: "0.5rem", color: "#f85149", fontSize: "0.7rem", background: "rgba(248,81,73,0.1)", borderRadius: "0.3rem" }}>{error}</div>}
                   
                   {fredMode === "categories" && (
                     <>
                       {explorerItems.categories.map(c => <div key={c.id} onClick={() => loadFredStructure("categories", c.id)} style={{ display: "flex", alignItems: "center", gap: "0.5rem", padding: "0.5rem", cursor: "pointer", fontSize: "0.75rem", borderRadius: "0.3rem" }} className="explorer-item"><Folder size={12} color="#fbbf24" /> {c.name}</div>)}
                       {explorerItems.series.map(s => <div key={s.id} onClick={() => setSelectedFred(s.id)} style={{ padding: "0.5rem", borderRadius: "0.3rem", cursor: "pointer", background: selectedFred === s.id ? "#1f6feb22" : "transparent", fontSize: "0.75rem", border: `1px solid ${selectedFred === s.id ? "#1f6feb" : "transparent"}` }}>{s.title}</div>)}
                     </>
                   )}

                   {fredMode === "releases" && (
                     <>
                       {explorerItems.releases.length > 0 ? explorerItems.releases.map(r => (
                         <div key={r.id} onClick={() => loadFredStructure("releases", r.id)} style={{ padding: "0.6rem", borderRadius: "0.3rem", cursor: "pointer", fontSize: "0.75rem", border: "1px solid #30363d" }} className="explorer-item">
                           <div style={{ fontWeight: 700, color: "#58a6ff" }}>{r.name}</div>
                           <div style={{ fontSize: "0.65rem", color: "#8b949e", marginTop: "0.2rem" }}>Lanzamiento: {r.realtime_start}</div>
                         </div>
                       )) : (
                         explorerItems.series.map(s => <div key={s.id} onClick={() => setSelectedFred(s.id)} style={{ padding: "0.5rem", borderRadius: "0.3rem", cursor: "pointer", background: selectedFred === s.id ? "#1f6feb22" : "transparent", fontSize: "0.75rem", border: `1px solid ${selectedFred === s.id ? "#1f6feb" : "transparent"}` }}>{s.title}</div>)
                       )}
                     </>
                   )}

                   {fredMode === "sources" && (
                     <>
                       {explorerItems.sources.length > 0 ? explorerItems.sources.map(src => (
                         <div key={src.id} onClick={() => loadFredStructure("sources", src.id)} style={{ padding: "0.6rem", borderRadius: "0.3rem", cursor: "pointer", fontSize: "0.75rem", border: "1px solid #30363d" }} className="explorer-item">
                           <div style={{ fontWeight: 700 }}>{src.name}</div>
                           <div style={{ fontSize: "0.65rem", color: "#8b949e" }}>ID: {src.id}</div>
                         </div>
                       )) : (
                         explorerItems.releases.map(r => (
                           <div key={r.id} onClick={() => loadFredStructure("releases", r.id)} style={{ padding: "0.6rem", borderRadius: "0.3rem", cursor: "pointer", fontSize: "0.75rem", border: "1px solid #30363d" }} className="explorer-item">
                             <div style={{ fontWeight: 700, color: "#58a6ff" }}>{r.name}</div>
                             <div style={{ fontSize: "0.65rem", color: "#8b949e", marginTop: "0.2rem" }}>Lanzamiento: {r.realtime_start}</div>
                           </div>
                         ))
                       )}
                     </>
                   )}

                   {fredMode === "tags" && (
                     <>
                       {explorerItems.tags.length > 0 ? explorerItems.tags.map(t => (
                         <div key={t.name} onClick={() => loadFredStructure("tags", t.name)} style={{ padding: "0.5rem", borderRadius: "0.3rem", cursor: "pointer", fontSize: "0.75rem", border: "1px solid #30363d", display: "flex", justifyContent: "space-between" }} className="explorer-item">
                           <span>{t.name}</span>
                           <span style={{ color: "#58a6ff", fontSize: "0.6rem" }}>{t.series_count}</span>
                         </div>
                       )) : (
                         explorerItems.series.map(s => <div key={s.id} onClick={() => setSelectedFred(s.id)} style={{ padding: "0.5rem", borderRadius: "0.3rem", cursor: "pointer", background: selectedFred === s.id ? "#1f6feb22" : "transparent", fontSize: "0.75rem", border: `1px solid ${selectedFred === s.id ? "#1f6feb" : "transparent"}` }}>{s.title}</div>)
                       )}
                     </>
                   )}

                   {fredMode === "maps" && (
                     explorerItems.series.map(s => <div key={s.id} onClick={() => setSelectedFred(s.id)} style={{ padding: "0.5rem", borderRadius: "0.3rem", cursor: "pointer", background: selectedFred === s.id ? "#1f6feb22" : "transparent", fontSize: "0.75rem", border: `1px solid ${selectedFred === s.id ? "#1f6feb" : "transparent"}` }}>{s.title}</div>)
                   )}

                   {hasMore && (
                     <button 
                      onClick={() => {
                        const tid = selectedTag ? selectedTag.name : (selectedSource ? selectedSource.id : (selectedRelease ? selectedRelease.id : (categoryPath.length > 0 ? categoryPath[categoryPath.length-1].id : 0)));
                        loadFredStructure(fredMode, tid, true);
                      }}
                      style={{ width: "100%", padding: "0.6rem", marginTop: "0.5rem", background: "#161b22", border: "1px solid #30363d", borderRadius: "0.3rem", color: "#58a6ff", fontSize: "0.7rem", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: "0.5rem" }}
                     >
                       {explorerLoading ? <Loader2 size={12} className="spinning" /> : <Plus size={12} />} Cargar más
                     </button>
                   )}
                 </div>
               )}

               {fredMode === "categories" && !isSearching && categoryPath.length === 0 && (
                 <div style={{ marginTop: "1rem", borderTop: "1px solid #333", paddingTop: "1rem" }}>
                   <h4 style={{ fontSize: "0.7rem", color: "#8b949e", textTransform: "uppercase", padding: "0 0.5rem 0.5rem 0.5rem" }}>Catálogo Principal</h4>
                   {Object.entries(fredCatalog).map(([cat, items]) => (
                     <div key={cat} style={{ marginBottom: "1rem" }}>
                       <div style={{ fontSize: "0.7rem", fontWeight: 700, padding: "0.2rem 0.5rem", color: "#ccc" }}>{cat}</div>
                       {items.map(i => <div key={i.id} onClick={() => setSelectedFred(i.id)} style={{ padding: "0.4rem 1rem", fontSize: "0.75rem", cursor: "pointer", color: selectedFred === i.id ? "#58a6ff" : "#8b949e" }}>• {i.name}</div>)}
                     </div>
                   ))}
                 </div>
               )}
            </>
          ) : (
            <div style={{ padding: "0.5rem" }}>
              <select value={selectedCountry} onChange={(e) => setSelectedCountry(e.target.value)} style={{ width: "100%", padding: "0.6rem", background: "#161b22", color: "white", border: "1px solid #30363d", borderRadius: "0.4rem", marginBottom: "1rem" }}>
                <option value="USA">EE.UU.</option><option value="CHN">CHINA</option><option value="DEU">ALEMANIA</option><option value="JPN">JAPÓN</option><option value="IND">INDIA</option><option value="BRA">BRASIL</option>
              </select>
              <h4 style={{ fontSize: "0.7rem", color: "#8b949e", textTransform: "uppercase", padding: "0.5rem" }}>INDICADORES</h4>
              {activeSource === "imf" ? 
                ["PGold", "PSilver", "POilCrude", "PCopper"].map(id => <div key={id} onClick={() => setSelectedImf(id)} style={{ padding: "0.75rem", borderRadius: "0.4rem", cursor: "pointer", background: selectedImf === id ? "#1f6feb22" : "transparent", marginBottom: "0.5rem", border: `1px solid ${selectedImf === id ? "#1f6feb" : "transparent"}` }}>{id}</div>)
                :
                [{id: "NY.GDP.MKTP.CD", n: "PIB Nominal"}, {id: "FP.CPI.TOTL.ZG", n: "Inflación %"}].map(ind => <div key={ind.id} onClick={() => setSelectedWb(ind.id)} style={{ padding: "0.75rem", borderRadius: "0.4rem", cursor: "pointer", background: selectedWb === ind.id ? "#8957e522" : "transparent", marginBottom: "0.5rem", border: `1px solid ${selectedWb === ind.id ? "#8957e5" : "transparent"}` }}>{ind.n}</div>)
              }
            </div>
          )}
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", overflow: "hidden" }}>
        
        <div style={{ padding: "0.75rem 1.5rem", background: "#161b22", borderBottom: "1px solid #30363d", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
            <Activity size={18} color="#58a6ff" />
            <h2 style={{ fontSize: "0.9rem", fontWeight: 800, margin: 0 }}>TERMINAL ESTRATÉGICA MACRO</h2>
          </div>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <div style={{ display: "flex", background: "#0d1117", padding: "0.2rem", borderRadius: "0.4rem" }}>
              {timePeriods.map(p => <button key={p.value} onClick={() => setTimePeriod(p.value)} style={{ padding: "0.3rem 0.7rem", fontSize: "0.7rem", border: "none", background: timePeriod === p.value ? "#30363d" : "transparent", color: "white", cursor: "pointer", borderRadius: "0.2rem" }}>{p.label}</button>)}
            </div>
            <div style={{ width: "1px", background: "#333", height: "20px", margin: "0 0.5rem" }} />
            <button onClick={() => setChartStyle("area")} style={{ padding: "0.4rem", background: chartStyle === "area" ? "#333" : "transparent", border: "none", color: "white", cursor: "pointer" }}><Layers size={14}/></button>
            <button onClick={() => setChartStyle("line")} style={{ padding: "0.4rem", background: chartStyle === "line" ? "#333" : "transparent", border: "none", color: "white", cursor: "pointer" }}><Activity size={14}/></button>
            <button onClick={() => setChartStyle("bar")} style={{ padding: "0.4rem", background: chartStyle === "bar" ? "#333" : "transparent", border: "none", color: "white", cursor: "pointer" }}><BarChart3 size={14}/></button>
            <button onClick={loadActiveData} style={{ padding: "0.4rem", background: "transparent", border: "none", color: "#58a6ff", cursor: "pointer" }}><RefreshCw size={14} className={loading ? "spinning" : ""} /></button>
            {dbStatus.initialized && activeSource === "fred" && (
              <button 
                onClick={() => syncSeries(selectedFred)}
                disabled={loading}
                style={{ padding: "0.4rem 0.6rem", background: "transparent", border: "1px solid #30363d", color: "#3fb950", cursor: loading ? "not-allowed" : "pointer", borderRadius: "0.3rem", fontSize: "0.65rem", display: "flex", alignItems: "center", gap: "0.3rem" }}
                title="Sync to local database"
              >
                <CloudDownload size={12} /> Sync DB
              </button>
            )}
          </div>
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "1.5rem" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: "1.5rem", minHeight: "100%" }}>
            
            <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
              <div style={{ background: "#0d1117", borderRadius: "1rem", border: "1px solid #30363d", padding: "1.5rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "1.5rem" }}>
                  <div>
                    <h3 style={{ margin: 0, fontSize: "1.3rem", fontWeight: 700 }}>{metadata?.title || "Cargando..."}</h3>
                    <div style={{ display: "flex", gap: "1rem", marginTop: "0.4rem" }}>
                      <span style={{ fontSize: "0.7rem", color: "#58a6ff", fontWeight: 800 }}>{metadata?.frequency?.toUpperCase()}</span>
                      <span style={{ fontSize: "0.7rem", color: "#8b949e" }}>UNIDADES: {metadata?.units}</span>
                    </div>
                  </div>
                  {stats && (
                    <div style={{ textAlign: "right" }}>
                      <div style={{ fontSize: "2rem", fontWeight: 900, color: "#fff" }}>{stats.curr.toLocaleString()}</div>
                      <div style={{ color: stats.pct >= 0 ? "#3fb950" : "#f85149", fontWeight: 800, fontSize: "1rem" }}>
                        {stats.pct >= 0 ? "▲" : "▼"} {Math.abs(stats.pct).toFixed(2)}%
                      </div>
                    </div>
                  )}
                </div>

                <div style={{ height: 450 }}>
                  {loading ? (
                    <div style={{ height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: "1rem" }}>
                      <Loader2 className="spinning" size={40} color="#1f6feb" />
                      <span style={{ fontSize: "0.8rem", opacity: 0.5 }}>Sincronizando con terminal remota...</span>
                    </div>
                  ) : analyzedData && activeSource === "fred" ? (
                    <MacroChart series={analyzedData} />
                  ) : (
                    <ResponsiveContainer width="100%" height="100%">
                      {chartStyle === "area" ? (
                        <AreaChart data={observations}>
                          <defs><linearGradient id="c" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#1f6feb" stopOpacity={0.3}/><stop offset="95%" stopColor="#1f6feb" stopOpacity={0}/></linearGradient></defs>
                          <CartesianGrid strokeDasharray="3 3" stroke="#30363d" vertical={false} />
                          <XAxis dataKey="date" hide />
                          <YAxis stroke="#8b949e" fontSize={10} orientation="right" domain={['auto', 'auto']} tickFormatter={v => v.toLocaleString()} />
                          <Tooltip contentStyle={{ background: "#161b22", border: "1px solid #30363d", borderRadius: "0.5rem" }} />
                          <Area type="monotone" dataKey="value" stroke="#58a6ff" strokeWidth={2} fill="url(#c)" animationDuration={500} />
                          <Brush dataKey="date" height={30} stroke="#30363d" fill="#0d1117" />
                          <ReferenceLine y={stats?.avg} stroke="#8b949e" strokeDasharray="3 3" />
                        </AreaChart>
                      ) : chartStyle === "line" ? (
                        <LineChart data={observations}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#30363d" vertical={false} />
                          <XAxis dataKey="date" hide /><YAxis stroke="#8b949e" fontSize={10} orientation="right" domain={['auto', 'auto']} />
                          <Tooltip contentStyle={{ background: "#161b22", border: "1px solid #30363d" }} />
                          <Line type="monotone" dataKey="value" stroke="#58a6ff" strokeWidth={2} dot={false} />
                          <Brush dataKey="date" height={30} stroke="#30363d" fill="#0d1117" />
                        </LineChart>
                      ) : (
                        <BarChart data={observations}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#30363d" vertical={false} />
                          <XAxis dataKey="date" hide /><YAxis stroke="#8b949e" fontSize={10} orientation="right" domain={['auto', 'auto']} />
                          <Tooltip contentStyle={{ background: "#161b22", border: "1px solid #30363d" }} />
                          <Bar dataKey="value" fill="#58a6ff" />
                          <Brush dataKey="date" height={30} stroke="#30363d" fill="#0d1117" />
                        </BarChart>
                      )}
                    </ResponsiveContainer>
                  )}
                </div>
              </div>

              {correlationMatrix && (
                <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
                  <CorrelationHeatmap data={correlationMatrix} />
                </div>
              )}

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
                 <div style={{ background: "#0d1117", borderRadius: "1rem", border: "1px solid #30363d", padding: "1.2rem" }}>
                    <h4 style={{ fontSize: "0.7rem", color: "#8b949e", fontWeight: 700, marginBottom: "1rem", display: "flex", alignItems: "center", gap: "0.5rem" }}>
                      <TrendingUp size={14} /> TENDENCIA YoY (Cálculo Rust)
                    </h4>
                    <div style={{ height: "150px" }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={analyzedData?.transformations.yoy_change.slice(-24)}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#222" vertical={false} />
                          <XAxis dataKey="date" hide />
                          <Tooltip contentStyle={{ background: "#111", border: "1px solid #333" }} />
                          <Bar dataKey="value" fill="#3fb950" />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                 </div>
                 <div style={{ background: "#0d1117", borderRadius: "1rem", border: "1px solid #30363d", padding: "1.2rem" }}>
                    <h4 style={{ fontSize: "0.7rem", color: "#8b949e", fontWeight: 700, marginBottom: "1rem", display: "flex", alignItems: "center", gap: "0.5rem" }}>
                      <Activity size={14} /> DINÁMICA MoM
                    </h4>
                    <div style={{ height: "150px" }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={analyzedData?.transformations.mom_change.slice(-24)}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#222" vertical={false} />
                          <XAxis dataKey="date" hide />
                          <Tooltip contentStyle={{ background: "#111", border: "1px solid #333" }} />
                          <Line type="monotone" dataKey="value" stroke="#8957e5" strokeWidth={2} dot={false} />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                 </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "1rem" }}>
                {[
                  { label: "MÁXIMO", val: stats?.max.toLocaleString(), icon: <ArrowUpRight size={14}/> },
                  { label: "MÍNIMO", val: stats?.min.toLocaleString(), icon: <ArrowDownRight size={14}/> },
                  { label: "PROMEDIO", val: stats?.avg.toFixed(2), icon: <Activity size={14}/> },
                  { label: "MUESTRAS", val: stats?.count, icon: <Layers size={14}/> }
                ].map((kpi, i) => (
                  <div key={i} style={{ background: "#161b22", padding: "1rem", borderRadius: "0.75rem", border: "1px solid #30363d" }}>
                    <div style={{ fontSize: "0.65rem", color: "#8b949e", fontWeight: 700, marginBottom: "0.5rem", display: "flex", alignItems: "center", gap: "0.4rem" }}>{kpi.icon} {kpi.label}</div>
                    <div style={{ fontSize: "1.1rem", fontWeight: 800 }}>{kpi.val || "---"}</div>
                  </div>
                ))}
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem", maxHeight: "calc(100vh - 200px)" }}>
              <button 
                onClick={handleAiDeepAnalysis}
                disabled={aiAnalyzing || !analyzedData}
                style={{ 
                  width: "100%", padding: "1.2rem", borderRadius: "0.75rem", border: "none", 
                  background: aiAnalyzing ? "#333" : "linear-gradient(135deg, #238636, #2ea043)", 
                  color: "white", fontWeight: 800, cursor: aiAnalyzing ? "not-allowed" : "pointer", 
                  display: "flex", alignItems: "center", justifyContent: "center", gap: "0.75rem", 
                  boxShadow: "0 4px 15px rgba(0,0,0,0.4)", flexShrink: 0 
                }}
              >
                {aiAnalyzing ? <Loader2 className="spinning" size={20} /> : <Zap size={20} fill="white" />} 
                {aiAnalyzing ? "PROCESANDO MATRIZ MACRO..." : "DEEP AI ANALYSIS (RUST CONTEXT)"}
              </button>

              <button 
                onClick={calculateCorrelation}
                disabled={corrLoading || !selectedFred}
                style={{ 
                  width: "100%", padding: "1rem", borderRadius: "0.75rem", border: "1px solid #30363d", 
                  background: "#161b22", color: "#58a6ff", fontWeight: 700, 
                  cursor: corrLoading ? "not-allowed" : "pointer", 
                  display: "flex", alignItems: "center", justifyContent: "center", gap: "0.75rem",
                  flexShrink: 0 
                }}
              >
                {corrLoading ? <Loader2 className="spinning" size={18} /> : <Table size={18} />} 
                {corrLoading ? "ALINEANDO SERIES..." : "VER MATRIZ DE CORRELACIÓN"}
              </button>

              {analyzedData && activeSource === "fred" && (
                <div style={{ flexShrink: 0 }}>
                  <DataContextCard series={analyzedData} />
                </div>
              )}

              <div style={{ flex: 1, background: "#161b22", borderRadius: "1rem", border: "1px solid #30363d", padding: "1.5rem", display: "flex", flexDirection: "column", overflow: "hidden" }}>
                <h4 style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.8rem", color: "#58a6ff", fontWeight: 800, marginBottom: "1rem", textTransform: "uppercase", letterSpacing: "1px" }}>
                  <Info size={16} /> Ficha Técnica y Análisis
                </h4>
                <div style={{ flex: 1, overflowY: "auto", overflowX: "hidden", fontSize: "0.85rem", lineHeight: "1.7", color: "#c9d1d9", paddingRight: "0.75rem", wordBreak: "break-word" }} className="custom-scroll">
                  
                  <div style={{ background: "rgba(255,255,255,0.03)", padding: "1rem", borderRadius: "0.5rem", marginBottom: "1rem", borderLeft: "3px solid #58a6ff" }}>
                    <span style={{ fontWeight: 700, display: "block", marginBottom: "0.25rem" }}>Contexto Institucional:</span>
                    <div style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{metadata?.notes}</div>
                  </div>

                  {vintageDates.length > 0 && (
                    <div style={{ marginBottom: "1rem", padding: "0.75rem", background: "rgba(251,191,36,0.05)", borderRadius: "0.4rem", border: "1px solid rgba(251,191,36,0.2)" }}>
                      <div style={{ fontSize: "0.7rem", color: "#fbbf24", fontWeight: 700, display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.4rem" }}>
                        <Clock size={12} /> HISTORIAL DE REVISIONES (VINTAGE)
                      </div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem" }}>
                        {vintageDates.slice(0, 5).map(date => (
                          <span key={date} style={{ fontSize: "0.6rem", padding: "0.1rem 0.4rem", background: "rgba(251,191,36,0.1)", color: "#fbbf24", borderRadius: "4px" }}>
                            {date}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {seriesRelease && (
                    <div style={{ marginBottom: "1rem", padding: "0.75rem", background: "rgba(88,166,255,0.05)", borderRadius: "0.4rem", border: "1px solid rgba(88,166,255,0.2)" }}>
                      <div style={{ fontSize: "0.7rem", color: "#8b949e", fontWeight: 700, display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.4rem" }}>
                        <ExternalLink size={12} /> REPORTE DE ORIGEN
                      </div>
                      <div style={{ fontSize: "0.8rem", fontWeight: 700, color: "#58a6ff" }}>{seriesRelease.name}</div>
                    </div>
                  )}

                  {seriesCategories.length > 0 && (
                    <div style={{ marginBottom: "1rem" }}>
                      <div style={{ fontSize: "0.7rem", color: "#8b949e", fontWeight: 700, display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.5rem" }}>
                        <LayoutGrid size={12} /> CATEGORÍAS RELACIONADAS
                      </div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
                        {seriesCategories.slice(0, 5).map(c => (
                          <span key={c.id} style={{ fontSize: "0.65rem", padding: "0.2rem 0.5rem", background: "#30363d", borderRadius: "10px", color: "#c9d1d9" }}>
                            {c.name}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  <p style={{ opacity: 0.7 }}>ID de Serie: <code style={{ color: "#ff7b72" }}>{metadata?.id}</code></p>
                </div>
                <div style={{ marginTop: "1rem", paddingTop: "1rem", borderTop: "1px solid #30363d", fontSize: "0.7rem", color: "#8b949e", display: "flex", justifyContent: "space-between", flexShrink: 0 }}>
                  <span>ACTUALIZADO: {metadata?.last_updated}</span>
                  <span>v4.0.0 - TOTAL ACCESS</span>
                </div>
              </div>
            </div>

          </div>
        </div>
      </div>

      <style>{`
        .spinning { animation: spin 1s linear infinite; }
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        .explorer-item:hover { background: rgba(255,255,255,0.05); }
        .custom-scroll::-webkit-scrollbar { width: 4px; }
        .custom-scroll::-webkit-scrollbar-track { background: transparent; }
        .custom-scroll::-webkit-scrollbar-thumb { background: #30363d; borderRadius: 10px; }
      `}</style>
    </div>
  );
}

export default MacroDataPanel;
