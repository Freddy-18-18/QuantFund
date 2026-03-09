use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SeriesPoint {
    pub date: String,
    pub value: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AnalyzedSeries {
    pub id: String,
    pub title: String,
    pub data: Vec<SeriesPoint>,
    pub stats: SeriesStats,
    pub transformations: SeriesTransformations,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SeriesStats {
    pub min: f64,
    pub max: f64,
    pub mean: f64,
    pub current_value: f64,
    pub z_score_current: f64, // Cuántas desviaciones estándar del promedio
    pub percentile_current: f64, // 0-100 rango histórico
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SeriesTransformations {
    pub yoy_change: Vec<SeriesPoint>, // Cambio año a año
    pub mom_change: Vec<SeriesPoint>, // Cambio mes a mes
    pub rolling_volatility: Vec<SeriesPoint>, // Volatilidad móvil
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CorrelationMatrix {
    pub series_ids: Vec<String>,
    pub matrix: Vec<Vec<f64>>, // matrix[i][j] es la correlación entre series_ids[i] y series_ids[j]
}

/// Implementación del motor de análisis
pub struct AnalysisEngine;

impl AnalysisEngine {
    /// Calcula la correlación de Pearson entre dos vectores de datos alineados
    pub fn calculate_pearson(x: &[f64], y: &[f64]) -> f64 {
        let n = x.len() as f64;
        if n < 2.0 { return 0.0; }

        let sum_x: f64 = x.iter().sum();
        let sum_y: f64 = y.iter().sum();
        let sum_xy: f64 = x.iter().zip(y.iter()).map(|(a, b)| a * b).sum();
        let sum_x2: f64 = x.iter().map(|a| a * a).sum();
        let sum_y2: f64 = y.iter().map(|a| a * a).sum();

        let numerator = n * sum_xy - sum_x * sum_y;
        let denominator = ((n * sum_x2 - sum_x * sum_x) * (n * sum_y2 - sum_y * sum_y)).sqrt();

        if denominator == 0.0 { 0.0 } else { numerator / denominator }
    }

    /// Alinea múltiples series por fecha y calcula su matriz de correlación
    pub fn calculate_correlation_matrix(series_data: HashMap<String, Vec<(String, f64)>>) -> CorrelationMatrix {
        let ids: Vec<String> = series_data.keys().cloned().collect();
        let n = ids.len();
        let mut matrix = vec![vec![1.0; n]; n];

        for i in 0..n {
            for j in (i + 1)..n {
                let id_a = &ids[i];
                let id_b = &ids[j];

                // Alinear datos (Inner Join por fecha)
                let data_a = &series_data[id_a];
                let data_b = &series_data[id_b];

                let mut map_b: HashMap<String, f64> = data_b.iter().cloned().collect();
                let mut aligned_a = Vec::new();
                let mut aligned_b = Vec::new();

                for (date, val_a) in data_a {
                    if let Some(val_b) = map_b.remove(date) {
                        aligned_a.push(*val_a);
                        aligned_b.push(val_b);
                    }
                }

                let corr = Self::calculate_pearson(&aligned_a, &aligned_b);
                matrix[i][j] = corr;
                matrix[j][i] = corr;
            }
        }

        CorrelationMatrix {
            series_ids: ids,
            matrix,
        }
    }
    
    /// Calcula estadísticas avanzadas para una serie de datos
    pub fn analyze_series(id: String, title: String, raw_data: Vec<(String, f64)>) -> AnalyzedSeries {
        let values: Vec<f64> = raw_data.iter().map(|(_, v)| *v).collect();
        let current_val = values.last().copied().unwrap_or(0.0);
        
        // 1. Estadísticas Básicas
        let min = values.iter().fold(f64::INFINITY, |a, &b| a.min(b));
        let max = values.iter().fold(f64::NEG_INFINITY, |a, &b| a.max(b));
        let sum: f64 = values.iter().sum();
        let count = values.len() as f64;
        let mean = if count > 0.0 { sum / count } else { 0.0 };

        // 2. Desviación Estándar y Z-Score
        let variance = values.iter().map(|value| {
            let diff = mean - *value;
            diff * diff
        }).sum::<f64>() / count;
        let std_dev = variance.sqrt();
        
        let z_score = if std_dev > 0.0 {
            (current_val - mean) / std_dev
        } else {
            0.0
        };

        // 3. Percentil (Rango histórico)
        let mut sorted_values = values.clone();
        sorted_values.sort_by(|a, b| a.partial_cmp(b).unwrap());
        let position = sorted_values.iter().position(|x| *x == current_val).unwrap_or(0);
        let percentile = (position as f64 / count) * 100.0;

        // 4. Transformaciones (YoY, MoM)
        // Asumiendo datos mensuales para simplificar, idealmente se usa la fecha real
        let data_points: Vec<SeriesPoint> = raw_data.iter().map(|(d, v)| SeriesPoint {
            date: d.clone(),
            value: *v
        }).collect();

        let yoy = Self::calculate_change(&raw_data, 12); // Asumiendo mensual
        let mom = Self::calculate_change(&raw_data, 1);

        AnalyzedSeries {
            id,
            title,
            data: data_points,
            stats: SeriesStats {
                min,
                max,
                mean,
                current_value: current_val,
                z_score_current: z_score,
                percentile_current: percentile,
            },
            transformations: SeriesTransformations {
                yoy_change: yoy,
                mom_change: mom,
                rolling_volatility: vec![], // TODO: Implementar
            }
        }
    }

    fn calculate_change(data: &[(String, f64)], offset: usize) -> Vec<SeriesPoint> {
        let mut result = Vec::new();
        if data.len() <= offset {
            return result;
        }

        for i in offset..data.len() {
            let (date_curr, val_curr) = &data[i];
            let (_, val_prev) = &data[i - offset];
            
            if *val_prev != 0.0 {
                let change = ((val_curr - val_prev) / val_prev.abs()) * 100.0;
                result.push(SeriesPoint {
                    date: date_curr.clone(),
                    value: change,
                });
            }
        }
        result
    }
    
    /// Genera un prompt estructurado para la IA basado en el análisis
    #[allow(dead_code)]
    pub fn generate_ai_context(analysis: &AnalyzedSeries) -> String {
        format!(
            "Data Context for {}:\n\
            - Current Value: {:.2} (Historical Percentile: {:.1}%)\n\
            - Statistical Anomaly: Z-Score is {:.2} (Values > 2.0 are rare/extreme)\n\
            - 1-Period Change: {:.2}%\n\
            - 12-Period Change (Trend): {:.2}%\n\
            - Historical Range: {:.2} to {:.2} (Mean: {:.2})\n",
            analysis.title,
            analysis.stats.current_value,
            analysis.stats.percentile_current,
            analysis.stats.z_score_current,
            analysis.transformations.mom_change.last().map(|p| p.value).unwrap_or(0.0),
            analysis.transformations.yoy_change.last().map(|p| p.value).unwrap_or(0.0),
            analysis.stats.min,
            analysis.stats.max,
            analysis.stats.mean
        )
    }
}
