from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol

import numpy as np
import pandas as pd


class PositionSizingMethod(Enum):
    FIXED = "fixed"
    FIXED_AMOUNT = "fixed_amount"
    KELLY = "kelly"
    VOLATILITY_ADJUSTED = "volatility_adjusted"
    EQUAL_WEIGHT = "equal_weight"


class SlippageModel(Enum):
    NONE = "none"
    FIXED = "fixed"
    VOLUME_BASED = "volume_based"
    VOLATILITY_BASED = "volatility_based"


@dataclass
class BacktestConfig:
    initial_capital: float = 100000.0
    position_sizing: PositionSizingMethod = PositionSizingMethod.FIXED
    position_size: float = 1.0
    max_position_size: float = 1.0
    slippage_model: SlippageModel = SlippageModel.FIXED
    slippage_bps: float = 5.0
    commission_rate: float = 0.0
    commission_type: str = "percentage"
    fixed_commission: float = 0.0
    min_commission: float = 0.0
    max_commission: float = 0.0
    borrow_rate: float = 0.0
    short_rate: float = 0.0
    margin_rate: float = 1.0
    risk_free_rate: float = 0.0
    annualization_factor: int = 252
    benchmark_symbol: str = "^SPX"


@dataclass
class Trade:
    entry_date: datetime
    exit_date: datetime
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    commission: float
    slippage: float
    holding_period: int
    drawdown_at_entry: float
    drawdown_at_exit: float


@dataclass
class BacktestResult:
    config: BacktestConfig
    start_date: datetime
    end_date: datetime
    total_return: float
    total_return_pct: float
    annualized_return: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    max_drawdown_pct: float
    calmar_ratio: float
    win_rate: float
    profit_factor: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win: float
    avg_loss: float
    avg_holding_period: float
    equity_curve: pd.DataFrame
    trades: list[Trade]
    monthly_returns: pd.DataFrame
    annual_returns: pd.Series
    benchmark_returns: float
    alpha: float
    beta: float
    information_ratio: float
    tail_ratio: float
    skewness: float
    kurtosis: float
    var_95: float
    cvar_95: float
    turnover: float

    def to_dict(self) -> dict:
        return {
            "config": {
                "initial_capital": self.config.initial_capital,
                "position_sizing": self.config.position_sizing.value,
                "slippage_model": self.config.slippage_model.value,
                "commission_rate": self.config.commission_rate,
            },
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "total_return": self.total_return,
            "total_return_pct": self.total_return_pct,
            "annualized_return": self.annualized_return,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "max_drawdown": self.max_drawdown,
            "max_drawdown_pct": self.max_drawdown_pct,
            "calmar_ratio": self.calmar_ratio,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "avg_holding_period": self.avg_holding_period,
            "benchmark_returns": self.benchmark_returns,
            "alpha": self.alpha,
            "beta": self.beta,
            "information_ratio": self.information_ratio,
            "tail_ratio": self.tail_ratio,
            "skewness": self.skewness,
            "kurtosis": self.kurtosis,
            "var_95": self.var_95,
            "cvar_95": self.cvar_95,
            "turnover": self.turnover,
        }


class EquityCurve:
    def __init__(self, initial_capital: float = 100000.0):
        self.initial_capital = initial_capital
        self.data = pd.DataFrame(
            columns=[
                "date",
                "equity",
                "returns",
                "drawdown",
                "drawdown_pct",
                "positions",
                "cash",
            ]
        )
        self.data = self.data.set_index("date")

    def add(self, date: datetime, equity: float, positions: float = 0, cash: float = None):
        if cash is None:
            cash = equity - (positions * equity if positions > 0 else 0)

        returns = (
            (equity / self.initial_capital - 1)
            if len(self.data) == 0
            else (equity / self.data["equity"].iloc[-1] - 1)
        )

        peak = self.data["equity"].max() if len(self.data) > 0 else self.initial_capital
        drawdown = equity - peak
        drawdown_pct = (equity / peak - 1) if peak > 0 else 0

        new_row = pd.DataFrame(
            {
                "equity": [equity],
                "returns": [returns],
                "drawdown": [drawdown],
                "drawdown_pct": [drawdown_pct],
                "positions": [positions],
                "cash": [cash],
            },
            index=[date],
        )
        self.data = pd.concat([self.data, new_row])

    def get_equity(self) -> pd.Series:
        return self.data["equity"]

    def get_returns(self) -> pd.Series:
        return self.data["returns"]

    def get_drawdown(self) -> pd.Series:
        return self.data["drawdown"]

    def get_drawdown_pct(self) -> pd.Series:
        return self.data["drawdown_pct"]


class SignalBacktester:
    def __init__(
        self,
        config: BacktestConfig | None = None,
        initial_capital: float = 100000.0,
    ):
        self.config = config or BacktestConfig(initial_capital=initial_capital)
        self.initial_capital = self.config.initial_capital
        self.current_capital = self.initial_capital

        self.price_data: pd.DataFrame | None = None
        self.signal_data: pd.DataFrame | None = None
        self.volume_data: pd.DataFrame | None = None
        self.benchmark_data: pd.Series | None = None

        self.train_start: datetime | None = None
        self.train_end: datetime | None = None
        self.test_start: datetime | None = None
        self.test_end: datetime | None = None

        self.equity_curve = EquityCurve(self.initial_capital)
        self.trades: list[Trade] = []
        self.positions: pd.Series | None = None
        self.daily_returns: pd.Series | None = None

    def set_parameters(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)

    def load_data(
        self,
        price_data: pd.DataFrame,
        signal_data: pd.DataFrame | None = None,
        volume_data: pd.DataFrame | None = None,
        benchmark_data: pd.Series | None = None,
    ):
        self.price_data = price_data.copy()
        if signal_data is not None:
            self.signal_data = signal_data.copy()
        if volume_data is not None:
            self.volume_data = volume_data.copy()
        if benchmark_data is not None:
            self.benchmark_data = benchmark_data.copy()

        if self.signal_data is None:
            self.signal_data = pd.DataFrame(index=price_data.index)
            for col in price_data.columns:
                self.signal_data[col] = 0.0

    def set_train_test_split(
        self,
        train_start: datetime,
        train_end: datetime,
        test_start: datetime,
        test_end: datetime,
    ):
        self.train_start = train_start
        self.train_end = train_end
        self.test_start = test_start
        self.test_end = test_end

    def generate_trades(
        self,
        signals: pd.DataFrame,
        prices: pd.DataFrame,
    ) -> list[dict]:
        trades = []
        positions = pd.DataFrame(0.0, index=signals.index, columns=signals.columns)

        for i, (date, row) in enumerate(signals.iterrows()):
            if i == 0:
                continue

            prev_positions = positions.iloc[i - 1].copy()

            for col in signals.columns:
                signal = row.get(col, 0)
                prev_pos = prev_positions[col]
                price = prices[col].iloc[i] if col in prices.columns else 0

                if pd.isna(signal) or pd.isna(price):
                    continue

                if signal > 0 and prev_pos <= 0:
                    trades.append(
                        {
                            "date": date,
                            "symbol": col,
                            "side": "long",
                            "entry_price": price,
                            "quantity": 1,
                        }
                    )
                    prev_positions[col] = 1
                elif signal < 0 and prev_pos >= 0:
                    trades.append(
                        {
                            "date": date,
                            "symbol": col,
                            "side": "short",
                            "entry_price": price,
                            "quantity": 1,
                        }
                    )
                    prev_positions[col] = -1
                elif signal == 0 and prev_pos != 0:
                    trades.append(
                        {
                            "date": date,
                            "symbol": col,
                            "side": "close",
                            "exit_price": price,
                            "quantity": abs(prev_pos),
                        }
                    )
                    prev_positions[col] = 0

            positions.loc[date] = prev_positions

        self.positions = positions
        return trades

    def calculate_positions(
        self,
        signals: pd.DataFrame,
        prices: pd.DataFrame,
    ) -> pd.DataFrame:
        positions = pd.DataFrame(0.0, index=signals.index, columns=signals.columns)

        if self.config.position_sizing == PositionSizingMethod.FIXED:
            positions = signals.apply(np.sign) * self.config.position_size
        elif self.config.position_sizing == PositionSizingMethod.FIXED_AMOUNT:
            for col in signals.columns:
                positions[col] = np.where(
                    signals[col] != 0,
                    self.config.position_size / prices[col],
                    0,
                )
        elif self.config.position_sizing == PositionSizingMethod.VOLATILITY_ADJUSTED:
            returns = prices.pct_change()
            vol = returns.rolling(20).std() * np.sqrt(252)
            target_vol = 0.15
            for col in signals.columns:
                positions[col] = np.where(
                    signals[col] != 0,
                    (target_vol / vol[col]) * self.config.position_size,
                    0,
                )
        else:
            positions = signals.apply(np.sign) * self.config.position_size

        positions = positions.clip(-self.config.max_position_size, self.config.max_position_size)
        return positions

    def apply_slippage(
        self,
        prices: pd.DataFrame,
        positions: pd.DataFrame,
    ) -> pd.DataFrame:
        if self.config.slippage_model == SlippageModel.NONE:
            return prices

        adjusted_prices = prices.copy()

        if self.config.slippage_model == SlippageModel.FIXED:
            slippage = self.config.slippage_bps / 10000
            for col in prices.columns:
                adjusted_prices[col] = np.where(
                    positions[col] > 0,
                    prices[col] * (1 - slippage),
                    prices[col] * (1 + slippage),
                )
        elif self.config.slippage_model == SlippageModel.VOLUME_BASED:
            if self.volume_data is not None:
                for col in prices.columns:
                    if col in self.volume_data.columns:
                        avg_volume = self.volume_data[col].rolling(20).mean()
                        volume_factor = np.clip(avg_volume / avg_volume.mean(), 0.5, 2.0)
                        slippage = self.config.slippage_bps / 10000 * volume_factor
                        adjusted_prices[col] = np.where(
                            positions[col] > 0,
                            prices[col] * (1 - slippage),
                            prices[col] * (1 + slippage),
                        )
        elif self.config.slippage_model == SlippageModel.VOLATILITY_BASED:
            returns = prices.pct_change()
            vol = returns.rolling(20).std()
            vol_ratio = vol / vol.rolling(60).mean()
            for col in prices.columns:
                slippage = self.config.slippage_bps / 10000 * vol_ratio[col].fillna(1)
                adjusted_prices[col] = np.where(
                    positions[col] > 0,
                    prices[col] * (1 - slippage),
                    prices[col] * (1 + slippage),
                )

        return adjusted_prices

    def apply_commission(
        self,
        trades: list[dict],
        prices: pd.DataFrame,
    ) -> list[dict]:
        for trade in trades:
            if "exit_price" not in trade:
                continue

            price = trade.get("entry_price", trade.get("exit_price", 0))
            quantity = trade.get("quantity", 1)

            if self.config.commission_type == "percentage":
                commission = price * quantity * self.config.commission_rate
            else:
                commission = self.config.fixed_commission

            commission = max(commission, self.config.min_commission)
            if self.config.max_commission > 0:
                commission = min(commission, self.config.max_commission)

            trade["commission"] = commission
            trade["slippage"] = trade.get("slippage", 0)

        return trades

    def calculate_returns(
        self,
        positions: pd.DataFrame,
        prices: pd.DataFrame,
    ) -> pd.Series:
        returns = prices.pct_change()

        portfolio_returns = (positions.shift(1) * returns).sum(axis=1)

        if self.config.commission_rate > 0:
            position_changes = positions.diff().abs()
            turnover = (position_changes.shift(1) * returns).sum(axis=1).abs()
            portfolio_returns = portfolio_returns - turnover * self.config.commission_rate

        portfolio_returns = portfolio_returns.fillna(0)
        self.daily_returns = portfolio_returns

        return portfolio_returns

    def calculate_sharpe(
        self,
        returns: pd.Series | None = None,
        periods: int = 252,
    ) -> float:
        if returns is None:
            returns = self.daily_returns

        if returns is None or len(returns) == 0:
            return 0.0

        excess_returns = returns - self.config.risk_free_rate / periods
        mean_return = excess_returns.mean() * periods
        std_return = excess_returns.std() * np.sqrt(periods)

        if std_return == 0:
            return 0.0

        return mean_return / std_return

    def calculate_sortino(
        self,
        returns: pd.Series | None = None,
        periods: int = 252,
    ) -> float:
        if returns is None:
            returns = self.daily_returns

        if returns is None or len(returns) == 0:
            return 0.0

        excess_returns = returns - self.config.risk_free_rate / periods
        mean_return = excess_returns.mean() * periods

        downside_returns = excess_returns[excess_returns < 0]
        if len(downside_returns) == 0:
            return np.inf

        downside_std = downside_returns.std() * np.sqrt(periods)

        if downside_std == 0:
            return 0.0

        return mean_return / downside_std

    def calculate_max_drawdown(
        self,
        equity_curve: pd.Series | None = None,
    ) -> tuple[float, float]:
        if equity_curve is None:
            if len(self.equity_curve.data) == 0:
                return 0.0, 0.0
            equity_curve = self.equity_curve.get_equity()

        if len(equity_curve) == 0:
            return 0.0, 0.0

        running_max = equity_curve.expanding().max()
        drawdown = equity_curve - running_max
        max_dd = drawdown.min()

        max_dd_pct = (equity_curve / running_max - 1).min()

        return abs(max_dd), abs(max_dd_pct)

    def calculate_win_rate(self, trades: list[Trade] | None = None) -> float:
        if trades is None:
            trades = self.trades

        if len(trades) == 0:
            return 0.0

        winning = sum(1 for t in trades if t.pnl > 0)
        return winning / len(trades)

    def calculate_profit_factor(self, trades: list[Trade] | None = None) -> float:
        if trades is None:
            trades = self.trades

        if len(trades) == 0:
            return 0.0

        gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))

        if gross_loss == 0:
            return np.inf if gross_profit > 0 else 0.0

        return gross_profit / gross_loss

    def calculate_calmar(
        self,
        returns: pd.Series | None = None,
        periods: int = 252,
    ) -> float:
        if returns is None:
            returns = self.daily_returns

        if returns is None or len(returns) == 0:
            return 0.0

        annualized_return = returns.mean() * periods
        max_dd, _ = self.calculate_max_drawdown()

        if max_dd == 0:
            return 0.0

        return annualized_return / max_dd

    def rolling_sharpe(
        self,
        returns: pd.Series | None = None,
        window: int = 252,
        periods: int = 252,
    ) -> pd.Series:
        if returns is None:
            returns = self.daily_returns

        if returns is None:
            return pd.Series()

        excess_returns = returns - self.config.risk_free_rate / periods
        rolling_mean = excess_returns.rolling(window).mean() * periods
        rolling_std = excess_returns.rolling(window).std() * np.sqrt(periods)

        return rolling_mean / rolling_std

    def drawdown_series(
        self,
        equity_curve: pd.Series | None = None,
    ) -> pd.Series:
        if equity_curve is None:
            if len(self.equity_curve.data) == 0:
                return pd.Series()
            equity_curve = self.equity_curve.get_equity()

        running_max = equity_curve.expanding().max()
        drawdown = equity_curve / running_max - 1

        return drawdown

    def trade_statistics(
        self,
        trades: list[Trade] | None = None,
    ) -> dict:
        if trades is None:
            trades = self.trades

        if len(trades) == 0:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "avg_holding_period": 0.0,
                "largest_win": 0.0,
                "largest_loss": 0.0,
                "avg_pnl": 0.0,
                "avg_pnl_pct": 0.0,
            }

        winning_trades = [t for t in trades if t.pnl > 0]
        losing_trades = [t for t in trades if t.pnl < 0]

        return {
            "total_trades": len(trades),
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate": len(winning_trades) / len(trades),
            "avg_win": np.mean([t.pnl for t in winning_trades]) if winning_trades else 0.0,
            "avg_loss": np.mean([t.pnl for t in losing_trades]) if losing_trades else 0.0,
            "avg_holding_period": np.mean([t.holding_period for t in trades]),
            "largest_win": max([t.pnl for t in winning_trades], default=0.0),
            "largest_loss": min([t.pnl for t in losing_trades], default=0.0),
            "avg_pnl": np.mean([t.pnl for t in trades]),
            "avg_pnl_pct": np.mean([t.pnl_pct for t in trades]),
        }

    def monthly_returns(
        self,
        returns: pd.Series | None = None,
    ) -> pd.DataFrame:
        if returns is None:
            returns = self.daily_returns

        if returns is None or len(returns) == 0:
            return pd.DataFrame()

        monthly = returns.resample("ME").apply(lambda x: (1 + x).prod() - 1)
        monthly_pivot = monthly.to_frame("return")
        monthly_pivot["year"] = monthly_pivot.index.year
        monthly_pivot["month"] = monthly_pivot.index.month

        return monthly_pivot.pivot(index="year", columns="month", values="return")

    def annual_returns(
        self,
        returns: pd.Series | None = None,
    ) -> pd.Series:
        if returns is None:
            returns = self.daily_returns

        if returns is None or len(returns) == 0:
            return pd.Series()

        return returns.resample("YE").apply(lambda x: (1 + x).prod() - 1)

    def walk_forward(
        self,
        train_periods: int,
        test_periods: int,
        step: int | None = None,
    ) -> list[BacktestResult]:
        if self.price_data is None:
            raise ValueError("Price data not loaded")

        if step is None:
            step = test_periods

        results = []
        dates = self.price_data.index

        for i in range(0, len(dates) - train_periods - test_periods, step):
            train_end_idx = i + train_periods
            test_end_idx = train_end_idx + test_periods

            if test_end_idx > len(dates):
                break

            train_dates = dates[i:train_end_idx]
            test_dates = dates[train_end_idx:test_end_idx]

            train_data = self.price_data.loc[train_dates]
            test_data = self.price_data.loc[test_dates]

            train_signals = (
                self.signal_data.loc[train_dates]
                if self.signal_data is not None
                else pd.DataFrame(0, index=train_dates, columns=train_data.columns)
            )
            test_signals = (
                self.signal_data.loc[test_dates]
                if self.signal_data is not None
                else pd.DataFrame(0, index=test_dates, columns=test_data.columns)
            )

            result = self._run_backtest(
                test_data,
                test_signals,
                f"walk_forward_{i}",
            )
            results.append(result)

        return results

    def in_sample_out_sample(
        self,
        train_start: datetime,
        train_end: datetime,
        test_start: datetime,
        test_end: datetime,
    ) -> tuple[BacktestResult, BacktestResult]:
        if self.price_data is None:
            raise ValueError("Price data not loaded")

        is_data = self.price_data.loc[train_start:train_end]
        oos_data = self.price_data.loc[test_start:test_end]

        is_signals = (
            self.signal_data.loc[train_start:train_end]
            if self.signal_data is not None
            else pd.DataFrame(0, index=is_data.index, columns=is_data.columns)
        )
        oos_signals = (
            self.signal_data.loc[test_start:test_end]
            if self.signal_data is not None
            else pd.DataFrame(0, index=oos_data.index, columns=oos_data.columns)
        )

        in_sample_result = self._run_backtest(is_data, is_signals, "in_sample")
        out_sample_result = self._run_backtest(oos_data, oos_signals, "out_sample")

        return in_sample_result, out_sample_result

    def rolling_optimization(
        self,
        param_grid: dict[str, list[Any]],
        train_periods: int,
        test_periods: int,
        metric: str = "sharpe_ratio",
    ) -> dict:
        results = []
        best_params = None
        best_score = -np.inf

        from itertools import product

        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())

        for params in product(*param_values):
            param_dict = dict(zip(param_names, params))
            self.set_parameters(**param_dict)

            rolling_results = self.walk_forward(train_periods, test_periods)

            scores = [getattr(r, metric) for r in rolling_results]
            avg_score = np.mean(scores)

            if avg_score > best_score:
                best_score = avg_score
                best_params = param_dict

            results.append(
                {
                    "params": param_dict,
                    "score": avg_score,
                    "rolling_scores": scores,
                }
            )

        return {
            "results": results,
            "best_params": best_params,
            "best_score": best_score,
        }

    def signal_quality(
        self,
        signals: pd.DataFrame | None = None,
        prices: pd.DataFrame | None = None,
    ) -> dict:
        if signals is None:
            signals = self.signal_data
        if prices is None:
            prices = self.price_data

        if signals is None or prices is None:
            return {}

        forward_returns = prices.pct_change().shift(-1)

        metrics = {}
        for col in signals.columns:
            if col not in prices.columns:
                continue

            sig = signals[col].dropna()
            fwd_ret = forward_returns[col].dropna()

            aligned_sig = sig.loc[sig.index.isin(fwd_ret.index)]
            aligned_fwd = fwd_ret.loc[fwd_ret.index.isin(sig.index)]

            if len(aligned_sig) == 0:
                continue

            correlation = aligned_sig.corr(aligned_fwd)

            long_signals = aligned_sig > 0
            short_signals = aligned_sig < 0

            long_return = aligned_fwd[long_signals].mean() if long_signals.any() else 0
            short_return = aligned_fwd[short_signals].mean() if short_signals.any() else 0

            metrics[col] = {
                "correlation": correlation,
                "long_avg_return": long_return,
                "short_avg_return": short_return,
                "signal_direction_accuracy": (
                    (long_return > 0 and short_return < 0) or (long_return < 0 and short_return > 0)
                ),
                "signal_count": len(aligned_sig[aligned_sig != 0]),
            }

        return metrics

    def signal_decay(
        self,
        signals: pd.DataFrame | None = None,
        prices: pd.DataFrame | None = None,
        periods: int = 20,
    ) -> pd.DataFrame:
        if signals is None:
            signals = self.signal_data
        if prices is None:
            prices = self.price_data

        if signals is None or prices is None:
            return pd.DataFrame()

        returns = prices.pct_change()

        decay_data = []
        for lag in range(1, periods + 1):
            lagged_returns = returns.shift(-lag)
            correlations = signals.corrwith(lagged_returns, axis=0)
            decay_data.append({"lag": lag, "correlations": correlations})

        decay_df = pd.DataFrame([d["correlations"] for d in decay_data])
        decay_df.index = range(1, periods + 1)

        return decay_df

    def signal_correlation(
        self,
        signals: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        if signals is None:
            signals = self.signal_data

        if signals is None:
            return pd.DataFrame()

        return signals.corr()

    def _run_backtest(
        self,
        prices: pd.DataFrame,
        signals: pd.DataFrame,
        name: str = "backtest",
    ) -> BacktestResult:
        positions = self.calculate_positions(signals, prices)

        adjusted_prices = self.apply_slippage(prices, positions)

        returns = self.calculate_returns(positions, adjusted_prices)

        equity = self.initial_capital * (1 + returns).cumprod()

        self.equity_curve = EquityCurve(self.initial_capital)
        for date, eq in equity.items():
            self.equity_curve.add(date, eq)

        trade_list = self._extract_trades(positions, prices, adjusted_prices)
        self.trades = trade_list

        total_return = equity.iloc[-1] / self.initial_capital - 1
        n_periods = len(returns)
        years = n_periods / self.config.annualization_factor
        annualized_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

        sharpe = self.calculate_sharpe(returns)
        sortino = self.calculate_sortino(returns)
        max_dd, max_dd_pct = self.calculate_max_drawdown(equity)
        calmar = self.calculate_calmar(returns)
        win_rate = self.calculate_win_rate(trade_list)
        profit_factor = self.calculate_profit_factor(trade_list)

        stats = self.trade_statistics(trade_list)

        monthly = self.monthly_returns(returns)
        annual = self.annual_returns(returns)

        benchmark_ret = 0.0
        alpha = 0.0
        beta = 0.0
        info_ratio = 0.0

        if self.benchmark_data is not None:
            bench = self.benchmark_data.loc[equity.index]
            benchmark_ret = bench.iloc[-1] / bench.iloc[0] - 1

            cov_matrix = np.cov(returns, bench)
            if cov_matrix.shape == (2, 2):
                beta = cov_matrix[0, 1] / cov_matrix[1, 1] if cov_matrix[1, 1] > 0 else 0
                alpha = (
                    annualized_return
                    - self.config.risk_free_rate
                    - beta * (benchmark_ret - self.config.risk_free_rate)
                )

                tracking_error = (returns - bench).std() * np.sqrt(252)
                info_ratio = (
                    (annualized_return - benchmark_ret) / tracking_error
                    if tracking_error > 0
                    else 0
                )

        tail_ratio = (
            returns.quantile(0.95) / abs(returns.quantile(0.05))
            if returns.quantile(0.05) != 0
            else 0
        )

        skewness = returns.skew()
        kurtosis = returns.kurtosis()

        var_95 = returns.quantile(0.05)
        cvar_95 = returns[returns <= var_95].mean()

        position_changes = positions.diff().abs().sum(axis=1)
        turnover = position_changes.mean() * 252

        return BacktestResult(
            config=self.config,
            start_date=equity.index[0],
            end_date=equity.index[-1],
            total_return=equity.iloc[-1] - self.initial_capital,
            total_return_pct=total_return,
            annualized_return=annualized_return,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown=max_dd,
            max_drawdown_pct=max_dd_pct,
            calmar_ratio=calmar,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_trades=stats["total_trades"],
            winning_trades=stats["winning_trades"],
            losing_trades=stats["losing_trades"],
            avg_win=stats["avg_win"],
            avg_loss=stats["avg_loss"],
            avg_holding_period=stats["avg_holding_period"],
            equity_curve=self.equity_curve.data,
            trades=trade_list,
            monthly_returns=monthly,
            annual_returns=annual,
            benchmark_returns=benchmark_ret,
            alpha=alpha,
            beta=beta,
            information_ratio=info_ratio,
            tail_ratio=tail_ratio,
            skewness=skewness,
            kurtosis=kurtosis,
            var_95=var_95,
            cvar_95=cvar_95,
            turnover=turnover,
        )

    def _extract_trades(
        self,
        positions: pd.DataFrame,
        prices: pd.DataFrame,
        adjusted_prices: pd.DataFrame,
    ) -> list[Trade]:
        trades = []
        prev_positions = (
            positions.iloc[0].copy()
            if len(positions) > 0
            else pd.Series(0, index=positions.columns)
        )

        for i in range(1, len(positions)):
            date = positions.index[i]
            curr_positions = positions.iloc[i]

            for col in positions.columns:
                pos_change = curr_positions[col] - prev_positions[col]

                if pos_change != 0:
                    entry_price = adjusted_prices[col].iloc[i]
                    original_entry_price = prices[col].iloc[i]
                    exit_price = adjusted_prices[col].iloc[i]
                    original_exit_price = prices[col].iloc[i]

                    quantity = abs(pos_change)
                    side = "long" if pos_change > 0 else "short"

                    pnl = 0
                    pnl_pct = 0

                    if pos_change < 0:
                        prev_pos = prev_positions[col]
                        if prev_pos > 0:
                            pnl = (exit_price - original_entry_price) * prev_pos
                            pnl_pct = exit_price / original_entry_price - 1
                        elif prev_pos < 0:
                            pnl = (original_entry_price - exit_price) * abs(prev_pos)
                            pnl_pct = original_entry_price / exit_price - 1

                    commission = (
                        quantity
                        * (original_exit_price + original_entry_price)
                        * self.config.commission_rate
                    )

                    holding_period = 1

                    trades.append(
                        Trade(
                            entry_date=date,
                            exit_date=date,
                            symbol=col,
                            side=side,
                            entry_price=original_entry_price,
                            exit_price=original_exit_price,
                            quantity=quantity,
                            pnl=pnl - commission,
                            pnl_pct=pnl_pct,
                            commission=commission,
                            slippage=exit_price - original_exit_price,
                            holding_period=holding_period,
                            drawdown_at_entry=0,
                            drawdown_at_exit=0,
                        )
                    )

            prev_positions = curr_positions.copy()

        return trades

    def run(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> BacktestResult:
        if self.price_data is None:
            raise ValueError("Price data not loaded. Use load_data() first.")

        prices = self.price_data
        signals = self.signal_data

        if start_date is not None:
            prices = prices.loc[start_date:]
            if signals is not None:
                signals = signals.loc[start_date:]

        if end_date is not None:
            prices = prices.loc[:end_date]
            if signals is not None:
                signals = signals.loc[:end_date]

        if signals is None:
            signals = pd.DataFrame(0, index=prices.index, columns=prices.columns)

        return self._run_backtest(prices, signals, "full_backtest")

    def generate_report(
        self,
        result: BacktestResult | None = None,
    ) -> str:
        if result is None:
            result = self.run()

        report = f"""
================================================================================
                           BACKTEST RESULTS
================================================================================
Period: {result.start_date} to {result.end_date}
Initial Capital: ${result.config.initial_capital:,.2f}

--------------------------------------------------------------------------------
RETURNS
--------------------------------------------------------------------------------
Total Return:      ${result.total_return:,.2f} ({result.total_return_pct * 100:.2f}%)
Annualized Return: {result.annualized_return * 100:.2f}%
Benchmark Return:  {result.benchmark_returns * 100:.2f}%
Alpha:             {result.alpha * 100:.2f}%
Beta:              {result.beta:.4f}

--------------------------------------------------------------------------------
RISK METRICS
--------------------------------------------------------------------------------
Sharpe Ratio:      {result.sharpe_ratio:.4f}
Sortino Ratio:     {result.sortino_ratio:.4f}
Max Drawdown:      ${result.max_drawdown:,.2f} ({result.max_drawdown_pct * 100:.2f}%)
Calmar Ratio:      {result.calmar_ratio:.4f}
VaR (95%):         {result.var_95 * 100:.4f}%
CVaR (95%):        {result.cvar_95 * 100:.4f}%

--------------------------------------------------------------------------------
TRADING STATISTICS
--------------------------------------------------------------------------------
Total Trades:      {result.total_trades}
Winning Trades:    {result.winning_trades}
Losing Trades:     {result.losing_trades}
Win Rate:          {result.win_rate * 100:.2f}%
Profit Factor:    {result.profit_factor:.4f}
Avg Win:           ${result.avg_win:,.2f}
Avg Loss:          ${result.avg_loss:,.2f}
Avg Holding Days: {result.avg_holding_period:.2f}
Turnover:          {result.turnover:.2f}x

--------------------------------------------------------------------------------
DISTRIBUTION
--------------------------------------------------------------------------------
Skewness:          {result.skewness:.4f}
Kurtosis:          {result.kurtosis:.4f}
Tail Ratio:        {result.tail_ratio:.4f}
================================================================================
"""
        return report

    def plot_results(
        self,
        result: BacktestResult | None = None,
        save_path: str | None = None,
    ):
        try:
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
        except ImportError:
            warnings.warn("matplotlib not installed. Skipping plots.")
            return

        if result is None:
            result = self.run()

        fig, axes = plt.subplots(3, 2, figsize=(15, 12))

        equity = result.equity_curve["equity"]
        axes[0, 0].plot(equity.index, equity.values)
        axes[0, 0].set_title("Equity Curve")
        axes[0, 0].set_ylabel("Portfolio Value ($)")
        axes[0, 0].grid(True, alpha=0.3)
        axes[0, 0].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

        drawdown = result.equity_curve["drawdown_pct"]
        axes[0, 1].fill_between(drawdown.index, drawdown.values * 100, 0, alpha=0.3, color="red")
        axes[0, 1].set_title("Drawdown")
        axes[0, 1].set_ylabel("Drawdown (%)")
        axes[0, 1].grid(True, alpha=0.3)
        axes[0, 1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

        returns = result.equity_curve["returns"]
        axes[1, 0].bar(returns.index, returns.values * 100, width=1)
        axes[1, 0].set_title("Daily Returns")
        axes[1, 0].set_ylabel("Return (%)")
        axes[1, 0].axhline(y=0, color="black", linewidth=0.5)
        axes[1, 0].grid(True, alpha=0.3)
        axes[1, 0].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

        rolling_sharpe = self.rolling_sharpe(returns)
        axes[1, 1].plot(rolling_sharpe.index, rolling_sharpe.values)
        axes[1, 1].axhline(y=0, color="black", linewidth=0.5)
        axes[1, 1].set_title("Rolling Sharpe (252-day)")
        axes[1, 1].set_ylabel("Sharpe Ratio")
        axes[1, 1].grid(True, alpha=0.3)
        axes[1, 1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

        monthly = result.monthly_returns
        if not monthly.empty:
            monthly_flat = monthly.values.flatten()
            monthly_flat = monthly_flat[~np.isnan(monthly_flat)]
            axes[2, 0].hist(monthly_flat * 100, bins=20, edgecolor="black")
            axes[2, 0].set_title("Monthly Returns Distribution")
            axes[2, 0].set_xlabel("Return (%)")
            axes[2, 0].set_ylabel("Frequency")
            axes[2, 0].axvline(x=0, color="black", linewidth=0.5)
            axes[2, 0].grid(True, alpha=0.3)

        if len(result.trades) > 0:
            trade_pnls = [t.pnl for t in result.trades]
            axes[2, 1].bar(range(len(trade_pnls)), trade_pnls)
            axes[2, 1].axhline(y=0, color="black", linewidth=0.5)
            axes[2, 1].set_title("Trade P&L")
            axes[2, 1].set_xlabel("Trade #")
            axes[2, 1].set_ylabel("P&L ($)")
            axes[2, 1].grid(True, alpha=0.3)

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches="tight")

        plt.show()

    def save_results(
        self,
        result: BacktestResult | None = None,
        json_path: str | None = None,
        csv_path: str | None = None,
    ):
        if result is None:
            result = self.run()

        if json_path:
            with open(json_path, "w") as f:
                json.dump(result.to_dict(), f, indent=2, default=str)

        if csv_path:
            result.equity_curve.to_csv(csv_path)


def create_sample_data(
    n_days: int = 1000,
    initial_price: float = 100.0,
    volatility: float = 0.02,
    trend: float = 0.0001,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    np.random.seed(42)

    dates = pd.date_range(start="2020-01-01", periods=n_days, freq="D")

    returns = np.random.normal(trend, volatility, n_days)
    prices = initial_price * (1 + returns).cumprod()

    price_df = pd.DataFrame({"price": prices}, index=dates)

    signal = pd.Series(np.sign(returns + np.random.normal(0, 0.005, n_days)), index=dates)
    signal = signal.rolling(5).mean()

    signal_df = pd.DataFrame({"signal": signal}, index=dates)

    return price_df, signal_df


if __name__ == "__main__":
    prices, signals = create_sample_data(500)

    backtester = SignalBacktester(initial_capital=100000)
    backtester.load_data(price_data=prices, signal_data=signals)

    result = backtester.run()

    print(backtester.generate_report(result))

    backtester.plot_results(result)
