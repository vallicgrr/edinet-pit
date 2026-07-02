# edinet-pit

**Point-in-time (as-originally-reported) annual financials for Japanese equities**, extracted from EDINET securities reports (有価証券報告書, XBRL). Built to eliminate restated-financials look-ahead bias in backtests.

日本語のREADMEは [README.ja.md](README.ja.md) にあります。

## Why

Historical financials from yfinance and similar sources are actually **current** numbers — restated and revised after the fact. Filtering by disclosure date doesn't help: the values themselves are not what investors saw at the time. This injects look-ahead bias into any fundamental backtest.

EDINET (Japan's regulatory filing system, the FSA's equivalent of SEC EDGAR) keeps each fiscal year's **original disclosure** as XBRL in the annual securities report (docTypeCode 120), free of charge. This library extracts only the current-period (`CurrentYear*`) context values from each report — so each fiscal year's numbers come from the report that disclosed them first, i.e. true point-in-time data. Restated prior-year (`Prior1Year*`) values carried in the following year's report are never picked up.

## Install

```
pip install edinet-pit            # zero dependencies (stdlib only)
pip install "edinet-pit[frames]"  # if you want pandas DataFrame output
```

## Usage

Get a free API key at the [EDINET API portal](https://api.edinet-fsa.go.jp/) and set it as the `EDINET_API_KEY` environment variable (or pass `key=` explicitly).

```python
import datetime as dt
import edinet_pit as ep

# 1. Collect annual reports by ticker code. EDINET has no cross-ticker search
#    API, so this scans the daily filing lists over the date range.
docs = ep.find_annual_reports(dt.date(2023, 6, 1), dt.date(2023, 6, 30),
                              codes={"7203"}, verbose=True)

# 2. Download each document and extract its current-period financials
periods = [ep.fetch_period_for_doc(d["docID"], fallback_period_end=d["period_end"])
           for d in docs["7203"]]

# 3. Build yfinance-compatible DataFrames (columns=period end, index=line item)
fin, bs, cf = ep.build_frames([p for p in periods if p])
print(fin.loc["Total Revenue"])
```

Each `find_annual_reports` entry carries `submit` — the actual filing date. Store it and you can decide whether a number was knowable as of any backtest date, which is more accurate than approximating with period-end plus a fixed lag.

The network layer (`client`) and the pure transformation layer (`parse`: CSV parsing → current-period extraction → frame assembly) are separated; the latter is unit-testable offline.

## Extracted line items

Revenue, operating income, net income, basic/diluted EPS, shares issued, shareholders' equity, cash and equivalents, current assets, current liabilities, total liabilities, long-term investments, interest-bearing debt (approximate aggregate), operating cash flow, and capex. Handles both the Japanese GAAP (jppfs) and IFRS (jpigp) taxonomies, plus a fallback for the filer-extension revenue tags large IFRS filers use.

Output labels are compatible with yfinance's `financials` / `balance_sheet` / `cashflow` frames (e.g. `"Total Revenue"`), so it drops into existing yfinance-based pipelines. If you don't need that, use the plain dicts returned by `extract_period`.

## Known limitations

- **Major line items only.** Niche items are unmapped (add tags to `ELEMENT_MAP` if you need them).
- **Consolidated-first, exact context match.** Some filers with unusual context naming (e.g. pure parent-only reporters) may be missed.
- **Interest-bearing debt is an approximation** — a sum of the main loan, bond, and lease-obligation tags, since no single tag exists.
- **The EDINET API only reaches back to around 2016.** Earlier filings use older taxonomies this library doesn't handle.
- **Annual reports only.** Quarterly reports and amended reports (docTypeCode 130) are excluded — amendments are excluded deliberately, to preserve original values.

## Background

Extracted from a long-running backtesting project on Japanese equities. A detailed write-up — including measured results on how much restated financials and survivorship bias distort backtests — is in preparation.

Provided as-is. Issues and PRs are welcome, but responses may be sporadic.

## License

MIT
