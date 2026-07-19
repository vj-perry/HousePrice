"""Standardized 30-day evaluation harness.

Answers one question for every strategy in the package, on identical terms:
"if this strategy was run every session at the market open for the past 30
trading days, what would the P&L have been, and how does it compare?"

Protocol
--------
- Notional: $100,000 gross exposure per strategy.
- Window: the most recent 30 trading days in the data. History before the
  window is used only for signal formation (moving averages, pair formation,
  momentum lookbacks), never for evaluation.
- Costs: 5 bps one-way on every change in position (retail-realistic for
  liquid US large caps once spread + slippage are included).
- Metrics: total P&L ($), annualized Sharpe of daily P&L, max drawdown (%),
  daily hit rate, total cost drag ($), average gross exposure. Sharpe is the
  primary cross-strategy comparison number because it is exposure- and
  scale-independent; P&L alone rewards whichever strategy happens to run the
  most risk. 30 observations is a small sample — treat every number as one
  draw, not an expectation (a strategy needs roughly 3 years of daily data
  for a Sharpe of 1 to be statistically distinguishable from zero).

Data
----
`--real` pulls from Yahoo Finance via yfinance (requires network access):
daily history for a 20-name large-cap panel and 30-minute bars for SPY and
an 8-name intraday panel. Without `--real` (or if the download fails), the
synthetic generators from `data.py` are used and the output is labeled
SYNTHETIC — plumbing check only, not a market result.

Usage
-----
    python3 backtest_30d.py            # synthetic
    python3 backtest_30d.py --real     # real data via yfinance
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from backtest import backtest, backtest_portfolio, max_drawdown, sharpe_ratio
from s1_technical_rules import sma_crossover_positions, trading_range_breakout_positions
from s2_chart_patterns import pattern_positions
from s3_intraday_momentum import intraday_momentum_daily_returns
from s4_intraday_periodicity import same_interval_weights
from s5_momentum_reversal import momentum_weights, reversal_weights
from s6_pairs_trading import pair_positions, select_pairs
from s7_intraday_practitioner import (
    gap_fade_positions,
    opening_range_breakout_positions,
    vwap_reversion_positions,
)

NOTIONAL = 100_000.0
WINDOW = 30            # trading days evaluated
COST_BPS = 5.0
DAILY_TICKERS = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "JPM", "V", "UNH",
    "XOM", "JNJ", "PG", "HD", "MA", "BAC", "KO", "PEP", "WMT", "DIS",
]
INTRADAY_TICKERS = ["SPY", "AAPL", "MSFT", "AMZN", "NVDA", "JPM", "XOM", "TSLA"]


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------

def load_data(real: bool):
    """Return (daily_panel, intraday_panel, label)."""
    if real:
        try:
            from data import load_yfinance

            daily = load_yfinance(DAILY_TICKERS, start="2023-01-01").dropna()
            intraday = load_yfinance(INTRADAY_TICKERS, interval="30m",
                                     start=None)  # yfinance caps 30m at 60d
            intraday = intraday.dropna()
            return daily, intraday, "REAL (Yahoo Finance)"
        except Exception as e:  # noqa: BLE001 - any failure falls back
            print(f"[warn] real-data download failed ({e}); using synthetic.\n")
    from data import synthetic_daily, synthetic_intraday, synthetic_pair

    daily = synthetic_daily(n_days=500, n_assets=18, seed=7)
    daily = pd.concat([daily, synthetic_pair(n_days=500, seed=11)], axis=1)
    panel = {}
    for i, name in enumerate(INTRADAY_TICKERS):
        panel[name] = synthetic_intraday(n_days=60, seed=200 + i)["close"]
    return daily, pd.DataFrame(panel), "SYNTHETIC (plumbing check only)"


# ---------------------------------------------------------------------------
# Per-strategy daily net-return series over the evaluation window
# ---------------------------------------------------------------------------

def _last_sessions(intraday: pd.DataFrame, n: int) -> pd.DataFrame:
    days = intraday.index.normalize().unique().sort_values()
    return intraday[intraday.index.normalize().isin(days[-n:])]


def _daily_from_bars(bar_returns: pd.Series) -> pd.Series:
    return bar_returns.groupby(bar_returns.index.normalize()).sum()


def strategy_daily_returns(daily: pd.DataFrame, intraday: pd.DataFrame) -> dict[str, pd.Series]:
    """Net daily return series (fraction of notional) per strategy, full
    sample; the harness slices the evaluation window afterwards."""
    out: dict[str, pd.Series] = {}
    bench = daily.iloc[:, 0]

    out["S1 VMA(1,50) crossover"] = backtest(
        bench, sma_crossover_positions(bench, 1, 50), COST_BPS
    ).returns
    out["S1 Range breakout (50d)"] = backtest(
        bench, trading_range_breakout_positions(bench, 50), COST_BPS
    ).returns
    out["S2 LMW chart patterns"] = backtest(
        bench, pattern_positions(bench), COST_BPS
    ).returns

    spy_bars = intraday.iloc[:, 0]
    out["S3 Intraday momentum"] = intraday_momentum_daily_returns(spy_bars, COST_BPS)

    w = same_interval_weights(intraday)
    res = backtest_portfolio(intraday, w, cost_bps=COST_BPS, periods_per_year=252 * 13)
    out["S4 Same-interval L/S"] = _daily_from_bars(res.returns)

    out["S5 JT momentum 6-1"] = backtest_portfolio(
        daily, momentum_weights(daily), COST_BPS
    ).returns
    out["S5 Short-term reversal"] = backtest_portfolio(
        daily, reversal_weights(daily), COST_BPS
    ).returns

    # S6: form pairs on the year ending WINDOW days ago, trade the window.
    form = daily.iloc[-(252 + WINDOW):-WINDOW]
    trade = daily.iloc[-WINDOW:]
    weights = pd.DataFrame(0.0, index=trade.index, columns=daily.columns)
    pairs = select_pairs(form, n_pairs=2)
    for a, b, sd in pairs:
        if sd > 0:
            weights[[a, b]] += pair_positions(trade, a, b, sd) / len(pairs)
    out["S6 Pairs (top 2)"] = backtest_portfolio(trade, weights, COST_BPS).returns

    bars_year = 252 * 13
    for name, fn in [
        ("S7 Opening-range breakout", opening_range_breakout_positions),
        ("S7 Gap fade", gap_fade_positions),
        ("S7 VWAP reversion", vwap_reversion_positions),
    ]:
        res = backtest(spy_bars, fn(spy_bars), COST_BPS, periods_per_year=bars_year)
        out[name] = _daily_from_bars(res.returns)
    return out


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

def run(real: bool = False) -> pd.DataFrame:
    daily, intraday, label = load_data(real)
    intraday = _last_sessions(intraday, 60)
    series = strategy_daily_returns(daily, intraday)

    rows = []
    for name, rets in series.items():
        r = rets.dropna().iloc[-WINDOW:]
        if len(r) == 0:
            continue
        pnl = NOTIONAL * ((1 + r).prod() - 1)
        rows.append(
            pd.Series(
                {
                    "pnl_$": round(pnl, 0),
                    "sharpe_ann": round(sharpe_ratio(r), 2),
                    "max_dd_%": round(100 * max_drawdown(r), 2),
                    "hit_rate_%": round(100 * (r[r != 0] > 0).mean(), 1)
                    if (r != 0).any()
                    else 0.0,
                    "active_days": int((r != 0).sum()),
                },
                name=name,
            )
        )
    table = pd.DataFrame(rows).sort_values("sharpe_ann", ascending=False)
    print(f"30-trading-day evaluation — data: {label}")
    print(f"Notional ${NOTIONAL:,.0f}, costs {COST_BPS} bps one-way\n")
    print(table.to_string())
    print(
        "\nRead Sharpe first (risk-adjusted, comparable across strategies), "
        "then P&L. 30 days is one small sample, not an expectation."
    )
    return table


if __name__ == "__main__":
    run(real="--real" in sys.argv)
