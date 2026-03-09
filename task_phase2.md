# Phase 2: Cerebro de Datos — QuantFund

## Contexto
Expandir la capacidad del sistema para ingerir y procesar datos masivos más allá de series de tiempo de precios, convirtiendo a QuantFund en un sistema "macro-aware" en tiempo real.

## Workstreams

### 1. Ingesta Masiva FRED (Data Lake)
- [ ] Optimizar `FredClient` para descargas masivas y concurrentes.
- [ ] Crear esquema de base de datos eficiente para millones de datapoints (`fred_series`, `fred_observations`).
- [ ] Script de "bootstrap" para descargar las 823K series (o un subconjunto curado de alta relevancia).
- [ ] Implementar sistema de actualización incremental inteligente (cron job).

### 2. Conector Binance (Precios Spot Real-Time)
- [ ] Crear módulo `engine/data/src/binance`.
- [ ] Implementar cliente WebSocket para `btcusdt`, `ethusdt`, `paxg` (oro tokenizado) para correlaciones.
- [ ] Normalizar datos de Binance al formato `TickEvent` del engine.
- [ ] Integrar feed de Binance en `LiveRunner` como fuente de datos secundaria.

### 3. API de Noticias (Finnhub + NewsAPI)
- [ ] Refactorizar `finnhub.rs` del dashboard a `engine/data/src/news/finnhub.rs`.
- [ ] Implementar cliente para NewsAPI.
- [ ] Crear estructura unificada `NewsEvent` en `quantfund_core`.
- [ ] Almacenar noticias en PostgreSQL con análisis de sentimiento (placeholder o básico por ahora).

### 4. Conector Twitter/X (Sentiment Analysis)
- [ ] Crear módulo `engine/data/src/twitter`.
- [ ] Implementar cliente usando API v2 (requiere Bearer Token).
- [ ] Definir lista de cuentas clave (FED, ECB, Powell, etc.).
- [ ] Pipeline de ingesta a base de datos de "Social Sentiment".

### 5. Base de Datos de Eventos Geopolíticos
- [ ] Diseñar esquema SQL para eventos (`conflict`, `election`, `sanction`).
- [ ] Crear API interna para registrar eventos manualmente o via scraping.
- [ ] Visualizar eventos en el Dashboard sobre el gráfico de precios.

## Dependencias
- Claves de API: Binance, Finnhub, NewsAPI, Twitter/X.
- Servidor PostgreSQL con suficiente almacenamiento para FRED data lake.
