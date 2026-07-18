"""Run every strategy section end-to-end on synthetic data.

This is a plumbing check, not a performance claim: the synthetic generators
inject the effects each paper documents, so most demos should show a positive
gross edge — real-market results will be far weaker, and the day-trading
profitability literature (see README) says most people who trade these lose
money after costs.
"""

from __future__ import annotations

import pandas as pd

import s1_technical_rules
import s2_chart_patterns
import s3_intraday_momentum
import s4_intraday_periodicity
import s5_momentum_reversal
import s6_pairs_trading
import s7_intraday_practitioner

SECTIONS = [
    ("S1 Technical rules (Brock-Lakonishok-LeBaron 1992)", s1_technical_rules),
    ("S2 Chart patterns (Lo-Mamaysky-Wang 2000)", s2_chart_patterns),
    ("S3 Intraday momentum (Gao et al. 2018)", s3_intraday_momentum),
    ("S4 Intraday periodicity (Heston-Korajczyk-Sadka 2010)", s4_intraday_periodicity),
    ("S5 Momentum & reversal (Jegadeesh-Titman 1993 et al.)", s5_momentum_reversal),
    ("S6 Pairs trading (Gatev-Goetzmann-Rouwenhorst 2006)", s6_pairs_trading),
    ("S7 Practitioner intraday triggers (ORB / gap fade / VWAP)", s7_intraday_practitioner),
]


def main() -> None:
    pd.set_option("display.width", 120)
    all_rows = []
    for title, module in SECTIONS:
        print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")
        table = module.demo()
        print(table.round(3).to_string())
        all_rows.append(table)
    print(f"\n{'=' * 78}\nCombined summary (net of costs, synthetic data)\n{'=' * 78}")
    print(pd.concat(all_rows).round(3).to_string())


if __name__ == "__main__":
    main()
