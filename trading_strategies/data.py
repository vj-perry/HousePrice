"""Data helpers: synthetic generators (offline demos) and optional yfinance loader.

The synthetic generators deliberately inject the effects the papers document
(serial correlation, intraday U-shaped volatility, cointegrated pairs) so each
strategy demo has a signal to find. Real markets are far noisier — treat demo
numbers as plumbing checks, not performance claims.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def synthetic_daily(
    n_days: int = 2500,
    n_assets: int = 20,
    momentum: float = 0.03,
    seed: int = 7,
) -> pd.DataFrame:
    """Daily close prices for `n_assets` with mild return autocorrelation.

    Returns a DataFrame indexed by business day, one column per asset.
    """
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-02", periods=n_days)
    prices = {}
    for i in range(n_assets):
        drift = rng.normal(0.0003, 0.0002)
        vol = rng.uniform(0.01, 0.025)
        shocks = rng.normal(0, vol, n_days)
        rets = np.zeros(n_days)
        for t in range(1, n_days):
            rets[t] = drift + momentum * rets[t - 1] + shocks[t]
        prices[f"A{i:02d}"] = 100 * np.cumprod(1 + rets)
    return pd.DataFrame(prices, index=idx)


def synthetic_pair(n_days: int = 2500, seed: int = 11) -> pd.DataFrame:
    """Two cointegrated price series (for pairs trading demos)."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-02", periods=n_days)
    common = np.cumsum(rng.normal(0.0003, 0.012, n_days))
    spread = np.zeros(n_days)
    for t in range(1, n_days):                      # mean-reverting OU spread
        spread[t] = 0.97 * spread[t - 1] + rng.normal(0, 0.004)
    x = 100 * np.exp(common)
    y = 100 * np.exp(common + spread)
    return pd.DataFrame({"X": x, "Y": y}, index=idx)


def synthetic_intraday(
    n_days: int = 500,
    bars_per_day: int = 13,
    first_last_corr: float = 0.25,
    seed: int = 3,
) -> pd.DataFrame:
    """30-minute bars (13 per 6.5h US session) with two documented effects:

    - Gao et al. (2018): the last bar's return correlates with the first bar's.
    - U-shaped intraday volatility (high at open/close, low midday).

    Returns a DataFrame with a DatetimeIndex and a 'close' column.
    """
    rng = np.random.default_rng(seed)
    sessions = pd.bdate_range("2022-01-03", periods=n_days)
    vol_profile = 0.0018 + 0.0022 * np.abs(
        np.linspace(-1, 1, bars_per_day)
    ) ** 2  # U-shape
    rows, price = [], 100.0
    for day in sessions:
        times = pd.date_range(
            day + pd.Timedelta(hours=10), periods=bars_per_day, freq="30min"
        )
        rets = rng.normal(0, vol_profile)
        rets[-1] += first_last_corr * rets[0]       # intraday momentum effect
        for t, r in zip(times, rets):
            price *= 1 + r
            rows.append((t, price))
    out = pd.DataFrame(rows, columns=["time", "close"]).set_index("time")
    return out


def load_yfinance(tickers: list[str], start: str = "2015-01-01", interval: str = "1d"):
    """Load adjusted close prices from Yahoo Finance (requires `yfinance`).

    Returns a DataFrame of closes, one column per ticker.
    """
    try:
        import yfinance as yf
    except ImportError as e:  # pragma: no cover
        raise ImportError("pip install yfinance to load real data") from e
    data = yf.download(tickers, start=start, interval=interval, auto_adjust=True)
    closes = data["Close"]
    if isinstance(closes, pd.Series):
        closes = closes.to_frame(tickers[0])
    return closes.dropna(how="all")
