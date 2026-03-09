import React from 'react';
import { Activity, Gauge, TrendingUp } from 'lucide-react';

interface AnalyzedSeries {
  id: string;
  title: string;
  stats: {
    min: number;
    max: number;
    mean: number;
    current_value: number;
    z_score_current: number;
    percentile_current: number;
  };
}

export const DataContextCard: React.FC<{ series: AnalyzedSeries }> = ({ series }) => {
  const { stats } = series;
  
  // Determinamos el color basado en el Z-Score
  const getZScoreColor = (z: number) => {
    if (Math.abs(z) > 2) return 'text-red-500'; // Anomalía extrema
    if (Math.abs(z) > 1) return 'text-yellow-500'; // Desviación moderada
    return 'text-green-500'; // Normal
  };

  // Determinamos el color del percentil
  const getPercentileColor = (p: number) => {
    if (p > 90 || p < 10) return 'text-orange-500'; // Extremos históricos
    return 'text-gray-300';
  };

  return (
    <div className="bg-[#1e1e1e] border border-[#333] rounded-lg p-6 flex flex-col justify-between h-full">
      <div className="flex items-center gap-2 mb-6 border-b border-[#2a2a2a] pb-4">
        <Activity size={18} className="text-blue-500" />
        <h4 className="text-gray-200 font-semibold uppercase tracking-tight text-xs">Contexto Estadístico (FRED)</h4>
      </div>

      <div className="space-y-6">
        {/* Z-Score Row */}
        <div className="flex justify-between items-center">
          <div className="flex items-center gap-2">
            <Gauge size={16} className="text-gray-500" />
            <span className="text-gray-400 text-sm">Z-Score (Anomalía)</span>
          </div>
          <div className="flex flex-col items-end">
            <span className={`text-xl font-mono font-bold ${getZScoreColor(stats.z_score_current)}`}>
              {stats.z_score_current.toFixed(2)}
            </span>
            <span className="text-[10px] text-gray-600 uppercase">Desv. Estándar</span>
          </div>
        </div>

        {/* Percentile Row */}
        <div className="flex justify-between items-center">
          <div className="flex items-center gap-2">
            <TrendingUp size={16} className="text-gray-500" />
            <span className="text-gray-400 text-sm">Rango Histórico</span>
          </div>
          <div className="flex flex-col items-end">
            <span className={`text-xl font-mono font-bold ${getPercentileColor(stats.percentile_current)}`}>
              {stats.percentile_current.toFixed(1)}%
            </span>
            <span className="text-[10px] text-gray-600 uppercase">Percentil</span>
          </div>
        </div>

        {/* Progress bar visual for Percentile */}
        <div className="w-full bg-[#111] rounded-full h-1.5 overflow-hidden">
          <div 
            className={`h-full transition-all duration-500 ${stats.percentile_current > 90 || stats.percentile_current < 10 ? 'bg-orange-500' : 'bg-blue-600'}`}
            style={{ width: `${stats.percentile_current}%` }}
          />
        </div>
      </div>

      <div className="mt-6 pt-4 border-t border-[#2a2a2a] grid grid-cols-2 gap-4">
        <div>
          <span className="block text-[10px] text-gray-600 uppercase">Promedio</span>
          <span className="text-gray-400 font-mono text-sm">{stats.mean.toLocaleString()}</span>
        </div>
        <div className="text-right">
          <span className="block text-[10px] text-gray-600 uppercase">Rango</span>
          <span className="text-gray-400 font-mono text-xs">{stats.min.toLocaleString()} - {stats.max.toLocaleString()}</span>
        </div>
      </div>
    </div>
  );
};
