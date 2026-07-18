"""Section 5 — Cross-sectional momentum and short-term reversal.

- Jegadeesh & Titman (1993), "Returns to Buying Winners and Selling Losers",
  Journal of Finance 48(1): rank stocks on past J-month returns, hold winners
  minus losers for K months. Canonical J/K = 6/6 or 12/1; the most recent
  month is skipped to avoid the reversal effect below.
- Jegadeesh (1990) and Lehmann (1990): at short horizons (1 week - 1 month)
  returns *revert* — last week's losers beat last week's winners. This is the
  academic basis of most mean-reversion day/swing strategies.

Both are implemented as dollar-neutral, equal-weighted decile-style portfolios
over a daily price panel.
"""

from __future__ import annotations

import pandas as pd


def _long_short_weights(signal: pd.DataFrame, quantile: float, invert: bool = False) -> pd.DataFrame:
    """Equal-weight long top quantile, short bottom quantile; unit gross."""
    ranks = signal.rank(axis=1, pct=True)
    hi = (ranks >= 1 - quantile).astype(float)
    lo = (ranks <= quantile).astype(float)
    if invert:                                   # reversal: long losers
        hi, lo = lo, hi
    n_hi = hi.sum(axis=1).replace(0, pd.NA)
    n_lo = lo.sum(axis=1).replace(0, pd.NA)
    w = hi.div(n_hi, axis=0).fillna(0) * 0.5 - lo.div(n_lo, axis=0).fillna(0) * 0.5
    return w.fillna(0.0)


def momentum_weights(
    prices: pd.DataFrame,
    formation_days: int = 126,     # J ≈ 6 months
    skip_days: int = 21,           # skip most recent month (JT convention)
    rebalance_days: int = 21,      # K ≈ 1 month holding
    quantile: float = 0.2,
) -> pd.DataFrame:
    """Jegadeesh-Titman momentum: long past winners, short past losers."""
    past = prices.shift(skip_days).pct_change(formation_days - skip_days)
    w = _long_short_weights(past, quantile)
    # hold weights fixed between rebalance dates
    mask = pd.Series(range(len(w)), index=w.index) % rebalance_days == 0
    return w.where(mask, other=pd.NA).ffill().fillna(0.0)


def reversal_weights(
    prices: pd.DataFrame,
    formation_days: int = 5,       # ~1 week (Lehmann 1990)
    quantile: float = 0.2,
) -> pd.DataFrame:
    """Short-term reversal: long last week's losers, short its winners,
    re-formed daily."""
    past = prices.pct_change(formation_days)
    return _long_short_weights(past, quantile, invert=True)


def demo() -> pd.DataFrame:
    from backtest import backtest_portfolio, summarize
    from data import synthetic_daily

    prices = synthetic_daily(n_days=1500, n_assets=30)
    rows = []
    res = backtest_portfolio(prices, momentum_weights(prices), cost_bps=5)
    rows.append(summarize(res, "JT momentum 6-1 (monthly rebal)"))
    res = backtest_portfolio(prices, reversal_weights(prices), cost_bps=5)
    rows.append(summarize(res, "Short-term reversal (weekly formation)"))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    print(demo().round(3))
