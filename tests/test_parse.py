"""Unit tests for the pure transformation layer (no network needed).

Fixtures mimic EDINET's CSV (UTF-16 TSV) format. Regression checks against
real data go through fetch_period_for_doc with a live API key (not in CI).
"""
import pandas as pd
import pytest

from edinet_pit.parse import (_to_float, build_frames, extract_period,
                              parse_csv)


def _tsv(rows):
    """[(element_id, context, value)] -> UTF-16 bytes in EDINET CSV format."""
    header = "\t".join(['"要素ID"', '"項目名"', '"コンテキストID"', '"相対年度"',
                        '"連結・個別"', '"期間・時点"', '"ユニットID"', '"単位"', '"値"'])
    lines = [header]
    for eid, ctx, val in rows:
        lines.append("\t".join([f'"{eid}"', '"x"', f'"{ctx}"', '"x"', '"x"',
                                '"x"', '"x"', '"JPY"', f'"{val}"']))
    return "\n".join(lines).encode("utf-16")


FIXTURE = _tsv([
    ("jpdei_cor:CurrentFiscalYearEndDate", "FilingDateInstant", "2023-03-31"),
    ("jppfs_cor:NetSales", "CurrentYearDuration", "1,000,000"),
    ("jppfs_cor:NetSales", "Prior1YearDuration", "900,000"),          # restated value -> ignored
    ("jppfs_cor:OperatingIncome", "CurrentYearDuration", "100,000"),
    ("jppfs_cor:ProfitLossAttributableToOwnersOfParent", "CurrentYearDuration", "70,000"),
    ("jppfs_cor:ShareholdersEquity", "CurrentYearInstant", "500,000"),
    ("jppfs_cor:ShortTermLoansPayable", "CurrentYearInstant", "30,000"),
    ("jppfs_cor:BondsPayable", "CurrentYearInstant", "20,000"),
    ("jppfs_cor:NetCashProvidedByUsedInOperatingActivities", "CurrentYearDuration", "80,000"),
])


def test_to_float():
    assert _to_float("1,234") == 1234.0
    assert _to_float("(500)") == -500.0
    assert _to_float("－") is None
    assert _to_float("") is None


def test_parse_csv_decodes_utf16_and_skips_header():
    rows = parse_csv(FIXTURE)
    assert rows[0]["element_id"] == "jpdei_cor:CurrentFiscalYearEndDate"
    assert all(r["element_id"] != "要素ID" for r in rows)


def test_extract_period_takes_current_context_only():
    p = extract_period(parse_csv(FIXTURE))
    assert p["period_end"] == "2023-03-31"
    assert p["fin"]["Total Revenue"] == 1_000_000    # not Prior1Year's 900,000
    assert p["fin"]["Net Income"] == 70_000
    assert p["bs"]["Stockholders Equity"] == 500_000
    assert p["bs"]["Total Debt"] == 50_000           # loans + bonds summed
    assert p["cf"]["Operating Cash Flow"] == 80_000


def test_extract_period_revenue_summary_fallback():
    data = _tsv([
        ("jpdei_cor:CurrentFiscalYearEndDate", "FilingDateInstant", "2023-03-31"),
        ("jpcrp030000-asr_E02144-000:OperatingRevenuesIFRSKeyFinancialData",
         "CurrentYearDuration", "37,154,298"),
    ])
    p = extract_period(parse_csv(data))
    assert p["fin"]["Total Revenue"] == 37_154_298


def test_extract_period_returns_none_when_empty():
    assert extract_period([]) is None
    assert extract_period(parse_csv(_tsv(
        [("jpdei_cor:CurrentFiscalYearEndDate", "FilingDateInstant", "2023-03-31")]))) is None


def test_build_frames_first_wins_and_aligns_columns():
    p1 = extract_period(parse_csv(FIXTURE))
    p2 = dict(p1, fin={"Total Revenue": 999.0})      # later entry, same period end -> must be ignored
    fin, bs, cf = build_frames([p1, p2])
    ts = pd.Timestamp("2023-03-31")
    assert fin.loc["Total Revenue", ts] == 1_000_000
    assert bs.loc["Total Debt", ts] == 50_000
    assert list(fin.columns) == [ts]


def test_build_frames_empty():
    assert build_frames([]) == (None, None, None)
    assert build_frames(None) == (None, None, None)
