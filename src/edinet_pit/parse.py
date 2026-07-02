"""Pure transformation layer: extract as-originally-reported annual financials
from EDINET annual securities report CSVs (XBRL).

No network access required — fully unit-testable offline. Downloading is
handled by the client module.

Why "as originally reported":
  Historical financials from yfinance and similar sources are *current*
  numbers, i.e. restated/revised after the fact. Filtering by disclosure date
  doesn't fix this — the values themselves are not what investors saw at the
  time, which injects look-ahead bias into backtests (the "restated
  financials" problem).

  EDINET's annual securities reports (有価証券報告書, docTypeCode=120) keep
  each fiscal year's *original disclosure* as XBRL, free of charge. By taking
  only the current-period ("CurrentYear*") context values from each report, a
  fiscal year's numbers come from the report that disclosed them first — true
  point-in-time data. Restated prior-year ("Prior1Year*") values carried in
  the following year's report are never picked up.

Known limitations:
  - Major line items only (revenue / operating income / net income / EPS /
    shares issued / equity / cash / interest-bearing debt / operating CF /
    capex / current assets / current liabilities / total liabilities).
    Niche items are unmapped.
  - Consolidated-first with exact context matching. Filers with unusual
    context naming (e.g. pure parent-only reporters) may be missed.
  - Interest-bearing debt is an approximation: no single tag exists, so the
    main loan, bond, and lease-obligation tags are summed.
  - The EDINET API only reaches back to around 2016; earlier filings use
    older taxonomies this module doesn't handle.

Output labels are compatible with yfinance's financials/balance_sheet/cashflow
frames ("Total Revenue" etc.) so results drop into existing yfinance-based
pipelines. If you don't need that, use the plain dicts from extract_period.
"""
from __future__ import annotations

import re

DOC_TYPE_ANNUAL = "120"  # Annual securities report (original). Amended reports
                         # (130) are excluded to preserve original values.

# Main "current period, consolidated" contexts. Prior-year (Prior1Year*),
# parent-only (_NonConsolidatedMember), segment, and other derived contexts
# fail the exact match and are naturally excluded.
CURRENT_CONTEXTS = {"CurrentYearDuration", "CurrentYearInstant"}

FIN, BS, CF = "fin", "bs", "cf"

# EDINET element ID -> (statement, yfinance-compatible label).
# Where multiple tags (Japanese GAAP / IFRS) map to one label, first match wins.
ELEMENT_MAP = {
    # ── income statement ──
    "jppfs_cor:NetSales": (FIN, "Total Revenue"),
    "jppfs_cor:OperatingRevenue1": (FIN, "Total Revenue"),
    "jpigp_cor:RevenueIFRS": (FIN, "Total Revenue"),
    "jpigp_cor:NetSalesIFRS": (FIN, "Total Revenue"),
    "jppfs_cor:OperatingIncome": (FIN, "Operating Income"),
    "jpigp_cor:OperatingProfitLossIFRS": (FIN, "Operating Income"),
    "jppfs_cor:ProfitLossAttributableToOwnersOfParent": (FIN, "Net Income"),
    "jpigp_cor:ProfitLossAttributableToOwnersOfParentIFRS": (FIN, "Net Income"),
    # ── balance sheet ──
    "jppfs_cor:EquityAttributableToOwnersOfParent": (BS, "Stockholders Equity"),
    "jppfs_cor:ShareholdersEquity": (BS, "Stockholders Equity"),
    "jpigp_cor:EquityAttributableToOwnersOfParentIFRS": (BS, "Stockholders Equity"),
    "jppfs_cor:CashAndDeposits": (BS, "Cash Cash Equivalents And Short Term Investments"),
    "jpigp_cor:CashAndCashEquivalentsIFRS": (BS, "Cash Cash Equivalents And Short Term Investments"),
    "jppfs_cor:CurrentAssets": (BS, "Current Assets"),
    "jpigp_cor:CurrentAssetsIFRS": (BS, "Current Assets"),
    "jppfs_cor:CurrentLiabilities": (BS, "Current Liabilities"),
    "jpigp_cor:CurrentLiabilitiesIFRS": (BS, "Current Liabilities"),
    "jppfs_cor:Liabilities": (BS, "Total Liabilities"),
    "jpigp_cor:LiabilitiesIFRS": (BS, "Total Liabilities"),
    "jppfs_cor:InvestmentSecurities": (BS, "Long Term Investments"),
    # ── cash flow ──
    "jppfs_cor:NetCashProvidedByUsedInOperatingActivities": (CF, "Operating Cash Flow"),
    "jpigp_cor:NetCashProvidedByUsedInOperatingActivitiesIFRS": (CF, "Operating Cash Flow"),
    "jppfs_cor:PurchaseOfPropertyPlantAndEquipment": (CF, "Capital Expenditure"),
    "jpigp_cor:PurchaseOfPropertyPlantAndEquipmentIFRS": (CF, "Capital Expenditure"),
}

# Per-share and share-count tags from the "Summary of Business Results"
# (主要な経営指標等の推移) section — single values in the current-period
# context. IFRS filers use separate element IDs with an *IFRS* infix for
# summary EPS (confirmed with 7203 Toyota), so both variants are listed.
SUMMARY_MAP = {
    "jpcrp_cor:BasicEarningsLossPerShareSummaryOfBusinessResults": (FIN, "Basic EPS"),
    "jpcrp_cor:DilutedEarningsPerShareSummaryOfBusinessResults": (FIN, "Diluted EPS"),
    "jpcrp_cor:BasicEarningsLossPerShareIFRSSummaryOfBusinessResults": (FIN, "Basic EPS"),
    "jpcrp_cor:DilutedEarningsLossPerShareIFRSSummaryOfBusinessResults": (FIN, "Diluted EPS"),
    "jpcrp_cor:TotalNumberOfIssuedSharesSummaryOfBusinessResults": (BS, "Share Issued"),
    # Shares issued (voting-rights basis). Large IFRS filers sometimes lack
    # the summary share-count tag and only report this one.
    "jpcrp_cor:NumberOfSharesIssuedSharesVotingRights": (BS, "Share Issued"),
}

# Namespace-independent revenue fallback. Large IFRS filers disclose revenue
# under filer-extension element IDs (e.g. 7203:
# jpcrp030000-asr_E02144-000:OperatingRevenuesIFRSKeyFinancialData) that a
# fixed jpigp_cor map cannot catch. Match local names (after the colon) that
# end in a KeyFinancialData / SummaryOfBusinessResults revenue pattern in the
# current-period context, and use it only when no canonical tag was found.
REVENUE_SUMMARY_RE = re.compile(
    r"(?:NetSales|NetRevenues?|Revenues?|OperatingRevenues?)"
    r".*(?:KeyFinancialData|SummaryOfBusinessResults)$")

# Interest-bearing debt: no single tag exists, so sum the main loan, bond,
# and lease-obligation items into an approximate "Total Debt".
DEBT_TAGS = {
    "jppfs_cor:ShortTermLoansPayable",
    "jppfs_cor:CurrentPortionOfLongTermLoansPayable",
    "jppfs_cor:CurrentPortionOfBonds",
    "jppfs_cor:CommercialPapersLiabilities",
    "jppfs_cor:BondsPayable",
    "jppfs_cor:LongTermLoansPayable",
    "jppfs_cor:LeaseObligationsCL",
    "jppfs_cor:LeaseObligationsNCL",
}

FY_END_TAG = "jpdei_cor:CurrentFiscalYearEndDate"


def _local_name(element_id):
    return element_id.split(":")[-1]


def _to_float(s):
    """EDINET cell value -> float. Empty / '－' / '-' etc. become None.
    Parentheses mean negative; commas are stripped."""
    if s is None:
        return None
    s = s.strip().strip('"')
    if s in ("", "-", "－", "‐", "—", "NaN", "N/A"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "")
    try:
        f = float(s)
        return -f if neg else f
    except ValueError:
        return None


def _decode(data: bytes) -> str:
    """Decode an EDINET CSV (actually a UTF-16 TSV). Encodings are tried in turn."""
    for enc in ("utf-16", "utf-16-le", "utf-8-sig", "utf-8"):
        try:
            t = data.decode(enc)
            if "\t" in t:
                return t
        except (UnicodeError, LookupError):
            pass
    return data.decode("utf-8", errors="replace")


def parse_csv(data: bytes) -> list:
    """EDINET CSV (TSV) bytes -> [{element_id, context, unit, value}]."""
    rows = []
    for line in _decode(data).splitlines():
        if not line.strip():
            continue
        c = line.split("\t")
        if len(c) < 9 or c[0].strip('"') in ("要素ID", "element_id"):
            continue  # header / malformed row
        rows.append({"element_id": c[0].strip('"'), "context": c[2].strip('"'),
                     "unit": c[7].strip('"'), "value": c[8].strip('"')})
    return rows


def extract_period(rows, fallback_period_end=None):
    """Rows of one annual report -> {period_end, fin:{}, bs:{}, cf:{}} for its
    current period. Returns None if nothing extractable.

    Taking only current-period (CurrentYear*) context values is the
    point-in-time crux: restated prior-year (Prior1Year*) values in the
    following year's report fail the exact match and are never picked up.
    """
    got = {FIN: {}, BS: {}, CF: {}}
    debt, debt_seen = 0.0, False
    rev_summary = None                # revenue-summary fallback candidate (first wins)
    period_end = fallback_period_end
    for r in rows:
        eid, ctx, val = r["element_id"], r["context"], r["value"]
        if eid == FY_END_TAG and val.strip():
            period_end = val.strip()
            continue
        if ctx not in CURRENT_CONTEXTS:
            continue
        if eid in DEBT_TAGS:
            f = _to_float(val)
            if f is not None:
                debt += f
                debt_seen = True
            continue
        m = ELEMENT_MAP.get(eid) or SUMMARY_MAP.get(eid)
        if not m:
            if rev_summary is None and REVENUE_SUMMARY_RE.search(_local_name(eid)):
                rev_summary = _to_float(val)
            continue
        stmt, label = m
        f = _to_float(val)
        if f is not None:
            got[stmt].setdefault(label, f)     # first wins (Japanese GAAP preferred)
    if debt_seen:
        got[BS].setdefault("Total Debt", debt)
    if rev_summary is not None:
        got[FIN].setdefault("Total Revenue", rev_summary)   # only if no canonical tag
    if not period_end or not any(got.values()):
        return None
    return {"period_end": period_end, FIN: got[FIN], BS: got[BS], CF: got[CF]}


def build_frames(periods):
    """[extract_period(...)] -> yfinance-compatible (fin, bs, cf) DataFrames.
    Empty statements come back as None.

    columns=period-end Timestamps, index=labels. If the same period end
    appears more than once, the earlier entry (= the original report) wins.
    pandas is only needed when calling this function (optional dependency).
    """
    import pandas as pd
    by_end = {}
    for p in periods or []:
        if p and p.get("period_end"):
            by_end.setdefault(p["period_end"], p)   # first wins
    if not by_end:
        return None, None, None
    cols = sorted(by_end)

    def frame(stmt):
        labels = sorted({l for c in cols for l in by_end[c].get(stmt, {})})
        if not labels:
            return None
        data = {pd.Timestamp(c): {l: by_end[c].get(stmt, {}).get(l) for l in labels}
                for c in cols}
        return pd.DataFrame(data, index=labels)

    return frame(FIN), frame(BS), frame(CF)
