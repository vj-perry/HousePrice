"""Section 1 — Simple technical trading rules.

Brock, Lakonishok & LeBaron (1992), "Simple Technical Trading Rules and the
Stochastic Properties of Stock Returns", Journal of Finance 47(5).

The paper tests two families of rules on 90 years of Dow data:

1. Variable-length moving average (VMA): long when a fast MA is above a slow
   MA, short (or flat) otherwise. Their classic parameterizations include
   (1, 50), (1, 150), (5, 150), (1, 200), (2, 200).
2. Trading-range breakout (TRB): buy when price breaks above the rolling
   maximum of the previous N days, sell on a break below the rolling minimum.

Both are implemented with an optional percentage band `b` (the paper uses 1%)
to filter whipsaw signals near the trigger level.
"""

from __future__ import annotations

import pandas as pd

# Parameterizations tested in the original paper (fast, slow):
BLL_VMA_PARAMS = [(1, 50), (1, 150), (5, 150), (1, 200), (2, 200)]


def sma_crossover_positions(
    prices: pd.Series,
    fast: int = 1,
    slow: int = 50,
    band: float = 0.0,
    allow_short: bool = True,
) -> pd.Series:
    """Variable-length moving average rule (BLL 1992, VMA).

    Long when MA_fast > MA_slow * (1 + band); short/flat when
    MA_fast < MA_slow * (1 - band); inside the band, keep the prior position.
    """
    ma_fast = prices.rolling(fast).mean()
    ma_slow = prices.rolling(slow).mean()
    pos = pd.Series(float("nan"), index=prices.index)
    pos[ma_fast > ma_slow * (1 + band)] = 1.0
    pos[ma_fast < ma_slow * (1 - band)] = -1.0 if allow_short else 0.0
    return pos.ffill().fillna(0.0)


def trading_range_breakout_positions(
    prices: pd.Series,
    lookback: int = 50,
    band: float = 0.0,
    allow_short: bool = True,
) -> pd.Series:
    """Trading-range breakout rule (BLL 1992, TRB).

    Go long on a close above the previous `lookback`-day high (× (1+band)),
    go short/flat on a close below the previous `lookback`-day low; hold the
    position between signals.
    """
    prev_high = prices.rolling(lookback).max().shift(1)
    prev_low = prices.rolling(lookback).min().shift(1)
    pos = pd.Series(float("nan"), index=prices.index)
    pos[prices > prev_high * (1 + band)] = 1.0
    pos[prices < prev_low * (1 - band)] = -1.0 if allow_short else 0.0
    return pos.ffill().fillna(0.0)


def demo() -> pd.DataFrame:
    from backtest import backtest, summarize
    from data import synthetic_daily

    px = synthetic_daily(n_assets=1)["A00"]
    rows = []
    for fast, slow in BLL_VMA_PARAMS:
        res = backtest(px, sma_crossover_positions(px, fast, slow), cost_bps=5)
        rows.append(summarize(res, f"VMA({fast},{slow})"))
    res = backtest(px, trading_range_breakout_positions(px, 50), cost_bps=5)
    rows.append(summarize(res, "TRB(50)"))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    print(demo().round(3))
