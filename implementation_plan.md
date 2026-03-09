# Phase 1: Conectar Componentes Existentes — Plan de Implementación

## Contexto del Problema

QuantFund tiene una arquitectura sólida con 9 crates Rust, dashboard Tauri, y framework de research Python. Sin embargo, los componentes están parcialmente desconectados:
- El **backtest con datos reales** funciona desde el dashboard ([xauusd_engine.rs](file:///c:/Users/Fredd/QuantFund/dashboard/src-tauri/src/xauusd_engine.rs) → PostgreSQL), pero el CLI solo usa datos sintéticos
- **Solo existe SMA Crossover** como estrategia — Mean Reversion, Momentum y Breakout están listados en el catálogo pero no implementados
- Las **señales FRED** se generan en el dashboard pero no se alimentan al motor de backtest
- **MT5 bridge** está completo (TCP, JSON wire format) pero no tiene un `LiveRunner` que lo use
- **24 archivos** tienen tests pero no hay CI ni cobertura automatizada

## User Review Required

> [!IMPORTANT]
> **Estrategias a implementar:** Las 3 estrategias (Mean Reversion, Momentum RSI, Channel Breakout) usan indicadores técnicos estándar. ¿Quieres alguna personalización específica o parámetros diferentes a los defaults del catálogo?

> [!WARNING]  
> **Base de datos PostgreSQL:** Se asume que ya existe un servidor PostgreSQL local con datos XAUUSD cargados en `xauusd_ohlcv`. Si no existe, se creará el esquema y un script de ingesta. ¿Tienes datos CSV de XAUUSD históricos listos para cargar?

---

## Proposed Changes

### 1. Estrategias de Trading — `engine/strategy/`

Implementar las 3 estrategias que el catálogo de `commands.rs` ya lista como `available: true` pero que no tienen código Rust.

---

#### [NEW] [mean_reversion.rs](file:///c:/Users/Fredd/QuantFund/engine/strategy/src/mean_reversion.rs)

Bollinger Bands mean reversion strategy:
- Mantiene buffer circular de precios de cierre (último bid)
- Calcula SMA y desviación estándar del período
- **Buy** cuando precio cae bajo la banda inferior (oversold)
- **Sell** cuando precio sube sobre la banda superior (overbought)
- **Exit** cuando precio vuelve a la SMA central
- Parámetros: `period` (default 20), `std_dev` (default 2.0), `position_size` (default 0.1)
- Incluye tests unitarios

#### [NEW] [momentum_rsi.rs](file:///c:/Users/Fredd/QuantFund/engine/strategy/src/momentum_rsi.rs)

RSI momentum strategy:
- Calcula Relative Strength Index usando EMA de ganancias/pérdidas
- **Buy** cuando RSI cruza de abajo hacia arriba el nivel `oversold` (default 30)
- **Sell** cuando RSI cruza de arriba hacia abajo el nivel `overbought` (default 70)
- Parámetros: `rsi_period` (default 14), `oversold` (default 30), `overbought` (default 70), `position_size`
- Incluye tests unitarios

#### [NEW] [channel_breakout.rs](file:///c:/Users/Fredd/QuantFund/engine/strategy/src/channel_breakout.rs)

Donchian Channel breakout strategy:
- Trackea high/low de los últimos N ticks/bars
- **Buy** cuando precio rompe el máximo del canal (new high)
- **Sell** cuando precio rompe el mínimo del canal (new low)
- Parámetros: `lookback` (default 20), `position_size` (default 0.1)
- Incluye tests unitarios

#### [MODIFY] [lib.rs](file:///c:/Users/Fredd/QuantFund/engine/strategy/src/lib.rs)

- Agregar `pub mod mean_reversion;`, `pub mod momentum_rsi;`, `pub mod channel_breakout;`
- Re-exportar los nuevos tipos

---

### 2. FRED Signals → Backtest Integration — `engine/strategy/`

Crear una estrategia que consuma señales FRED pre-generadas y las emita como `SignalEvent` durante el backtest.

---

#### [NEW] [fred_signal_strategy.rs](file:///c:/Users/Fredd/QuantFund/engine/strategy/src/fred_signal_strategy.rs)

Similar a `PythonSignalRelay` pero lee señales FRED de un archivo JSON pre-generado:
- Acepta un `Vec<FredSignalEntry>` con fecha, dirección, strength
- Durante `on_tick`, busca la señal más cercana al timestamp del tick
- Emite `SignalEvent` con side/strength del macro analysis
- Permite combinar con estrategias técnicas (composite strategy)

---

### 3. Integración Multi-Estrategia — `dashboard/src-tauri/`

#### [MODIFY] [xauusd_engine.rs](file:///c:/Users/Fredd/QuantFund/dashboard/src-tauri/src/xauusd_engine.rs)

En `create_strategy()` (línea 309), agregar match arms para:
- `"mean_reversion"` → `MeanReversion::new(config)`
- `"momentum"` → `MomentumRsi::new(config)`
- `"breakout"` → `ChannelBreakout::new(config)`
- `"fred_macro"` → `FredSignalStrategy::new(config)`

Esto permite que el dashboard lance backtests con cualquier estrategia del catálogo.

---

### 4. PostgreSQL Data Provider — `engine/data/`

#### [NEW] [postgres_provider.rs](file:///c:/Users/Fredd/QuantFund/engine/data/src/postgres_provider.rs)

Implementa `TickDataProvider` trait con PostgreSQL como fuente de datos:
- Conecta a PostgreSQL usando la misma lógica que `database.rs` del dashboard
- `load_ticks()` carga OHLCV bars y las convierte a ticks (reutilizando `bars_to_ticks` de `xauusd_engine.rs`)
- `available_range()` consulta MIN/MAX de `datetime` en `xauusd_ohlcv`
- `instruments()` retorna los símbolos disponibles

#### [MODIFY] [lib.rs](file:///c:/Users/Fredd/QuantFund/engine/data/src/lib.rs)

- Agregar `pub mod postgres_provider;`
- Re-exportar `PostgresTickProvider`

---

### 5. CLI con Datos Reales — `engine/bin/`

#### [MODIFY] [main.rs](file:///c:/Users/Fredd/QuantFund/engine/bin/src/main.rs)

Agregar un nuevo subcomando `backtest-db` que:
- Acepta `--db-url` para conexión PostgreSQL  
- Acepta `--symbol` (default XAUUSD) y `--timeframe` (default M1)
- Acepta `--strategy` (sma, mean_reversion, momentum, breakout, fred_macro)
- Carga datos de PostgreSQL via `PostgresTickProvider`
- Muestra resultado con métricas de rendimiento

---

### 6. Esquema de Base de Datos — `scripts/`

#### [NEW] [create_schema.sql](file:///c:/Users/Fredd/QuantFund/scripts/create_schema.sql)

```sql
CREATE TABLE IF NOT EXISTS xauusd_ohlcv (
    datetime TIMESTAMP NOT NULL,
    symbol VARCHAR(20) NOT NULL DEFAULT 'XAUUSD',
    timeframe VARCHAR(10) NOT NULL DEFAULT 'M1',
    o NUMERIC(12,5) NOT NULL,
    h NUMERIC(12,5) NOT NULL,
    l NUMERIC(12,5) NOT NULL,
    c NUMERIC(12,5) NOT NULL,
    v BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (datetime, symbol, timeframe)
);
CREATE INDEX IF NOT EXISTS idx_xauusd_symbol_tf ON xauusd_ohlcv(symbol, timeframe, datetime);
```

#### [NEW] [ingest_csv.py](file:///c:/Users/Fredd/QuantFund/scripts/ingest_csv.py)

Script Python para cargar datos CSV históricos a PostgreSQL usando psycopg2 con batch insert.

---

### 7. LiveRunner para Paper Trading — `engine/backtest/`

#### [NEW] [live_runner.rs](file:///c:/Users/Fredd/QuantFund/engine/backtest/src/live_runner.rs)

Un runner simplificado para paper/live trading:
- Usa `BacktestRunner::with_bridge()` con `Mt5Bridge` 
- Se subscribe a ticks de MT5 vía el bridge
- Procesa señales de estrategias y envía órdenes a MT5
- Incluye loop de heartbeat/ping

#### [MODIFY] [lib.rs](file:///c:/Users/Fredd/QuantFund/engine/backtest/src/lib.rs)

- Agregar `pub mod live_runner;`
- Re-exportar `LiveRunner`

---

## Verification Plan

### Automated Tests

**Existentes (24 archivos con tests):**
```bash
# Ejecutar todos los tests existentes
cargo test --workspace
```
Tests existentes cubren: `sma_crossover`, `python_signal_relay` (5 tests), `simulation_bridge` (4 tests), `mt5_bridge` (5 tests), `matching_engine`, `oms`, `risk_engine`, `var`, `volatility`, `correlation`, `event_bus`, `event_router`, `handler`, `tick_replay`, `synthetic_ticks`, `provider`, `latency`, `impact`, `queue`, `fred_cache`, `worldbank`.

**Nuevos tests a agregar:**
1. `mean_reversion.rs` — 4 tests: buy signal below lower band, sell signal above upper band, no signal within bands, reset clears buffers
2. `momentum_rsi.rs` — 4 tests: buy when RSI crosses oversold up, sell when RSI crosses overbought down, neutral in middle, reset
3. `channel_breakout.rs` — 3 tests: breakout above channel, breakout below channel, no signal within channel
4. `fred_signal_strategy.rs` — 3 tests: emits correct signal for date, returns None when no signal for timestamp, handles empty signal list

```bash
# Ejecutar tests específicos de las nuevas estrategias
cargo test -p quantfund-strategy mean_reversion
cargo test -p quantfund-strategy momentum_rsi
cargo test -p quantfund-strategy channel_breakout
cargo test -p quantfund-strategy fred_signal
```

### Manual Verification

1. **Backtest con datos reales desde CLI:**
   ```bash
   cargo run -p quantfund-bin -- backtest-db --symbol XAUUSD --strategy sma_crossover
   ```
   Verificar que muestra métricas de rendimiento reales (Sharpe, max drawdown, trades, PnL).

2. **Dashboard con nueva estrategia:**
   - Abrir dashboard (`npm run tauri dev` desde `dashboard/`)
   - Seleccionar "Mean Reversion" en el selector de estrategias
   - Ejecutar backtest
   - Verificar que se muestra equity curve y métricas

3. **MT5 Paper Trading (requiere MT5 terminal activo):**
   - Abrir MT5 terminal
   - Ejecutar el comando de paper trading
   - Verificar que la conexión TCP se establece y las órdenes se envían
   - *Nota: Este test requiere que el usuario tenga MT5 instalado y configurado*
