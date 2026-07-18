"""Section 6 — Pairs trading (distance method).

Gatev, Goetzmann & Rouwenhorst (2006), "Pairs Trading: Performance of a
Relative-Value Arbitrage Rule", Review of Financial Studies 19(3).

The paper's recipe, followed here:
1. Formation (12 months): normalize each stock's cumulative-return path to
   start at 1; pair each stock with the partner minimizing the sum of squared
   differences (SSD) between normalized paths.
2. Trading (next 6 months): when the pair's normalized spread diverges beyond
   2 × its formation-period std, short the winner / long the loser (one unit
   each, dollar-neutral); unwind when the spread crosses zero; close all at
   the end of the trading window.
"""

from __future__ import annotations

import itertools

import numpy as np
import pandas as pd


def normalized_paths(prices: pd.DataFrame) -> pd.DataFrame:
    """Cumulative total-return index rebased to 1 at the window start."""
    return prices / prices.iloc[0]


def select_pairs(prices: pd.DataFrame, n_pairs: int = 5) -> list[tuple[str, str, float]]:
    """Rank all pairs by formation-window SSD; return the closest `n_pairs`
    as (stock_a, stock_b, spread_std)."""
    norm = normalized_paths(prices)
    scored = []
    for a, b in itertools.combinations(norm.columns, 2):
        spread = norm[a] - norm[b]
        scored.append((float((spread**2).sum()), a, b, float(spread.std())))
    scored.sort()
    return [(a, b, sd) for _, a, b, sd in scored[:n_pairs]]


def pair_positions(
    trade_prices: pd.DataFrame,
    a: str,
    b: str,
    spread_std: float,
    entry_z: float = 2.0,
) -> pd.DataFrame:
    """GGR trading rule for one pair over the trading window.

    Returns per-stock weights (+0.5/-0.5 when open, so one pair has unit
    gross exposure).
    """
    norm = normalized_paths(trade_prices[[a, b]])
    spread = norm[a] - norm[b]
    w = pd.DataFrame(0.0, index=trade_prices.index, columns=[a, b])
    open_dir = 0                                  # +1: long a/short b
    for t in range(len(spread)):
        s = spread.iloc[t]
        if open_dir == 0:
            if s > entry_z * spread_std:
                open_dir = -1                     # a rich → short a, long b
            elif s < -entry_z * spread_std:
                open_dir = 1
        elif open_dir == -1 and s <= 0:
            open_dir = 0
        elif open_dir == 1 and s >= 0:
            open_dir = 0
        w.iloc[t] = [0.5 * open_dir, -0.5 * open_dir]
    w.iloc[-1] = 0.0                              # close at window end
    return w


def pairs_portfolio_weights(
    prices: pd.DataFrame,
    formation_days: int = 252,
    trading_days: int = 126,
    n_pairs: int = 5,
    entry_z: float = 2.0,
) -> pd.DataFrame:
    """Rolling GGR implementation over the whole sample: non-overlapping
    formation/trading windows, weights averaged across the open pairs."""
    weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    start = 0
    while start + formation_days + trading_days <= len(prices):
        form = prices.iloc[start : start + formation_days]
        trade = prices.iloc[start + formation_days : start + formation_days + trading_days]
        for a, b, sd in select_pairs(form, n_pairs):
            if sd == 0:
                continue
            w = pair_positions(trade, a, b, sd, entry_z) / n_pairs
            weights.loc[w.index, [a, b]] += w
        start += trading_days
    return weights


def demo() -> pd.DataFrame:
    from backtest import backtest_portfolio, summarize
    from data import synthetic_daily, synthetic_pair

    # A cointegrated pair plus decoy assets the pair-selector must reject.
    pair = synthetic_pair(n_days=1500)
    noise = synthetic_daily(n_days=1500, n_assets=6, momentum=0.0, seed=42)
    prices = pd.concat([pair, noise], axis=1)
    w = pairs_portfolio_weights(prices, n_pairs=2)
    res = backtest_portfolio(prices, w, cost_bps=5)
    return pd.DataFrame([summarize(res, "GGR pairs (top 2, 2-sigma entry)")])


if __name__ == "__main__":
    print(demo().round(3))
