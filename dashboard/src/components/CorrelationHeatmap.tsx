import React from 'react';

interface CorrelationMatrix {
  series_ids: string[];
  matrix: number[][];
}

export const CorrelationHeatmap: React.FC<{ data: CorrelationMatrix }> = ({ data }) => {
  const { series_ids, matrix } = data;

  const getColor = (value: number) => {
    // Escala de colores: Rojo (-1) -> Blanco (0) -> Verde (1)
    const alpha = Math.abs(value);
    if (value > 0) return `rgba(34, 197, 94, ${alpha})`; // Verde (Tailwind green-500)
    if (value < 0) return `rgba(239, 68, 68, ${alpha})`; // Rojo (Tailwind red-500)
    return 'rgba(255, 255, 255, 0.1)';
  };

  return (
    <div className="bg-[#1e1e1e] border border-[#333] rounded-lg p-6 overflow-hidden">
      <h4 className="text-gray-200 font-semibold uppercase tracking-tight text-xs mb-6 border-b border-[#2a2a2a] pb-4">
        Matriz de Correlación Macro (Pearson)
      </h4>
      
      <div className="overflow-auto custom-scroll">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className="p-2"></th>
              {series_ids.map(id => (
                <th key={id} className="p-2 text-[10px] text-gray-500 font-mono rotate-45 h-20 whitespace-nowrap">
                  {id}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.map((row, i) => (
              <tr key={series_ids[i]}>
                <td className="p-2 text-[10px] text-gray-400 font-mono font-bold border-r border-[#333] whitespace-nowrap">
                  {series_ids[i]}
                </td>
                {row.map((cell, j) => (
                  <td 
                    key={j} 
                    className="p-0 border border-[#111]"
                    title={`${series_ids[i]} vs ${series_ids[j]}: ${cell.toFixed(4)}`}
                  >
                    <div 
                      className="w-12 h-12 flex items-center justify-center text-[10px] font-bold text-white transition-all hover:scale-110 cursor-help"
                      style={{ backgroundColor: getColor(cell) }}
                    >
                      {cell.toFixed(2)}
                    </div>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-6 flex justify-between items-center text-[10px] text-gray-500 uppercase tracking-widest">
        <span>Inversa (-1.0)</span>
        <div className="flex-1 mx-4 h-2 rounded-full bg-gradient-to-r from-red-500 via-gray-800 to-green-500" />
        <span>Directa (1.0)</span>
      </div>
    </div>
  );
};
