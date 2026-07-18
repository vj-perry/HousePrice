# Trading Strategies — Research-Based Python Implementations

Educational implementations of the day-trading / short-horizon strategy
literature, one module per research strand. **This is research code for
backtesting and study, not investment advice.** The empirical literature
(Barber–Odean Taiwan studies; Chague, De-Losso & Giovannetti 2020, Brazil)
finds that the overwhelming majority of retail day traders lose money after
costs — see `backtest.py`, which charges transaction costs on every trade
for exactly that reason.

## Layout

| Module | Strategy family | Key paper(s) |
|---|---|---|
| `s1_technical_rules.py` | Moving-average crossover, trading-range breakout | Brock, Lakonishok & LeBaron (1992) |
| `s2_chart_patterns.py` | Kernel-smoothed chart patterns (head-and-shoulders, double top/bottom) | Lo, Mamaysky & Wang (2000) |
| `s3_intraday_momentum.py` | First half-hour return predicts last half-hour | Gao, Han, Li & Zhou (2018) |
| `s4_intraday_periodicity.py` | Same-interval-of-day cross-sectional momentum | Heston, Korajczyk & Sadka (2010) |
| `s5_momentum_reversal.py` | Cross-sectional momentum & short-term reversal | Jegadeesh & Titman (1993); Jegadeesh (1990); Lehmann (1990) |
| `s6_pairs_trading.py` | Distance-method pairs trading | Gatev, Goetzmann & Rouwenhorst (2006) |
| `s7_intraday_practitioner.py` | Opening-range breakout, gap fade, VWAP reversion | Practitioner strategies studied across the intraday literature |
| `backtest.py` | Shared vectorized backtest engine, costs, metrics | — |
| `data.py` | Synthetic data generators + optional `yfinance` loader | — |
| `run_all_demo.py` | Runs every strategy end-to-end on synthetic data | — |

## Quick start

```bash
pip install -r requirements.txt
python run_all_demo.py            # synthetic data, no network needed
```

To run on real data, install `yfinance` and use `data.load_yfinance()`:

```python
from data import load_yfinance
from s1_technical_rules import sma_crossover_positions
from backtest import backtest, summarize

prices = load_yfinance(["SPY"], start="2015-01-01")["SPY"]
pos = sma_crossover_positions(prices, fast=1, slow=50)
result = backtest(prices, pos, cost_bps=5)
print(summarize(result))
```

## Conventions

- **Positions** are Series/DataFrames of target exposure in [-1, 1],
  indexed like the price data, decided using information available *at*
  that timestamp and earning the *next* bar's return (no look-ahead).
- **Costs** are charged in basis points on each change in position
  (`|Δposition| × cost_bps`). Retail-realistic values are 5–20 bps per
  side for liquid US equities once spread + slippage are included.
- All returns are simple (not log) unless stated otherwise.
