"""Section 7 — Practitioner intraday triggers studied in the literature.

These are the strategies retail day traders most commonly run, and the ones
whose aggregate outcomes the profitability literature (Jordan & Diltz 2003;
Barber, Lee, Liu & Odean 2004/2014; Chague, De-Losso & Giovannetti 2020)
measures. Included so the package covers what is actually traded, with the
same cost-aware backtesting as the academic sections:

1. Opening-range breakout (ORB): trade a break of the first N minutes' range.
2. Overnight-gap fade: fade large opening gaps (intraday reversal evidence,
   e.g. Grant, Wolf & Yu 2005).
3. VWAP mean reversion: fade large intraday deviations from session VWAP.

All operate on intraday OHLC-free bar closes (volume optional for VWAP) and
return per-bar positions closed by end of session — no overnight risk.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _session_groups(index: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(index.normalize(), index=index)


def opening_range_breakout_positions(
    intraday_close: pd.Series,
    opening_bars: int = 1,
    stop_frac: float = 0.5,
) -> pd.Series:
    """Opening-range breakout, long-short, flat by the close.

    The first `opening_bars` bars define the range. A close above the range
    high opens a long; below the range low, a short. The position exits if
    price retraces `stop_frac` of the range against it, and always closes on
    the session's last bar.
    """
    pos = pd.Series(0.0, index=intraday_close.index)
    for _, day in intraday_close.groupby(_session_groups(intraday_close.index)):
        if len(day) <= opening_bars + 1:
            continue
        rng_hi = day.iloc[:opening_bars].max()
        rng_lo = day.iloc[:opening_bars].min()
        rng = max(rng_hi - rng_lo, 1e-12)
        state = 0.0
        for i in range(opening_bars, len(day) - 1):
            px = day.iloc[i]
            if state == 0.0:
                if px > rng_hi:
                    state = 1.0
                elif px < rng_lo:
                    state = -1.0
            elif state == 1.0 and px < rng_hi - stop_frac * rng:
                state = 0.0
            elif state == -1.0 and px > rng_lo + stop_frac * rng:
                state = 0.0
            pos.loc[day.index[i]] = state
        pos.loc[day.index[-1]] = 0.0
    return pos


def gap_fade_positions(
    intraday_close: pd.Series,
    gap_threshold: float = 0.005,
    exit_bar: int = 6,
) -> pd.Series:
    """Fade overnight gaps larger than `gap_threshold`.

    Short after an up-gap, long after a down-gap, from the first bar's close;
    exit at `exit_bar` bars into the session (or when the gap fills is a
    common variant — the fixed-time exit keeps this vectorizable and honest).
    """
    pos = pd.Series(0.0, index=intraday_close.index)
    prev_close = None
    for _, day in intraday_close.groupby(_session_groups(intraday_close.index)):
        if prev_close is not None and len(day) > exit_bar:
            gap = day.iloc[0] / prev_close - 1
            if abs(gap) > gap_threshold:
                pos.loc[day.index[1:exit_bar]] = -np.sign(gap)
        prev_close = day.iloc[-1]
    return pos


def vwap_reversion_positions(
    intraday_close: pd.Series,
    volume: pd.Series | None = None,
    band: float = 0.005,
    warmup_bars: int = 3,
) -> pd.Series:
    """Fade deviations from the running session VWAP beyond `band`.

    Long when price < VWAP × (1 − band), short when price > VWAP × (1 + band),
    flat once price re-touches VWAP; always flat at the close. With no volume
    series, a running mean price (TWAP) stands in for VWAP.
    """
    if volume is None:
        volume = pd.Series(1.0, index=intraday_close.index)
    pos = pd.Series(0.0, index=intraday_close.index)
    df = pd.DataFrame({"px": intraday_close, "vol": volume})
    for _, day in df.groupby(_session_groups(df.index)):
        pv = (day["px"] * day["vol"]).cumsum()
        vwap = pv / day["vol"].cumsum()
        state = 0.0
        for i in range(warmup_bars, len(day) - 1):
            px, vw = day["px"].iloc[i], vwap.iloc[i]
            if state == 0.0:
                if px < vw * (1 - band):
                    state = 1.0
                elif px > vw * (1 + band):
                    state = -1.0
            elif (state == 1.0 and px >= vw) or (state == -1.0 and px <= vw):
                state = 0.0
            pos.loc[day.index[i]] = state
        pos.loc[day.index[-1]] = 0.0
    return pos


def demo() -> pd.DataFrame:
    from backtest import backtest, summarize
    from data import synthetic_intraday

    px = synthetic_intraday(n_days=250)["close"]
    bars_year = 252 * 13
    rows = []
    for name, fn in [
        ("ORB (first bar range)", lambda p: opening_range_breakout_positions(p)),
        ("Gap fade (>0.5%)", lambda p: gap_fade_positions(p)),
        ("VWAP reversion (0.5% band)", lambda p: vwap_reversion_positions(p)),
    ]:
        res = backtest(px, fn(px), cost_bps=5, periods_per_year=bars_year)
        rows.append(summarize(res, name))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    print(demo().round(3))
