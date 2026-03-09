// Types mirroring the Rust DashboardSnapshot struct.

export interface EquityPoint {
  ts: number;
  equity: number;
}

export interface PositionSnapshot {
  instrument: string;
  side: string;
  volume: number;
  entry_price: number;
  unrealized_pnl: number;
}

export interface RiskSnapshot {
  equity: number;
  balance: number;
  daily_pnl: number;
  current_drawdown_pct: number;
  max_drawdown_pct: number;
  open_positions: number;
  total_closed_trades: number;
  kill_switch_active: boolean;
}

export interface OrderLogEntry {
  ts: number;
  event_type: string;
  instrument: string;
  side: string;
  volume: number;
  price: number;
  note: string;
}

export interface LatencySample {
  label: string;
  latency_us: number;
}

export interface ConnectionStatus {
  mode: string;
  connected: boolean;
  symbols: string[];
  ping_ms: number;
}

export interface Mt5AccountInfo {
  login: number;
  server: string;
  currency: string;
  balance: number;
  equity: number;
  margin: number;
  free_margin: number;
  margin_level: number;
  profit: number;
  leverage: number;
}

export interface Mt5Position {
  ticket: number;
  symbol: string;
  volume: number;
  open_price: number;
  current_price: number;
  profit: number;
  side: string;
  open_time: string;
}

export interface Mt5Order {
  ticket: number;
  symbol: string;
  volume: number;
  price: number;
  order_type: string;
  status: string;
  open_time: string;
}

export interface Mt5Deal {
  ticket: number;
  order: number;
  symbol: string;
  volume: number;
  price: number;
  profit: number;
  side: string;
  entry: string;
  time: string;
}

export interface DashboardSnapshot {
  equity_curve: EquityPoint[];
  positions: PositionSnapshot[];
  risk: RiskSnapshot;
  order_log: OrderLogEntry[];
  latency: LatencySample[];
  connection: ConnectionStatus;
  progress_pct: number;
  tick_count: number;
  total_ticks: number;
}

export const EMPTY_SNAPSHOT: DashboardSnapshot = {
  equity_curve: [],
  positions: [],
  risk: {
    equity: 0,
    balance: 0,
    daily_pnl: 0,
    current_drawdown_pct: 0,
    max_drawdown_pct: 0,
    open_positions: 0,
    total_closed_trades: 0,
    kill_switch_active: false,
  },
  order_log: [],
  latency: [],
  connection: {
    mode: "SIMULATION",
    connected: false,
    symbols: [],
    ping_ms: 0,
  },
  progress_pct: 0,
  tick_count: 0,
  total_ticks: 0,
};
