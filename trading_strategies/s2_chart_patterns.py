"""Section 2 — Kernel-smoothed chart pattern detection.

Lo, Mamaysky & Wang (2000), "Foundations of Technical Analysis", Journal of
Finance 55(4).

The paper's method:
1. Smooth prices with a Nadaraya-Watson kernel regression (Gaussian kernel,
   bandwidth chosen slightly below cross-validation optimal so genuine
   extrema survive).
2. Find local extrema of the smoothed curve.
3. Classify sequences of 5 consecutive extrema into patterns — implemented
   here: head-and-shoulders (HS), inverse head-and-shoulders (IHS), and
   double top / double bottom — using the paper's tolerance definitions
   (shoulders/tops within 1.5% of each other's mean).

Signals: a completed bearish pattern (HS, double top) → short; a completed
bullish pattern (IHS, double bottom) → long; positions held `hold_days` bars.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def kernel_smooth(prices: pd.Series, bandwidth: float | None = None) -> pd.Series:
    """Nadaraya-Watson Gaussian kernel regression over time index 0..n-1."""
    y = prices.to_numpy(dtype=float)
    n = len(y)
    x = np.arange(n, dtype=float)
    if bandwidth is None:
        # LMW use ~0.3 × the cross-validation bandwidth; this heuristic
        # tracks their choice's order of magnitude for daily data.
        bandwidth = max(2.0, 0.3 * n ** 0.2 * 3)
    diffs = (x[:, None] - x[None, :]) / bandwidth
    w = np.exp(-0.5 * diffs**2)
    smoothed = (w * y[None, :]).sum(axis=1) / w.sum(axis=1)
    return pd.Series(smoothed, index=prices.index)


def local_extrema(smoothed: pd.Series) -> list[tuple[int, float, str]]:
    """Return (index_position, value, 'max'|'min') for interior local extrema."""
    v = smoothed.to_numpy()
    out = []
    for i in range(1, len(v) - 1):
        if v[i] > v[i - 1] and v[i] > v[i + 1]:
            out.append((i, v[i], "max"))
        elif v[i] < v[i - 1] and v[i] < v[i + 1]:
            out.append((i, v[i], "min"))
    return out


def _within(a: float, b: float, tol: float) -> bool:
    m = (a + b) / 2
    return abs(a - b) <= tol * abs(m)


def classify_window(extrema: list[tuple[int, float, str]], tol: float = 0.015) -> str | None:
    """Classify the last 5 extrema per LMW definitions. Returns pattern or None."""
    if len(extrema) < 5:
        return None
    e = extrema[-5:]
    vals = [v for _, v, _ in e]
    kinds = [k for _, _, k in e]
    if kinds == ["max", "min", "max", "min", "max"]:
        e1, _, e3, _, e5 = vals
        if e3 > e1 and e3 > e5 and _within(e1, e5, tol):
            return "head_and_shoulders"          # bearish
        if _within(e1, e3, tol) or _within(e3, e5, tol):
            return "double_top"                  # bearish (adjacent equal tops)
    if kinds == ["min", "max", "min", "max", "min"]:
        e1, _, e3, _, e5 = vals
        if e3 < e1 and e3 < e5 and _within(e1, e5, tol):
            return "inverse_head_and_shoulders"  # bullish
        if _within(e1, e3, tol) or _within(e3, e5, tol):
            return "double_bottom"               # bullish
    return None


BULLISH = {"inverse_head_and_shoulders", "double_bottom"}
BEARISH = {"head_and_shoulders", "double_top"}


def pattern_positions(
    prices: pd.Series,
    window: int = 38,
    hold_days: int = 5,
    tol: float = 0.015,
) -> pd.Series:
    """Rolling pattern detection (LMW use a 38-day window for daily data).

    Each day, smooth the trailing `window` of prices, extract extrema, and if
    the final extremum completed within the last 3 bars and the last five
    extrema form a pattern, open a position for `hold_days` bars.
    """
    pos = pd.Series(0.0, index=prices.index)
    hold_until = -1
    current = 0.0
    for t in range(window, len(prices)):
        if t <= hold_until:
            pos.iloc[t] = current
            continue
        current = 0.0
        seg = prices.iloc[t - window : t]
        ext = local_extrema(kernel_smooth(seg))
        if ext and ext[-1][0] >= window - 4:      # pattern just completed
            pat = classify_window(ext, tol)
            if pat in BULLISH:
                current, hold_until = 1.0, t + hold_days
            elif pat in BEARISH:
                current, hold_until = -1.0, t + hold_days
        pos.iloc[t] = current
    return pos


def demo() -> pd.DataFrame:
    from backtest import backtest, summarize
    from data import synthetic_daily

    px = synthetic_daily(n_days=1500, n_assets=1, seed=21)["A00"]
    res = backtest(px, pattern_positions(px), cost_bps=5)
    return pd.DataFrame([summarize(res, "LMW patterns (38d window)")])


if __name__ == "__main__":
    print(demo().round(3))
