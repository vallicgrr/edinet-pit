"""Network layer for the EDINET API v2 (daily filing-list scan, bulk-CSV download).

Get a free API key at https://api.edinet-fsa.go.jp/ and pass it as an argument
or set the EDINET_API_KEY environment variable.
"""
from __future__ import annotations

import io
import json
import os
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import timedelta

from .parse import DOC_TYPE_ANNUAL, extract_period, parse_csv

DOCS_URL = "https://api.edinet-fsa.go.jp/api/v2/documents.json"
DOC_URL = "https://api.edinet-fsa.go.jp/api/v2/documents/{docID}"


def get_key(key=None):
    """Resolve the API key: explicit argument first, then EDINET_API_KEY."""
    k = key or os.environ.get("EDINET_API_KEY")
    if not k:
        raise RuntimeError(
            "EDINET API key required (pass key= or set EDINET_API_KEY)")
    return k.strip()


def daterange(a, b):
    """Yield weekdays (Mon-Fri) from a to b as dates (EDINET has no weekend filings)."""
    d = a
    while d <= b:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def fetch_documents(date_str, key=None, retries=3):
    """Return the day's filing list (results array). type=2 (metadata + list)."""
    q = urllib.parse.urlencode(
        {"date": date_str, "type": 2, "Subscription-Key": get_key(key)})
    url = f"{DOCS_URL}?{q}"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                payload = json.loads(r.read().decode("utf-8"))
            return payload.get("results", [])
        except Exception:  # noqa: BLE001
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    return []


def find_annual_reports(date_from, date_to, key=None, codes=None,
                        sleep=0.3, verbose=False):
    """Collect annual securities reports (120) in the date range as
    code -> [{docID, period_end, submit}].

    EDINET has no cross-ticker search API, so this scans the daily filing
    lists. Pass codes to restrict to those 4-digit ticker codes. submit is
    the actual filing date, usable for as-of knowability checks in backtests.
    """
    key = get_key(key)
    want = set(codes) if codes else None
    out = {}
    for d in daterange(date_from, date_to):
        for x in fetch_documents(d.isoformat(), key):
            if x.get("docTypeCode") != DOC_TYPE_ANNUAL:
                continue
            sec = x.get("secCode")
            if not sec:
                continue
            code = sec[:-1] if len(sec) == 5 else sec
            if want and code not in want:
                continue
            out.setdefault(code, []).append({
                "docID": x.get("docID"),
                "period_end": x.get("periodEnd"),
                "submit": x.get("submitDateTime"),
            })
        if verbose:
            print(f"  scan {d}  codes={len(out)}", flush=True)
        time.sleep(sleep)
    return out


def _download_csv_zip(docID, key=None, retries=3):
    q = urllib.parse.urlencode(
        {"type": 5, "Subscription-Key": get_key(key)})   # type=5: bulk CSV
    url = DOC_URL.format(docID=docID) + "?" + q
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except Exception:  # noqa: BLE001
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    return b""


def _csv_from_zip(zip_bytes) -> bytes:
    """Pull the main CSV (jpcrp*; excludes audit jpaud*) out of a type=5 ZIP."""
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
    main = [n for n in names if "jpcrp" in n.lower()] or names
    return zf.read(main[0]) if main else b""


def fetch_period_for_doc(docID, key=None, fallback_period_end=None):
    """Download one docID -> parse -> extract its current period. None on failure/empty."""
    csv_bytes = _csv_from_zip(_download_csv_zip(docID, key))
    if not csv_bytes:
        return None
    return extract_period(parse_csv(csv_bytes), fallback_period_end)
