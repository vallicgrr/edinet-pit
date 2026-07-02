"""Fetch Toyota's (7203) point-in-time annual financials from EDINET.

Usage:
    export EDINET_API_KEY=...   # free key from https://api.edinet-fsa.go.jp/
    python examples/fetch_toyota.py

Annual securities reports are filed roughly 3 months after fiscal year end,
so for Toyota (March FYE) we scan the June filing lists. Scanning is one API
call per weekday — a one-month window takes ~20 calls with the default 0.3s
sleep, so expect this to run for ten seconds or so per year scanned.
"""
import datetime as dt
import json
import pathlib

import edinet_pit as ep

CODE = "7203"
OUT = pathlib.Path(__file__).parent / "output" / f"{CODE}.json"

# 1. Find the annual reports. Each June window catches one fiscal year.
docs = []
for year in (2022, 2023, 2024):
    found = ep.find_annual_reports(dt.date(year, 6, 1), dt.date(year, 6, 30),
                                   codes={CODE}, verbose=True)
    docs += found.get(CODE, [])
print(f"found {len(docs)} annual reports")

# 2. Download and extract the current-period (as-originally-reported) values.
#    Keep `submit` alongside — it's the actual filing date, which tells a
#    backtest when these numbers became knowable.
periods = []
for d in docs:
    p = ep.fetch_period_for_doc(d["docID"], fallback_period_end=d["period_end"])
    if p:
        p["submit"] = d["submit"]
        periods.append(p)
        print(f"  {p['period_end']}  filed {d['submit']}")

# 3. Cache the raw extraction (re-runnable without hitting the API again) …
OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(periods, ensure_ascii=False, indent=1))
print(f"saved {OUT}")

# 4. … and show it as yfinance-compatible DataFrames (needs pandas).
fin, bs, cf = ep.build_frames(periods)
print("\nIncome statement (as originally reported):")
print(fin)
