"""Section 4 — Intraday cross-sectional periodicity ("same half-hour" effect).

Heston, Korajczyk & Sadka (2010), "Intraday Patterns in the Cross-Section of
Stock Returns", Journal of Finance 65(4).

Finding: a stock's return in a given half-hour interval predicts its return
in the *same* interval on subsequent days (peaks at exact multiples of the
13-bar trading day, persisting for ~40 trading days). The strategy is
cross-sectional: each interval, rank stocks by their return in that same
interval `lag_days` ago and go long the winners / short the losers.
"""

from __future__ import annotations

import pandas as pd


def interval_returns(intraday_close: pd.DataFrame) -> pd.DataFrame:
    """Per-interval returns for a panel of stocks.

    `intraday_close`: DatetimeIndex × one column per stock, regular intraday
    bars. Returns same shape, first bar of each day vs prior day's last bar.
    """
    return intraday_close.pct_change()


def same_interval_weights(
    intraday_close: pd.DataFrame,
    bars_per_day: int = 13,
    lag_days: int = 1,
    quantile: float = 0.2,
) -> pd.DataFrame:
    """Long-short weights from the same interval `lag_days` days ago.

    Each timestamp: signal = that stock's return in the same interval
    `lag_days` trading days earlier. Long the top `quantile`, short the
    bottom `quantile`, equal-weighted, dollar-neutral, unit gross exposure.
    """
    rets = interval_returns(intraday_close)
    signal = rets.shift(bars_per_day * lag_days)
    ranks = signal.rank(axis=1, pct=True)
    long = (ranks >= 1 - quantile).astype(float)
    short = (ranks <= quantile).astype(float)
    n_long = long.sum(axis=1).replace(0, pd.NA)
    n_short = short.sum(axis=1).replace(0, pd.NA)
    weights = long.div(n_long, axis=0).fillna(0) * 0.5 - short.div(
        n_short, axis=0
    ).fillna(0) * 0.5
    return weights.fillna(0.0)


def periodicity_profile(
    intraday_close: pd.DataFrame, bars_per_day: int = 13, max_lag_days: int = 5
) -> pd.Series:
    """HKS's diagnostic: cross-sectional correlation of interval returns with
    their own lags, averaged over time, at daily multiples. Spikes at
    multiples of `bars_per_day` reproduce the paper's Figure 1 signature.
    """
    rets = interval_returns(intraday_close)
    out = {}
    for d in range(1, max_lag_days + 1):
        lagged = rets.shift(bars_per_day * d)
        corr = rets.corrwith(lagged, axis=1).mean()
        out[f"lag_{d}d"] = corr
    return pd.Series(out)


def demo() -> pd.DataFrame:
    import numpy as np

    from backtest import backtest_portfolio, summarize
    from data import synthetic_intraday

    # Build a small panel: each stock gets its own intraday series with a
    # persistent stock-specific interval pattern injected.
    rng = np.random.default_rng(5)
    panel = {}
    for i in range(8):
        px = synthetic_intraday(n_days=250, seed=100 + i)["close"]
        pattern = rng.normal(0, 0.0012, 13)       # stock's half-hour signature
        tiled = np.tile(pattern, len(px) // 13 + 1)[: len(px)]
        panel[f"S{i}"] = px * np.exp(np.cumsum(tiled))
    prices = pd.DataFrame(panel)

    print("Same-interval cross-correlation by lag (should spike at all lags):")
    print(periodicity_profile(prices).round(4).to_string())

    w = same_interval_weights(prices)
    res = backtest_portfolio(prices, w, cost_bps=2, periods_per_year=252 * 13)
    return pd.DataFrame([summarize(res, "HKS same-interval L/S")])


if __name__ == "__main__":
    print(demo().round(3))
