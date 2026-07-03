"""
Pillar 3: Macro credit & Fed pivot, via FRED.

Metric 1: Fed funds target range (DFEDTARU/DFEDTARL). Trigger: the range
changes on a date that doesn't fall on (or within 2 days of) a scheduled
2026 FOMC decision date -- i.e. an emergency/unscheduled move.
Also surfaces T10Y2Y (10Y-2Y spread) as context, not a hard trigger.

Metric 2: BofA US High Yield OAS (BAMLH0A0HYM2). Trigger: spread widens by
more than 50bps versus ~1 month (21 trading days) prior.
"""
import datetime as dt
import requests

import state
from config import FRED_API_KEY

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"

# 2026 FOMC decision dates (second day of each meeting), per federalreserve.gov.
FOMC_2026_DATES = [
    dt.date(2026, 1, 28), dt.date(2026, 3, 18), dt.date(2026, 4, 29),
    dt.date(2026, 6, 17), dt.date(2026, 7, 29), dt.date(2026, 9, 16),
    dt.date(2026, 10, 28), dt.date(2026, 12, 9),
]

CREDIT_SPREAD_TRIGGER_BPS = 50


def _fetch_series(series_id, limit=40):
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }
    resp = requests.get(FRED_URL, params=params, timeout=20)
    resp.raise_for_status()
    obs = resp.json().get("observations", [])
    # Drop "." placeholder values FRED uses for missing data.
    return [o for o in obs if o.get("value") not in (None, ".")]


def _is_scheduled(check_date):
    return any(abs((check_date - d).days) <= 2 for d in FOMC_2026_DATES)


def _check_fed_funds_target():
    obs = _fetch_series("DFEDTARU", limit=10)
    if not obs:
        return "WARN: DFEDTARU unavailable this run", None
    latest = obs[0]
    latest_val = float(latest["value"])
    latest_date = dt.date.fromisoformat(latest["date"])

    prior = state.load("fed_funds_target", default=None)
    state.save("fed_funds_target", {"value": latest_val, "date": str(latest_date)})

    if prior is None:
        return f"OK: Fed funds target upper bound {latest_val:.2f}% (baseline recorded)", "GREEN"

    if prior["value"] != latest_val:
        if _is_scheduled(latest_date):
            return f"OK: Fed funds target changed to {latest_val:.2f}% on {latest_date} (scheduled FOMC date)", "GREEN"
        else:
            return (f"RED: Fed funds target changed to {latest_val:.2f}% on {latest_date} -- "
                    f"NOT a scheduled 2026 FOMC date, possible emergency move"), "RED"

    return f"OK: Fed funds target unchanged at {latest_val:.2f}%", "GREEN"


def _check_yield_curve():
    obs = _fetch_series("T10Y2Y", limit=5)
    if not obs:
        return "WARN: T10Y2Y unavailable this run"
    val = float(obs[0]["value"])
    note = "inverted" if val < 0 else "normal"
    return f"OK: 10Y-2Y spread {val:+.2f} ({note}) -- informational only, not a hard trigger"


def _check_credit_spread():
    obs = _fetch_series("BAMLH0A0HYM2", limit=40)
    if len(obs) < 22:
        return "WARN: insufficient BAMLH0A0HYM2 history this run", "GREEN"

    latest_val = float(obs[0]["value"])
    prior_val = float(obs[21]["value"])  # ~21 trading days back (1 month)
    delta_bps = (latest_val - prior_val) * 100

    if delta_bps > CREDIT_SPREAD_TRIGGER_BPS:
        return (f"RED: US HY OAS widened {delta_bps:.0f}bps over ~1 month "
                f"({prior_val:.2f}% -> {latest_val:.2f}%), trigger > {CREDIT_SPREAD_TRIGGER_BPS}bps"), "RED"
    return f"OK: US HY OAS {latest_val:.2f}% ({delta_bps:+.0f}bps over ~1 month)", "GREEN"


def run():
    findings = []
    status = "GREEN"

    try:
        msg, st = _check_fed_funds_target()
        findings.append(msg)
        if st == "RED":
            status = "RED"
    except Exception as e:
        findings.append(f"WARN: fed funds target check failed ({e})")

    try:
        findings.append(_check_yield_curve())
    except Exception as e:
        findings.append(f"WARN: yield curve check failed ({e})")

    try:
        msg, st = _check_credit_spread()
        findings.append(msg)
        if st == "RED":
            status = "RED"
    except Exception as e:
        findings.append(f"WARN: credit spread check failed ({e})")

    return {
        "pillar": "3: Macro Credit & Fed Pivot",
        "status": status,
        "findings": findings,
    }
