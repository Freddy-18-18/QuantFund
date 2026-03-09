import {
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  AreaChart,
  Area,
} from 'recharts';

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
  };
}

export const MacroChart: React.FC<{ series: AnalyzedSeries }> = ({ series }) => {
  // Preparamos los datos para que Recharts los entienda
  const data = series.data.map(p => ({
    date: p.date,
    value: p.value,
    mean: series.stats.mean,
    // Podríamos añadir bandas de desviación si las calculamos en Rust (Z-Score bands)
  }));

  const formatYAxis = (tickItem: number) => {
    return tickItem.toLocaleString(undefined, { maximumFractionDigits: 2 });
  };

  return (
    <div className="bg-[#1e1e1e] border border-[#333] rounded-lg p-4 h-[400px]">
      <div className="flex justify-between mb-4">
        <h3 className="text-gray-400 font-medium uppercase tracking-wider text-sm">{series.title}</h3>
        <span className="text-white font-bold">{series.stats.current_value.toLocaleString()}</span>
      </div>
      <ResponsiveContainer width="100%" height="90%">
        <AreaChart data={data}>
          <defs>
            <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3}/>
              <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#2a2a2a" vertical={false} />
          <XAxis 
            dataKey="date" 
            stroke="#666" 
            tick={{ fontSize: 10 }}
            tickFormatter={(str) => str.slice(0, 7)} // Formato YYYY-MM
            minTickGap={30}
          />
          <YAxis 
            stroke="#666" 
            tick={{ fontSize: 10 }} 
            domain={['auto', 'auto']}
            tickFormatter={formatYAxis}
            orientation="right"
          />
          <Tooltip 
            contentStyle={{ backgroundColor: '#111', border: '1px solid #333', color: '#fff', fontSize: '12px' }}
            itemStyle={{ color: '#3b82f6' }}
          />
          <Area 
            type="monotone" 
            dataKey="value" 
            stroke="#3b82f6" 
            strokeWidth={2}
            fillOpacity={1} 
            fill="url(#colorValue)" 
            isAnimationActive={false}
          />
          <Line 
            type="monotone" 
            dataKey="mean" 
            stroke="#666" 
            strokeDasharray="5 5" 
            dot={false}
            strokeWidth={1}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
};
