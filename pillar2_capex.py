"""
Pillar 2: Hyperscaler capex guidance.

Free earnings-call transcripts don't exist via API, so this scans the
authoritative free alternative instead: SEC EDGAR full-text search across
each hyperscaler's own 8-K/10-Q/10-K filings for capex-related keyword
phrases. This surfaces CANDIDATE filings for you to read -- it cannot judge
whether language constitutes a "downward revision," only that it exists.
Always flagged YELLOW (needs human read), never auto-RED.
"""
import time
import datetime as dt
import requests

import state
from config import SEC_USER_AGENT

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
FULLTEXT_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

COMPANIES = ["MSFT", "GOOGL", "AMZN", "META"]
KEYWORD_PHRASES = [
    "capex reduction",
    "slowing infrastructure spend",
    "data center optimization",
    "margin compression",
    "capital expenditure guidance",
]
FORMS = "8-K,10-Q,10-K"
LOOKBACK_DAYS = 45

HEADERS = {"User-Agent": SEC_USER_AGENT}


def _get_cik_map():
    cached = state.load("sec_ticker_ciks", default=None)
    if cached and (dt.datetime.now() - dt.datetime.fromisoformat(cached["fetched_at"])).days < 30:
        return cached["map"]

    resp = requests.get(TICKER_MAP_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    raw = resp.json()
    mapping = {}
    for row in raw.values():
        mapping[row["ticker"].upper()] = str(row["cik_str"]).zfill(10)

    state.save("sec_ticker_ciks", {"fetched_at": dt.datetime.now().isoformat(), "map": mapping})
    return mapping


def _search(cik, phrase, start_date, end_date):
    params = {
        "q": f'"{phrase}"',
        "forms": FORMS,
        "ciks": cik,
        "dateRange": "custom",
        "startdt": start_date,
        "enddt": end_date,
    }
    resp = requests.get(FULLTEXT_SEARCH_URL, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.json().get("hits", {}).get("hits", [])


def run():
    seen = state.load("capex_seen_filings", default={"ids": []})
    seen_ids = set(seen["ids"])

    findings = []
    new_hits = []
    errors = []

    try:
        cik_map = _get_cik_map()
    except Exception as e:
        return {
            "pillar": "2: Hyperscaler Capex Guidance",
            "status": "GREEN",
            "findings": [f"WARN: could not reach SEC EDGAR ticker map ({e}); skipped this run"],
        }

    end_date = dt.date.today().isoformat()
    start_date = (dt.date.today() - dt.timedelta(days=LOOKBACK_DAYS)).isoformat()

    for ticker in COMPANIES:
        cik = cik_map.get(ticker)
        if not cik:
            errors.append(f"no CIK found for {ticker}")
            continue
        for phrase in KEYWORD_PHRASES:
            try:
                hits = _search(cik, phrase, start_date, end_date)
            except Exception as e:
                errors.append(f"{ticker}/{phrase}: {e}")
                time.sleep(0.5)
                continue

            for hit in hits:
                src = hit.get("_source", {})
                hit_id = hit.get("_id", f"{ticker}-{phrase}-{src.get('adsh')}")
                if hit_id in seen_ids:
                    continue
                seen_ids.add(hit_id)
                adsh = src.get("adsh", "")
                form = src.get("file_type") or src.get("form", "?")
                filed = src.get("file_date", "?")
                cik_num = str(int(cik))
                url = (f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                       f"&CIK={cik_num}&type={form}&dateb=&owner=include&count=10")
                new_hits.append({
                    "ticker": ticker, "phrase": phrase, "form": form,
                    "filed": filed, "adsh": adsh, "url": url,
                })
            time.sleep(0.3)

    state.save("capex_seen_filings", {"ids": list(seen_ids)})

    if new_hits:
        for h in new_hits:
            findings.append(
                f"YELLOW: {h['ticker']} {h['form']} filed {h['filed']} matches \"{h['phrase']}\" -- {h['url']}"
            )
        status = "YELLOW"
    else:
        findings.append(f"OK: no new capex-keyword matches in the last {LOOKBACK_DAYS} days across {', '.join(COMPANIES)}")
        status = "GREEN"

    if errors:
        findings.append(f"WARN: {len(errors)} search error(s), e.g. {errors[0]}")

    return {
        "pillar": "2: Hyperscaler Capex Guidance",
        "status": status,
        "findings": findings,
    }
