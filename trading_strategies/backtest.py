"""Shared vectorized backtest engine, transaction costs, and performance metrics.

Every strategy module in this package returns *positions* (target exposure in
[-1, 1]); this module turns positions + prices into a net-of-cost equity curve.

Positions at timestamp t are assumed to be decided with information available
at t and earn the return from t to t+1 (positions are shifted internally, so
callers never need to shift themselves — pass the "decided at t" series).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass
class BacktestResult:
    """Net and gross strategy returns plus the positions that produced them."""

    returns: pd.Series            # net-of-cost per-bar strategy returns
    gross_returns: pd.Series      # before costs
    positions: pd.Series          # position actually held during each bar
    costs: pd.Series              # per-bar cost drag
    periods_per_year: int = TRADING_DAYS
    equity: pd.Series = field(init=False)

    def __post_init__(self) -> None:
        self.equity = (1 + self.returns.fillna(0)).cumprod()


def backtest(
    prices: pd.Series,
    positions: pd.Series,
    cost_bps: float = 5.0,
    periods_per_year: int = TRADING_DAYS,
) -> BacktestResult:
    """Run a single-asset backtest.

    Parameters
    ----------
    prices : bar close prices.
    positions : target exposure in [-1, 1] decided at each bar's close.
    cost_bps : one-way cost in basis points charged on |change in position|.
    periods_per_year : bars per year, used for annualization (252 for daily).
    """
    prices = prices.dropna()
    positions = positions.reindex(prices.index).fillna(0.0).clip(-1, 1)

    asset_rets = prices.pct_change()
    held = positions.shift(1).fillna(0.0)      # position held during each bar
    gross = held * asset_rets
    turnover = positions.diff().abs().fillna(positions.abs())
    costs = turnover.shift(1).fillna(0.0) * (cost_bps / 1e4)
    net = gross - costs
    return BacktestResult(net, gross, held, costs, periods_per_year)


def backtest_portfolio(
    prices: pd.DataFrame,
    weights: pd.DataFrame,
    cost_bps: float = 5.0,
    periods_per_year: int = TRADING_DAYS,
) -> BacktestResult:
    """Multi-asset backtest. `weights` rows are portfolio weights decided at t."""
    rets = prices.pct_change()
    weights = weights.reindex(prices.index).reindex(columns=prices.columns)
    weights = weights.fillna(0.0)
    held = weights.shift(1).fillna(0.0)
    gross = (held * rets).sum(axis=1)
    turnover = weights.diff().abs().sum(axis=1)
    turnover.iloc[0] = weights.iloc[0].abs().sum()
    costs = turnover.shift(1).fillna(0.0) * (cost_bps / 1e4)
    net = gross - costs
    return BacktestResult(net, gross, held.sum(axis=1), costs, periods_per_year)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def annualized_return(returns: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    r = returns.dropna()
    if len(r) == 0:
        return 0.0
    growth = (1 + r).prod()
    if growth <= 0:
        return -1.0
    return growth ** (periods_per_year / len(r)) - 1


def annualized_vol(returns: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    return float(returns.dropna().std() * np.sqrt(periods_per_year))


def sharpe_ratio(returns: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    r = returns.dropna()
    if len(r) == 0 or r.std() == 0:
        return 0.0
    return float(r.mean() / r.std() * np.sqrt(periods_per_year))


def max_drawdown(returns: pd.Series) -> float:
    equity = (1 + returns.fillna(0)).cumprod()
    peak = equity.cummax()
    return float((equity / peak - 1).min())


def hit_rate(returns: pd.Series) -> float:
    active = returns[returns != 0].dropna()
    if len(active) == 0:
        return 0.0
    return float((active > 0).mean())


def summarize(result: BacktestResult, name: str = "strategy") -> pd.Series:
    """One-row performance summary (net of costs)."""
    r, ppy = result.returns, result.periods_per_year
    return pd.Series(
        {
            "ann_return_gross": annualized_return(result.gross_returns, ppy),
            "ann_return": annualized_return(r, ppy),
            "ann_vol": annualized_vol(r, ppy),
            "sharpe": sharpe_ratio(r, ppy),
            "max_drawdown": max_drawdown(r),
            "hit_rate": hit_rate(r),
            "total_cost_drag": float(result.costs.sum()),
            "n_bars": int(r.notna().sum()),
        },
        name=name,
    )
