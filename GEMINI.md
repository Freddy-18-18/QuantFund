# GEMINI.md - QuantFund Project Context

## Project Overview
**QuantFund** is an institutional-grade, low-latency, event-driven algorithmic trading engine. It is designed for multi-asset execution (specifically optimized for XAUUSD/Gold) with a focus on safety, performance, and determinism.

### Core Architecture
- **Rust Core Engine:** A modular, actor-based system using `tokio` for async tasks and `crossbeam` for low-latency, lock-minimized communication. It handles market data ingestion, risk management, and order execution.
- **Research Framework (Python):** A data pipeline for alpha discovery, feature engineering, and walk-forward validation.
- **Dashboard (Tauri/React):** A professional UI for managing backtests, visualizing equity curves, and monitoring system health.
- **MT5 Integration:** A bridge layer (`mql5/`) for execution via MetaTrader 5 terminals.

---

## Key Technologies
- **Languages:** Rust (Engine), Python (Research), TypeScript (Dashboard/Tauri).
- **Core Libraries (Rust):** `tokio`, `crossbeam`, `rust_decimal`, `arrow`, `serde`, `chrono`.
- **Frontend:** React, Vite, TailwindCSS (for styling), Recharts (for visualization).
- **Database:** PostgreSQL (Historical tick/bar data storage).
- **Communication:** IPC via ZeroMQ/gRPC (planned/in-progress) between the Engine and MT5 Bridge.

---

## Project Structure
- `engine/`: Rust workspace containing the core trading logic.
    - `core/`: Common types, traits, and utilities (Price, Decimal, Timestamp).
    - `events/`: Event definitions (Tick, Order, Fill, Risk).
    - `data/`: Data provider interfaces and PostgreSQL integration.
    - `strategy/`: Pluggable strategy engine (e.g., SMA Crossover).
    - `risk/`: Multi-layer risk management and pre-trade validation.
    - `execution/`: Order Management System (OMS) and matching simulator.
    - `backtest/`: Deterministic tick-level replay engine.
    - `mt5/`: MT5 bridge communication protocol.
- `research/`: Python-based research layer (`pandas`, `scikit-learn`, `polars`).
- `dashboard/`: Tauri-based desktop application.
- `mql5/`: MetaTrader 5 Expert Advisor bridge code.
- `docs/`: Comprehensive documentation (Architecture, FRED integration, etc.).

---

## Building and Running

### Development Environment Setup
Run the setup script to install dependencies and configure the environment:
- **Windows:** `powershell -ExecutionPolicy Bypass -File setup_dashboard.ps1`
- **Linux/Mac:** `./setup_dashboard.sh`

### Core Engine (Rust)
- **Test:** `cargo test --workspace`
- **Build:** `cargo build --release`
- **Run (CLI):** `cargo run -p quantfund-bin`

### Dashboard (Tauri/React)
- **Install Dependencies:** `cd dashboard && npm install`
- **Run (Dev):** `npm run tauri dev`
- **Build:** `npm run tauri build`

### Research Layer (Python)
- **Install:** `cd research && pip install -e .`
- **Run Tests:** `pytest`
- **Load XAUUSD Data:** `python download_histdata.py --start-year 2020 --end-year 2024`

---

## Development Conventions
- **Zero-Allocation in Hot Path:** Avoid heap allocations inside the strategy and risk loops. Use pre-allocated buffers and object pools.
- **Deterministic Replay:** Ensure that given the same input stream (ticks), the backtest and live engine produce identical outputs.
- **Type Safety:** Use `rust_decimal` for all price and volume calculations to avoid floating-point errors.
- **Risk First:** Every order must pass through the hierarchical Risk Engine before being sent to the Execution layer.
- **Documentation:** Maintain `PROJECT_STATUS.md` for current progress and `ARCHITECTURE.md` for design decisions.

---

## Usage Guidelines
- **Adding a Strategy:** Implement the `Strategy` trait in `engine/strategy/src/`.
- **Data Ingestion:** Use `download_histdata.py` to populate the PostgreSQL database before running backtests.
- **MT5 Bridge:** The `QuantFundBridge.mq5` must be running on an MT5 terminal to enable execution.
