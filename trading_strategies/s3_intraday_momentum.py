"""Section 3 — Market intraday momentum (first half-hour → last half-hour).

Gao, Han, Li & Zhou (2018), "Market Intraday Momentum", Journal of Financial
Economics 129(2).

Finding: the market's return in the first 30 minutes of the session (including
the overnight gap) positively predicts its return in the last 30 minutes,
especially on high-volatility and high-volume days. The trading rule is
simple timing: at 15:30, take a position in the direction of the first
half-hour return and close at 16:00 — one round trip per day.

This module works on a DataFrame of intraday bar closes with a DatetimeIndex
(see `data.synthetic_intraday` for the expected shape).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def session_first_last_returns(intraday_close: pd.Series) -> pd.DataFrame:
    """Per-session first-bar and last-bar returns.

    First-bar return includes the overnight move (prev session close → end of
    first bar), matching the paper's definition.
    """
    df = intraday_close.to_frame("close")
    df["date"] = df.index.normalize()
    by_day = df.groupby("date")["close"]
    first_close = by_day.first()
    last_close = by_day.last()
    second_last = by_day.agg(lambda s: s.iloc[-2] if len(s) > 1 else np.nan)
    prev_close = last_close.shift(1)
    out = pd.DataFrame(
        {
            "r_first": first_close / prev_close - 1,
            "r_last": last_close / second_last - 1,
        }
    )
    return out.dropna()


def intraday_momentum_daily_returns(
    intraday_close: pd.Series,
    cost_bps: float = 5.0,
    scale: bool = False,
) -> pd.Series:
    """Daily strategy returns for the Gao et al. timing rule.

    Each session: position = sign(first half-hour return), held only for the
    last bar; costs charge one round trip (2 × cost_bps) per active day.
    If `scale`, position size is |r_first| / trailing-60-day mean |r_first|,
    capped at 2 — a volatility-responsive variant discussed in the paper.
    """
    sess = session_first_last_returns(intraday_close)
    signal = np.sign(sess["r_first"])
    if scale:
        base = sess["r_first"].abs().rolling(60).mean()
        size = (sess["r_first"].abs() / base).clip(upper=2.0).fillna(1.0)
        signal = signal * size
    gross = signal * sess["r_last"]
    costs = signal.abs() * 2 * (cost_bps / 1e4)
    return (gross - costs).rename("intraday_momentum")


def predictive_regression(intraday_close: pd.Series) -> pd.Series:
    """The paper's headline regression: r_last ~ a + b * r_first.

    Returns slope, t-stat and R² so users can check whether the effect exists
    in their own data before trading it.
    """
    sess = session_first_last_returns(intraday_close)
    x, y = sess["r_first"].to_numpy(), sess["r_last"].to_numpy()
    x1 = np.column_stack([np.ones_like(x), x])
    beta, *_ = np.linalg.lstsq(x1, y, rcond=None)
    resid = y - x1 @ beta
    dof = len(y) - 2
    se = np.sqrt(resid @ resid / dof * np.linalg.inv(x1.T @ x1)[1, 1])
    r2 = 1 - (resid @ resid) / ((y - y.mean()) @ (y - y.mean()))
    return pd.Series(
        {"slope": beta[1], "t_stat": beta[1] / se, "r_squared": r2, "n_days": len(y)}
    )


def demo() -> pd.DataFrame:
    from backtest import BacktestResult, summarize
    from data import synthetic_intraday

    px = synthetic_intraday()["close"]
    print("Predictive regression (r_last on r_first):")
    print(predictive_regression(px).round(4).to_string())
    rows = []
    for bps in (0.5, 5.0):        # futures/ETF-level costs vs retail equity costs
        gross = intraday_momentum_daily_returns(px, cost_bps=0)
        net = intraday_momentum_daily_returns(px, cost_bps=bps)
        res = BacktestResult(
            returns=net,
            gross_returns=gross,
            positions=pd.Series(1.0, index=net.index),
            costs=gross - net,
        )
        rows.append(summarize(res, f"Gao et al. intraday momentum ({bps}bps)"))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    print(demo().round(3))
