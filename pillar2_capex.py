"""
Pillar 2: Hyperscaler capex guidance.

Three checks against SEC EDGAR, all free:

1. Earnings releases (8-K Item 2.02): every new one in the last 120 days is
   flagged YELLOW so it gets read. Guidance changes are announced here.
2. Capex trend (XBRL company concept): year-over-year growth in reported
   property/equipment purchases, on a year-to-date basis. A sharp slowdown
   versus the prior quarter is flagged YELLOW. This uses reported numbers,
   so it doesn't depend on how a filing words its guidance.
3. Keyword search across each company's 8-K/10-Q/10-K for capex-related
   phrases. Candidates only, always YELLOW ("go read this filing").

Nothing here judges whether a filing is a "downward revision" -- it surfaces
candidates for a human read. Never auto-RED.

Status: YELLOW when there is a candidate. UNKNOWN when a source failed and
nothing was found (the pillar couldn't check). GREEN only when every check ran
and found nothing.
"""
import time
import datetime as dt
import requests

import state
from config import SEC_USER_AGENT

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
FULLTEXT_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
CAPEX_CONCEPT_URL = ("https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}"
                     "/us-gaap/{concept}.json")
CAPEX_CONCEPTS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
]

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
# Earnings releases (8-K Item 2.02) are where capex guidance actually moves.
# 120 days covers the last full quarterly cycle.
EARNINGS_LOOKBACK_DAYS = 120
# Flag when YoY capex growth slows by more than this many percentage points
# versus the prior quarter, or turns negative. A heuristic for "read this",
# not a validated threshold -- tune it after the backtest.
CAPEX_SLOWDOWN_PTS = 15.0

HEADERS = {"User-Agent": SEC_USER_AGENT}
_YTD_MONTHS = {3, 6, 9, 12}  # Q1, H1, 9M, full year


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


def _recent_earnings_filings(cik):
    """Return recent 8-K filings that include Item 2.02 (results of operations)."""
    resp = requests.get(SUBMISSIONS_URL.format(cik=cik), headers=HEADERS, timeout=20)
    resp.raise_for_status()
    recent = resp.json()["filings"]["recent"]
    cutoff = (dt.date.today() - dt.timedelta(days=EARNINGS_LOOKBACK_DAYS)).isoformat()
    out = []
    for form, items, filed, adsh, doc in zip(
        recent["form"], recent["items"], recent["filingDate"],
        recent["accessionNumber"], recent["primaryDocument"],
    ):
        if form == "8-K" and "2.02" in items.split(",") and filed >= cutoff:
            out.append({"filed": filed, "adsh": adsh, "doc": doc})
    return out


def _capex_yoy(cik):
    """Year-over-year growth in YTD capex for the latest two reported quarters.

    Periods are matched on the actual start/end dates, not the XBRL fy/fp
    labels, which describe the filing and are not reliable for the period.

    Returns (latest_label, latest_yoy_pct, prior_yoy_pct, latest_ytd_usd_bn),
    or None if the filings don't contain a usable comparison.
    """
    # Companies tag the same cash-flow line with different concepts, and a
    # concept can go stale (Amazon's PP&E tag ends in 2017; its productive-assets
    # tag is current). Build each concept, then keep the one with the newest data.
    candidates = []
    for concept in CAPEX_CONCEPTS:
        url = CAPEX_CONCEPT_URL.format(cik=cik, concept=concept)
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 404:
            continue
        resp.raise_for_status()
        rows = resp.json().get("units", {}).get("USD", [])

        # Year-to-date periods only, by length: Q1 ~3 months, H1 ~6, 9M ~9.
        # Latest-filed value wins for each (start, end) pair.
        best = {}
        for r in rows:
            if r.get("form") not in ("10-Q", "10-K") or "start" not in r:
                continue
            start, end = dt.date.fromisoformat(r["start"]), dt.date.fromisoformat(r["end"])
            months = round((end - start).days / 30.44)
            if months not in _YTD_MONTHS:
                continue
            key = (start, end)
            if key not in best or r["filed"] > best[key]["filed"]:
                best[key] = {**r, "_months": months, "_end": end}
        if best:
            candidates.append(best)

    if not candidates:
        return None
    best = max(candidates, key=lambda b: max(v["_end"] for v in b.values()))
    latest = max(best.values(), key=lambda r: (r["_end"], r["filed"]))

    def same_period_last_year(r):
        target = r["_end"].replace(year=r["_end"].year - 1)
        matches = [v for v in best.values()
                   if v["_months"] == r["_months"] and abs((v["_end"] - target).days) <= 7]
        return matches[0] if matches else None

    def yoy_for(r):
        prev = same_period_last_year(r)
        if not prev or not prev["val"]:
            return None
        return (r["val"] / prev["val"] - 1) * 100

    latest_yoy = yoy_for(latest)
    if latest_yoy is None:
        return None
    # Prior quarter, two shapes: a year-to-date period one quarter shorter from
    # the same fiscal-year start, or a rolling period of the same length that
    # ends about a quarter earlier (Amazon's trailing-12-month figures).
    def is_prior(v):
        gap = (latest["_end"] - v["_end"]).days
        if v["_months"] == latest["_months"] - 3 and v["start"] == latest["start"] and 0 < gap <= 120:
            return True
        return v["_months"] == latest["_months"] and 75 <= gap <= 110

    earlier = [v for v in best.values() if is_prior(v)]
    prior_yoy = yoy_for(max(earlier, key=lambda r: r["_end"])) if earlier else None
    label = f"period ending {latest['_end'].isoformat()} ({latest['_months']}mo)"
    return label, latest_yoy, prior_yoy, latest["val"] / 1e9


def _search(cik, phrase, start_date, end_date):
    params = {
        "q": f'"{phrase}"',
        "forms": FORMS,
        "ciks": cik,
        "dateRange": "custom",
        "startdt": start_date,
        "enddt": end_date,
    }
    # EDGAR FTS intermittently 500s on cold queries under load; an immediate
    # retry almost always succeeds, so retry 5xx twice before giving up.
    for attempt in range(3):
        resp = requests.get(FULLTEXT_SEARCH_URL, params=params, headers=HEADERS, timeout=20)
        if resp.status_code >= 500 and attempt < 2:
            time.sleep(1)
            continue
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
            "status": "UNKNOWN",
            "findings": [f"WARN: could not reach SEC EDGAR ticker map ({e}); pillar not checked this run"],
        }

    end_date = dt.date.today().isoformat()
    start_date = (dt.date.today() - dt.timedelta(days=LOOKBACK_DAYS)).isoformat()

    for ticker in COMPANIES:
        cik = cik_map.get(ticker)
        if not cik:
            errors.append(f"no CIK found for {ticker}")
            continue

        # 1. Earnings releases (Item 2.02): every new one gets read.
        try:
            earnings = _recent_earnings_filings(cik)
        except Exception as e:
            errors.append(f"{ticker}/earnings: {e}")
            earnings = []
        for f in earnings:
            key = f"earnings:{f['adsh']}"
            if key in seen_ids:
                continue
            seen_ids.add(key)
            cik_num = str(int(cik))
            url = (f"https://www.sec.gov/Archives/edgar/data/{cik_num}/"
                   f"{f['adsh'].replace('-', '')}/{f['doc']}")
            new_hits.append({
                "ticker": ticker, "phrase": "earnings release (Item 2.02)", "form": "8-K",
                "filed": f["filed"], "adsh": f["adsh"], "url": url,
            })

        # 2. Capex trend: flag a sharp slowdown or a negative YoY, once per quarter.
        try:
            trend = _capex_yoy(cik)
        except Exception as e:
            errors.append(f"{ticker}/capex trend: {e}")
            trend = None
        if trend is None:
            errors.append(f"{ticker}/capex trend: no comparable year-over-year capex data")
        else:
            label, latest_yoy, prior_yoy, ytd_bn = trend
            slowed = latest_yoy < 0 or (prior_yoy is not None and prior_yoy - latest_yoy > CAPEX_SLOWDOWN_PTS)
            prior_txt = f"prior quarter {prior_yoy:+.1f}%" if prior_yoy is not None else "no prior quarter to compare"
            msg = f"{ticker} capex {label}: YTD ${ytd_bn:.1f}B, YoY {latest_yoy:+.1f}% ({prior_txt})"
            if slowed:
                findings.append(f"YELLOW: {msg} -- capex growth slowed; read the latest 10-Q/10-K")
            else:
                findings.append(f"OK: {msg}")

        # 3. Keyword search for capex-related language in filings.
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

    for h in new_hits:
        findings.append(
            f"YELLOW: {h['ticker']} {h['form']} filed {h['filed']} matches \"{h['phrase']}\" -- {h['url']}"
        )

    if any(f.startswith("YELLOW") for f in findings):
        status = "YELLOW"
    elif errors:
        status = "UNKNOWN"
    else:
        status = "GREEN"
        findings.append(f"OK: no new capex candidates across {', '.join(COMPANIES)}")

    if errors:
        findings.append(f"WARN: {len(errors)} check(s) failed or had no data, e.g. {errors[0]}")

    return {
        "pillar": "2: Hyperscaler Capex Guidance",
        "status": status,
        "findings": findings,
    }
