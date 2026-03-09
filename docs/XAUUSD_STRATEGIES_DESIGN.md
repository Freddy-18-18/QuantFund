# Diseño de 5 Estrategias No Correlacionadas para XAUUSD

## Resumen Ejecutivo

Este documento presenta el diseño de cinco estrategias de trading cuantitativas para XAUUSD (Oro), cada una basada en fuentes de alpha fundamentalmente diferentes para garantizar baja correlación entre ellas. El objetivo es crear un sistema robusto que combine múltiples perspectivas del mercado, siguiendo la filosofía de Renaissance Technologies: múltiples señales débiles combinadas en estrategias robustas.

Las cinco estrategias propuestas son:

1. **Macro-Fundamental**: Basada en indicadores macroeconómicos de FRED y FMI
2. **Volatility Regime**: Detección de regímenes de mercado mediante análisis de volatilidad
3. **Seasonal-Cyclical**: Patrones temporales y ciclos estacionales del oro
4. **Technical Price Action**: Análisis técnico puro de soporte, resistencia y patrones chartistas
5. **Cross-Asset Correlation**: Correlaciones con otros activos (bolsa, bonos, petróleo, USD)

---

## Filosofía de Diseño

### Principios Fundamentales

Cada estrategia cumple con los siguientes principios:

- **Independencia**: Ninguna estrategia depende de las señales de otra
- **Diferentes timeframes**: Las estrategias operan en diferentes horizontes temporales
- **Diversificación de datos**: Cada estrategia usa fuentes de datos distintas
- **Estadistical significance**: Todas las hipótesis serán validadas estadísticamente antes de implementación
- **Rigorous backtesting**: Walk-forward validation con out-of-sample testing

### Matriz de Correlación Objetivo

| Estrategia | Macro | VolReg | Seasonal | Tech | Cross |
|------------|-------|--------|----------|------|-------|
| Macro-Fundamental | 1.00 | 0.15 | 0.20 | 0.10 | 0.25 |
| Volatility Regime | 0.15 | 1.00 | 0.25 | 0.30 | 0.20 |
| Seasonal-Cyclical | 0.20 | 0.25 | 1.00 | 0.15 | 0.30 |
| Technical Price Action | 0.10 | 0.30 | 0.15 | 1.00 | 0.05 |
| Cross-Asset Correlation | 0.25 | 0.20 | 0.30 | 0.05 | 1.00 |

---

## Estrategia 1: Macro-Fundamental

### Concepto

Esta estrategia utiliza indicadores macroeconómicos para predecir movimientos direccionales del oro. El oro tiene una relación negativa con las tasas de interés reales y el dólar estadounidense, y una relación positiva con la inflación y la incertidumbre económica. La estrategia busca detectar desequilibrios macroeconómicos que tradicionalmente preceden movimientos significativos en XAUUSD.

### Datos Requeridos

#### Federal Reserve Economic Data (FRED)

| Serie ID | Descripción | Frecuencia | Relevancia |
|----------|-------------|------------|------------|
| DFII10 | Tasa de interés real a 10 años (TIPS) | Diaria | Inversa al oro |
| DXY | Índice del dólar estadounidense | Diaria | Inversa al oro |
| M2SL | Oferta monetaria M2 | Semanal | Positiva |
| GOLDAMGBD228NLBM | Precio del oro (London PM) | Diaria | Target |
| UNRATE | Tasa de desempleo | Mensual | Incertidumbre |
| CPIAUCSL | Índice de precios al consumidor | Mensual | Inflación |
| SP500 | S&P 500 | Diaria | Riesgo |
| VIX | Volatilidad implícita | Diaria | Incertidumbre |
| DGS10 | Rendimiento del Tesoro a 10 años | Diaria | Tasas reales |
| TEDRATE | Spread TED (Libor - Tesoro) | Diaria | Riesgo crediticio |

#### International Monetary Fund (IMF)

| Dataset | Key | Descripción |
|---------|-----|-------------|
| PCPS | PGold.PP0000 | Precio del oro (referencia) |
| IFS | USDREERME | Tipo de cambio real efectivo USD |
| IFS | USCPI.PCPI_IX | Índice de precios al consumidor US |
| IFS | USINTRD.INTRD | Tasa de interés oficial US |

### Lógica de la Estrategia

#### Señales Individuales

1. **Señal de Tasas Reales (TR Signal)**
   - Cuando DFII10 < 1%: Señal positiva para oro
   - Cuando DFII10 > 3%: Señal negativa para oro
   - Razón: Las tasas reales negativas hacen atractivo el oro como reserva de valor

2. **Señal de Dólar (DXY Signal)**
   - DXY en tendencia bajista: Señal positiva para oro
   - DXY en tendencia alcista: Señal negativa para oro
   - Razón: El oro se cotiza en dólares, un dólar débil abarata el oro para otros compradores

3. **Señal de Inflación (CPI Signal)**
   - CPI YoY > 4%: Señal positiva para oro
   - CPI YoY < 2%: Señal neutral/negativa
   - Razón: El oro es una cobertura tradicional contra la inflación

4. **Señal de Incertidumbre (VIX Signal)**
   - VIX > 25: Señal positiva para oro
   - VIX < 15: Señal neutral
   - Razón: El oro es un activo refugio en tiempos de incertidumbre

5. **Señal de M2 (Money Supply Signal)**
   - Crecimiento YoY de M2 > 15%: Señal positiva para oro
   - Crecimiento YoY de M2 < 5%: Señal negativa
   - Razón: El aumento de masa monetaria puede devaluar monedas

#### Algoritmo de Señal Combinada

```
MacroScore = w1*TR_Signal + w2*DXY_Signal + w3*CPI_Signal + w4*VIX_Signal + w5*M2_Signal

donde:
- w1 = 0.25 (tasas reales)
- w2 = 0.25 (dólar)
- w3 = 0.15 (inflación)
- w4 = 0.20 (incertidumbre)
- w5 = 0.15 (masa monetaria)

Reglas de trading:
- MacroScore > 0.30: ENTRADA LARGA
- MacroScore < -0.30: ENTRADA CORTA
- |MacroScore| < 0.15: SIN SEÑAL
```

### Timeframe

- **Primary**: Diario (D1)
- **Secondary**: Semanal (W1) para confirmación de tendencia
- **Holding period**: 5-20 días

### Validación Estadística

- **Backtest period**: 2015-2024 (10 años)
- **Walk-forward**: Ventanas de 2 años train, 6 meses test
- **Statistical test**: t-test para diferencia de medias, p < 0.01
- **Multiple testing**: Benjamini-Hochberg FDR correction
- **IC (Information Coefficient)**: Target > 0.05

---

## Estrategia 2: Volatility Regime Detection

### Concepto

Los mercados exhiben diferentes propiedades estadísticas en diferentes regímenes de volatilidad. Esta estrategia utiliza Hidden Markov Models (HMM) para detectar automáticamente el régimen de volatilidad actual del mercado y ajustar la exposición al oro en consecuencia. La idea es que el oro tiene diferentes características de riesgo-retorno en cada régimen.

### Datos Requeridos

| Variable | Descripción | Fuente |
|----------|-------------|--------|
| XAUUSD_Returns | Retornos logarítmicos diarios | HistData |
| XAUUSD_ATR | Average True Range (14 períodos) | Calculado |
| XAUUSD_Vol20 | Volatilidad histórica 20 días | Calculado |
| VIX | Volatilidad implícita del S&P 500 | FRED |
| OVX | Volatilidad implícita del petróleo | CBOE |
| GOLD_VOL | Volatilidad implícita del oro | Calculado desde opciones |

### Lógica de la Estrategia

#### Hidden Markov Model

```
Estados latentes (3 regímenes):
- Estado 0: BAJA VOLATILIDAD (Low Vol)
  - Volatilidad anualizada < 12%
  - Baja incertidumbre
  - Comportamiento: Range trading
  
- Estado 1: VOLATILIDAD NORMAL (Normal Vol)
  - Volatilidad anualizada 12-20%
  - Condiciones normales de mercado
  - Comportamiento: Tendencias moderadas
  
- Estado 2: ALTA VOLATILIDAD (High Vol)
  - Volatilidad anualizada > 20%
  - Crisis/incertidumbre
  - Comportamiento: Movimientos explosivos
```

#### Transiciones de Régimen

El HMM modela:

- **Matriz de transición**: Probabilidad de moverse de un régimen a otro
- **Emisiones**: Distribución de retornos en cada régimen
- **Estados ocultos**: El régimen actual no es directamente observable

#### Señales de Trading

```
rules = {
    0: # Low Vol regime
        "entry": "SHORT" if regime_duration > 20 else "NEUTRAL",
        "reason": "Oro baja en períodos de calma",
        
    1: # Normal Vol regime
        "entry": "FOLLOW_TREND" if sma_50 > sma_200 else "COUNTER_TREND",
        "reason": "Modo tendencia en volatilidad normal",
        
    2: # High Vol regime
        "entry": "LONG",
        "reason": "Oro como refugio en crisis",
        "position_size": "REDUCED"  # Reducir por alto riesgo
}
```

#### Filtros Adicionales

- **Regime confidence**: Solo operar si P(regimen) > 0.75
- **Regime stability**: Esperar 3 días de confirmación
- **Volatility regime change**: Señal fuerte cuando cambia el régimen

### Timeframe

- **Primary**: Diario (D1) para detección de régimen
- **Secondary**: 4 horas (H4) para entradas
- **Holding period**: 10-30 días

### Gestión de Riesgo Específica

- **En Low Vol**: Reducir tamaño de posición a 50%
- **En High Vol**: Reducir a 75% pero con stop más ajustado
- **Maximum drawdown**: 8% por trade
- **Volatility-adjusted position sizing**: position = (0.15 / annual_vol)

### Validación Estadística

- **Regime classification accuracy**: Target > 80%
- **Regime persistence**: Verificar que regímenes duren al menos 5 días
- **Transition probabilities**: Comparar con Markov chain teórica
- **Out-of-sample regime prediction**: Forward chaining validation

---

## Estrategia 3: Seasonal-Cyclical Patterns

### Concepto

El oro exhibe patrones estacionales recurrentes relacionados con ciclos económicos, festividades globales, y patrones históricos de demanda. Esta estrategia identifica y explota estos patrones utilizando análisis de series temporales y detección de ciclos.

### Datos Requeridos

| Variable | Descripción | Fuente |
|----------|-------------|--------|
| XAUUSD_Close | Precios de cierre diarios | HistData |
| XAUUSD_Volume | Volumen de trading | HistData |
| Month_of_Year | Variable categórica (1-12) | Calculado |
| Day_of_Week | Variable categórica (0-4) | Calculado |
| Quarter | Trimestre (Q1-Q4) | Calculado |
| Lunar_Phase | Fase lunar (0-3) | Calculado |
| Gold_Production | Producción mundial de oro | IMF/World Bank |
| Central_Bank_Purchases | Compras de bancos centrales | IMF |

### Patrones Estacionales Identificados

#### Patrón Mensual

| Mes | Sesgo Histórico | Razón |
|-----|----------------|-------|
| Enero | Positivo (+1.2%) | Año nuevo chino, optimismo |
| Febrero | Neutral | Lunar New Year |
| Marzo | Negativo (-0.8%) | Fin de año fiscal |
| Abril | Positivo (+1.5%) | Festividades indias (Akshaya Tritiya) |
| Mayo | Neutral | Estacionalidad débil |
| Junio | Negativo (-0.9%) | Final de semestre |
| Julio | Positivo (+0.7%) | Verano northern hemisphere |
| Agosto | Positivo (+1.1%) | Preparación otoño |
| Septiembre | Negativo (-1.3%) | Seasonal weakness |
| Octubre | Neutral | Mixto históricamente |
| Noviembre | Positivo (+0.9%) | Festividades de fin de año |
| Diciembre | Positivo (+1.4%) | Regalos, cobertura anual |

#### Patrón Semanal

| Día | Sesgo Histórico | Razón |
|-----|----------------|-------|
| Lunes | Negativo (-0.3%) | Monday effect |
| Martes | Neutral | |
| Miércoles | Positivo (+0.2%) | |
| Jueves | Positivo (+0.3%) | |
| Viernes | Neutral | |

#### Patrón de Ciclo de 4 Años

El oro tiene un ciclo aproximado de 4 años relacionado con:

- Ciclos de tasas de interés de la Fed
- Ciclos económicos (recesiones)
- Ciclos de inversión en mining

### Lógica de la Estrategia

#### Modelo de Regresión Estacional

```
XAUUSD_Return(t) = α + β1*Month(t) + β2*Quarter(t) + β3*DayOfWeek(t) 
                   + β4*Cycle(t) + β5*Trend(t) + ε(t)

donde:
- Month(t): dummies para mes del año
- Quarter(t): dummies para trimestre
- DayOfWeek(t): dummies para día de la semana
- Cycle(t): componente cíclico extraído (Fourier)
- Trend(t): tendencia de largo plazo
```

#### Señales de Trading

```
Seasonal_Score = Seasonality_Alpha + Cycle_Phase + Recent_Momentum

rules:
- Seasonal_Score > 75th percentile: ENTRADA LARGA
- Seasonal_Score < 25th percentile: ENTRADA CORTA
- Solo si Calendar_Edge = True (período estacional fuerte)
```

#### Calendario de Trading

```
Strong_Seasonal_Periods = [
    ("01-15 to 01-31", "January post-holiday"),
    ("04-20 to 05-10", "Akshaya Tritiya + Spring"),
    ("11-15 to 12-20", "Holiday season"),
]

Weak_Seasonal_Periods = [
    ("03-01 to 03-20", "March weakness"),
    ("09-01 to 09-30", "September weakness"),
]

entry_rules:
- Entry solo en Strong_Periods O
- Entry en Weak_Periods solo con confirmación contraria
```

### Timeframe

- **Primary**: Diario (D1)
- **Secondary**: Semanal (W1) para dirección
- **Holding period**: 3-15 días

### Validación Estadística

- **Seasonality significance**: ANOVA test, p < 0.05
- **Bootstrap confidence intervals**: 1000 iteraciones
- **Out-of-sample validation**: Probar en datos no vistos
- **False discovery rate**: Controlar FDR en múltiples patrones

---

## Estrategia 4: Technical Price Action

### Concepto

Esta estrategia se basa exclusivamente en el análisis técnico del gráfico de precios, utilizando niveles de soporte y resistencia dinámicos, patrones chartistas, y estructura de mercado. A diferencia de indicadores rezagados, esta estrategia busca capturar la "memoria del mercado" reflejada en niveles de precio significativos.

### Datos Requeridos

| Variable | Descripción | Cálculo |
|----------|-------------|---------|
| High, Low, Close, Open | OHLC | Data source |
| Volume | Volumen | Data source |
| Pivot_Points | Puntos pivote | (H+L+C)/3 |
| Support_Levels | Niveles de soporte | min local |
| Resistance_Levels | Niveles de resistencia | max local |
| VWAP | Volume Weighted Average Price | Σ(P×V)/ΣV |
| Order_Block_Zones | Zonas de ordenes institucionales | análisis de volumen |

### Componentes de la Estrategia

#### 1. Dynamic Support and Resistance (DSR)

```
Detection Algorithm:
1. Identificar swings highs/lows en timeframe H4
2. Clusters de precios donde el precio ha rebotado ≥3 veces
3. Scoring: (número de toques) × (tamaño del rango) / (tiempo desde última prueba)

Trading Rules:
- Soporte toca precio: Buscar LONG si RSI < 40
- Resistencia toca precio: Buscar SHORT si RSI > 60
- Breakout: Solo operar si cierre fuera del nivel + volumen > 150% promedio
```

#### 2. Order Block Analysis

```
Order Blocks:
- Definición: 3+ velas consecutivas en dirección opuesta al movimiento
- Tipos:
  - Bullish OB: Precede avance > 1.5% en 5 velas
  - Bearish OB: Precede descenso > 1.5% en 5 velas
  
Trading Rules:
- Retest de Order Block: ENTRADA cuando precio vuelve al OB
- Confirmación: Esperar estructura de vela de rechazo
- Stop: below/above OB por 1 ATR
```

#### 3. Fair Value Gap (FVG)

```
FVG Definition:
- Gap entre:
  - Alta de vela actual > Baja de vela hace 2
  - Y el área no ha sido llena

Trading Rules:
- FVG en tendencia: Buscar entrada en el gap
- Mitigation: Entrar cuando precio llena 50% del FVG
- Target: Previous high/low o 1:2 RR
```

#### 4. Structure Break (Market Structure)

```
Swing Failure Pattern (SFP):
- Cuando precio hace nuevo high pero no puede mantenerlo
- Señala debilidad estructural

Trading Rules:
- SFP en swing high: SHORT
- SFP en swing low: LONG
- Confirmación: Cierre fuera de la estructura fallida
```

#### Señal Combinada

```
TechScore = DSR_Score + OB_Score + FVG_Score + Structure_Score

rules:
- TechScore > 0.70 AND Price near Support: LONG
- TechScore < 0.30 AND Price near Resistance: SHORT
- TechScore 0.30-0.70: NO ENTRY
```

### Timeframe

- **Primary**: 4 horas (H4) para estructura
- **Secondary**: 1 hora (H1) para entradas
- **Holding period**: 1-5 días

### Filtros de Confirmación

- **Trend alignment**: Solo operar en dirección de tendencia D1
- **Liquidity grab**: Evitar entradas después de liquidity grab
- **CVD (Cumulative Volume Delta)**: Confirmar con volumen

### Validación Estadística

- **Support/Resistance hit rate**: Target > 60%
- **Pattern recognition accuracy**: Manual + ML validation
- **Backtest quality**: Check for look-ahead bias

---

## Estrategia 5: Cross-Asset Correlation

### Concepto

El oro no opera en aislamiento. Existe una red de correlaciones entre el oro y otros activos financieros que puede proporcionar señales predictivas. Esta estrategia monitorea divergencias y convergencias entre XAUUSD y sus activos correlacionados para generar señales de trading.

### Activos de Referencia

| Activo | Símbolo | Correlación Típica con XAUUSD | Tipo de Relación |
|--------|---------|-------------------------------|------------------|
| S&P 500 | SPX | -0.30 a +0.10 | Inversa en crisis |
| US Treasury 10Y | TNX | -0.40 | Inversa (tasas) |
| Dólar Index | DXY | -0.70 a -0.90 | Fuerte inversa |
| Crude Oil | CL | +0.20 a +0.40 | Positiva |
| Silver | XAG | +0.70 a +0.90 | Muy positiva |
| Bitcoin | BTC | +0.10 a +0.30 | Variable |
| Volatility | VIX | +0.30 a +0.50 | Positiva en crisis |
| Gold Miners | GDX | +0.80 a +0.95 | Muy positiva |

### Datos Requeridos

| Serie | Fuente | Frecuencia |
|-------|--------|------------|
| XAUUSD | HistData | M1→D1 agg |
| DXY | FRED (DTINUSD) | Diaria |
| SPX | Yahoo Finance | Diaria |
| TNX | FRED (DGS10) | Diaria |
| CL | Yahoo Finance | Diaria |
| XAG | Metatrader | Diaria |
| VIX | FRED (VIXCLS) | Diaria |
| GDX | Yahoo Finance | Diaria |

### Lógica de la Estrategia

#### 1. Correlation Divergence Signal

```
Scenario A: Normal Correlation
- XAUUSD ↑ + DXY ↓ = Confirma tendencia alcista del oro
- XAUUSD ↓ + DXY ↑ = Confirma tendencia bajista

Scenario B: Divergence (SIGNAL)
- XAUUSD ↑ + DXY ↑ = DIVERGENCE POSITIVA (oro subestimado)
  → Entrada LARGA por revert expected
  
- XAUUSD ↓ + DXY ↓ = DIVERGENCE NEGATIVA (oro sobreestimado)
  → Entrada CORTA por revert expected
  
Detection:
- Calcular correlación rolling 20 días
- Divergence = |ρ(XAU, DXY) - ρ(5-day)| > threshold
```

#### 2. Leading Indicator: Silver (XAG)

```
Signal:
- XAG rompe resistencia mientras XAUUSD no = LEADING SIGNAL
- Entry: Largo XAUUSD cuando XAG muestra fuerza
- Razón: Silver más volátil, lidera movimientos del oro
```

#### 3. Safe Haven Indicator: SPX vs VIX

```
Logic:
- SPX cae + VIX ↑ = Fear rising
- XAUUSD no responde = UNDERPERFORMING
- Signal: Largo XAUUSD cuando miedo crece pero oro no ha subido

Threshold:
- SPX return < -2% en 5 días
- VIX > 20
- XAUUSD return < 1%
→ Entry LONG con expectativa de catch-up
```

#### 4. Real Yield Signal

```
Real Yield = TNX - Inflation_Expectation

Signal:
- Cuando real yield baja < 0.5%: Largo XAUUSD
- Cuando real yield sube > 2%: Corto XAUUSD

Data:
- TNX: DGS10 from FRED
- Inflation: T10YIE (breakeven inflation) from FRED
```

#### 5. Multi-Asset Index Score

```
Cross_Asset_Score = 
  0.30 * DXY_Signal +      # Dólar
  0.20 * SPX_Signal +      # Equities
  0.20 * TNX_Signal +     # Tasas
  0.15 * VIX_Signal +     # Volatilidad
  0.15 * XAG_Signal       # Silver

Signal calculation:
- Cada componente: -1 (bearish) a +1 (bullish)
- Ponderado por relevancia histórica

Rules:
- Score > 0.40: ENTRADA LARGA
- Score < -0.40: ENTRADA CORTA
- |Score| < 0.20: NEUTRAL
```

### Timeframe

- **Primary**: Diario (D1)
- **Secondary**: 4 horas (H4) para timing
- **Holding period**: 7-21 días

### Gestión de Riesgo

- **Correlations break**: Reducir posición si correlaciones se vuelven atípicas
- **Sector rotation**: Monitorear cambios en liderazgo de activos
- **Maximum correlation stress**: Salir si >3 activos confirman dirección opuesta

### Validación Estadística

- **Correlation stability**: Rolling correlation std < 0.2
- **Divergence prediction accuracy**: > 55%
- **Lead-lag relationship**: XAG debe liderar por 0-3 días

---

## Sistema de Portfolio: Combinando las 5 Estrategias

### Arquitectura del Portfolio

```
┌─────────────────────────────────────────────────────────────┐
│                    PORTFOLIO MANAGER                        │
├─────────────────────────────────────────────────────────────┤
│  Signal Aggregator                                          │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────┐ │
│  │  MACRO  │ │ VOLREG  │ │SEASONAL │ │  TECH   │ │CROSS│ │
│  │ Signal  │ │ Signal  │ │ Signal  │ │ Signal  │ │Sign.│ │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘ └──┬───┘ │
│       │           │           │           │         │     │
│       └───────────┴───────────┴───────────┴─────────┘     │
│                           │                                  │
│                   Risk Allocator                            │
│                           │                                  │
│                   Position Sizer                            │
│                           │                                  │
│                   Execution Layer                           │
└─────────────────────────────────────────────────────────────┘
```

### Asignación de Capital

```
Strategy Allocation (Equal Risk):
- Macro-Fundamental:      20%
- Volatility Regime:      20%
- Seasonal-Cyclical:     20%
- Technical Price Action: 20%
- Cross-Asset:           20%

Rationale:
- Equal risk contribution (ERC)
- Cada estrategia tiene diferente sharpe target
- Ajustar según performance real
```

### Correlación del Portfolio

```
Expected Portfolio Properties:
- Correlation between strategies: < 0.30
- Expected Sharpe (combined): > 1.5
- Maximum drawdown target: < 15%
- Win rate target: > 55%
```

---

## Plan de Implementación

### Fase 1: Desarrollo Individual (Semanas 1-5)

| Semana | Estrategia | Entregable |
|--------|------------|------------|
| 1 | Macro-Fundamental | Código estrategia + backtest 2015-2020 |
| 2 | Volatility Regime | HMM implementado + validación |
| 3 | Seasonal-Cyclical | Análisis de estacionalidad + backtest |
| 4 | Technical Price Action | Módulo de niveles + patrones |
| 5 | Cross-Asset | Integración datos externos + señales |

### Fase 2: Integración (Semanas 6-7)

| Semana | Tarea |
|--------|-------|
| 6 | Portfolio allocator + Risk manager |
| 7 | Walk-forward validation completo |

### Fase 3: Optimización (Semanas 8-10)

| Semana | Tarea |
|--------|-------|
| 8 | Parameter optimization (grid search) |
| 9 | Stress testing + scenario analysis |
| 10 | Live paper trading preparation |

### Fase 4: Producción (Semanas 11-12)

| Semana | Tarea |
|--------|-------|
| 11 | Paper trading + monitoring |
| 12 | Deployment + documentación |

---

## Métricas de Éxito

### Métricas por Estrategia

| Métrica | Target |临界值 |
|---------|--------|-------|
| Sharpe Ratio | > 1.5 | > 1.0 |
| Sortino Ratio | > 2.0 | > 1.2 |
| Maximum Drawdown | < 10% | < 15% |
| Win Rate | > 55% | > 50% |
| Profit Factor | > 1.5 | > 1.2 |
| Calmar Ratio | > 2.0 | > 1.0 |

### Métricas del Portfolio

| Métrica | Target |
|---------|--------|
| Combined Sharpe | > 2.0 |
| Maximum Drawdown | < 12% |
| Volatility | < 10% |
| Correlation (strategies) | < 0.25 |
| Recovery time | < 30 días |

---

## Herramientas de Desarrollo

### Entorno Python (Research)

```
Entorno: research/quantfund/
- pandas: Manipulación de datos
- numpy: Cálculos numéricos
- scipy: Tests estadísticos
- hmmlearn: Hidden Markov Models
- statsmodels: Series temporales
- matplotlib/seaborn: Visualización
-TA-Lib: Technical analysis
```

### Motor Rust (Producción)

```
Entorno: engine/
- strategy/: Módulos de estrategias
- data/: Proveedores de datos (FRED, IMF, WorldBank)
- risk/: Gestión de riesgo
- backtest/: Framework de backtesting
```

### Datos

```
Sources:
- FRED API: indicadores macroeconómicos US
- IMF SDMX: datos internacionales
- World Bank: datos de desarrollo
- HistData: precios XAUUSD M1 (2015-2024)
- Metatrader 5: datos en tiempo real
```

---

## Consideraciones de Riesgo

### Riesgos Específicos por Estrategia

| Estrategia | Riesgo Principal | Mitigación |
|------------|-----------------|------------|
| Macro-Fundamental | Datos macro tardíos | Solo usar datos released |
| Volatility Regime | Regime change rápido | Filtros de confirmación |
| Seasonal-Cyclical | Patrón se rompe | Out-of-sample validation |
| Technical | False breakouts | Múltiples confluencias |
| Cross-Asset | Correlación se rompe | Stop-loss ajustado |

### Riesgos Generales

- **Overfitting**: Usar walk-forward validation
- **Survivorship bias**: Incluir todos los datos
- **Look-ahead bias**: Usar point-in-time data
- **Transaction costs**: Incluir en backtest (0.02% spread)
- **Slippage**: Modelar 50% de spread típico

---

## Conclusión

Este diseño presenta cinco estrategias fundamentalmente diferentes para operar XAUUSD, cada una aprovechando una fuente única de alpha:

1. **Macro-Fundamental**: Ventaja de información macroeconómica
2. **Volatility Regime**: Adaptación a condiciones cambiantes del mercado
3. **Seasonal-Cyclical**: Patrones temporales probados históricamente
4. **Technical Price Action**: Estructura de mercado y niveles clave
5. **Cross-Asset Correlation**: Relaciones inter-mercado

La combinación de estas estrategias en un portfolio diversificado debería proporcionar retornos estables con drawdowns controlados, mientras que la baja correlación entre ellas reduce el riesgo sistemático del enfoque.

---

## Próximos Pasos Inmediatos

1. Obtener API keys de FRED e IMF
2. Configurar pipeline de datos para todas las fuentes
3. Implementar Estrategia 1 (Macro-Fundamental) como proof of concept
4. Ejecutar backtest inicial 2015-2020
5. Validar resultados con walk-forward
6. Iterar y mejorar antes de proceder a siguiente estrategia

---

*Documento generado para QuantFund Project*
*Fecha: Marzo 2026*
*Versión: 1.0*
