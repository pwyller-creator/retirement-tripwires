"""
Pillar 3: Macro credit & Fed pivot, via FRED.

Metric 1: Fed funds target range (DFEDTARU). RED: the range changes on a
date that doesn't fall on (or within 2 days of) a scheduled FOMC decision
date -- an emergency/unscheduled move.

Metric 2: BofA US High Yield OAS (BAMLH0A0HYM2). YELLOW/RED: spread widens
more than 50bps over ~1 month (RED), or more than 75bps over ~3 months (YELLOW).

Metric 3: Sahm rule (UNRATE). RED: 3-month average unemployment is at least
0.5pt above its 12-month low. Historically this has fired near recessions.

Metric 4: Initial jobless claims (ICSA). YELLOW: 4-week average is more than
25% above its 52-week low.

Metric 5: Chicago Fed National Financial Conditions Index (NFCI). YELLOW:
above 0 (tighter than average conditions).

Metric 6: 10Y-2Y spread (T10Y2Y). YELLOW: the curve re-steepened to positive
after being inverted within the last year. Re-steepening after inversion is
the part that has historically mattered, not the inversion itself.

Metric 7: 10Y-3M spread (T10Y3M) -- the NY Fed's own recession-probability
model input. YELLOW: currently inverted, or re-steepened to positive after
an inversion within the last ~19 months. backtest.py (2026-10-08) found
this curve catches the same 4/8 drawdowns on both forms with a ~2.5x worse
false-alarm rate than the 10Y-2Y re-steepening signal above, so it stays
YELLOW rather than RED -- treat it as supplementary color, not a sharper
lead than metric 6.

Metric 8: Senior Loan Officer Opinion Survey, net % of banks tightening C&I
lending standards for large/middle-market firms (DRTSCILM). Quarterly.
YELLOW above 20%, RED above 40% (2001/2008/2020 each cleared 40%+).

All thresholds are untested heuristics. backtest.py measures them against
past drawdowns; tune them from that output, not from memory.

Status: a failed check or a stale FOMC list makes the pillar UNKNOWN. It is
never reported as GREEN.
"""
import datetime as dt
import time
import requests

import state
from config import FRED_API_KEY

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"

# FOMC decision dates (second day of each meeting), per federalreserve.gov.
# Must be updated every January. The check below warns when the current year
# is missing.
FOMC_DATES = [
    dt.date(2026, 1, 28), dt.date(2026, 3, 18), dt.date(2026, 4, 29),
    dt.date(2026, 6, 17), dt.date(2026, 7, 29), dt.date(2026, 9, 16),
    dt.date(2026, 10, 28), dt.date(2026, 12, 9),
]

CREDIT_SPREAD_TRIGGER_BPS = 50      # 1-month widening -> RED
CREDIT_SPREAD_3M_TRIGGER_BPS = 75   # 3-month widening -> YELLOW
SAHM_TRIGGER_PTS = 0.5
CLAIMS_TRIGGER_RATIO = 1.25
CURVE_LOOKBACK_OBS = 252            # ~1 year of trading days
CURVE_3M10Y_LOOKBACK_OBS = 400      # ~19 months of trading days; this curve's inversions run longer
LENDING_STANDARDS_YELLOW_PCT = 20
LENDING_STANDARDS_RED_PCT = 40


def _fetch_series(series_id, limit=40):
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }
    # FRED intermittently 5xxs (502 seen 2026-09-29); back off and retry
    # before giving up so a check isn't silently skipped.
    for attempt in range(4):
        try:
            resp = requests.get(FRED_URL, params=params, timeout=20)
        except (requests.ConnectionError, requests.Timeout):
            if attempt < 3:
                time.sleep(2 ** attempt * 2)
                continue
            raise
        if resp.status_code >= 500 and attempt < 3:
            time.sleep(2 ** attempt * 2)
            continue
        resp.raise_for_status()
        break
    obs = resp.json().get("observations", [])
    # Drop "." placeholder values FRED uses for missing data.
    return [o for o in obs if o.get("value") not in (None, ".")]


def _is_scheduled(check_date):
    return any(abs((check_date - d).days) <= 2 for d in FOMC_DATES)


def _check_fomc_list():
    """Warn when the hardcoded meeting list doesn't cover the current year."""
    years = {d.year for d in FOMC_DATES}
    if dt.date.today().year not in years:
        return (f"WARN: FOMC_DATES has no {dt.date.today().year} meetings -- "
                f"update pillar3_macro.py or unscheduled-move checks are blind"), "UNKNOWN"
    return None, None


def _check_fed_funds_target():
    obs = _fetch_series("DFEDTARU", limit=10)
    if not obs:
        return "WARN: DFEDTARU unavailable this run", "UNKNOWN"
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
        return (f"RED: Fed funds target changed to {latest_val:.2f}% on {latest_date} -- "
                f"NOT a scheduled FOMC date, possible emergency move"), "RED"

    return f"OK: Fed funds target unchanged at {latest_val:.2f}%", "GREEN"


def _check_yield_curve():
    obs = _fetch_series("T10Y2Y", limit=CURVE_LOOKBACK_OBS)
    if len(obs) < 60:
        return "WARN: T10Y2Y history unavailable this run", "UNKNOWN"
    vals = [float(o["value"]) for o in obs]
    latest = vals[0]
    inverted_within_year = min(vals) < 0
    if inverted_within_year and latest > 0:
        return (f"YELLOW: 10Y-2Y spread {latest:+.2f} -- re-steepened to positive after inversion "
                f"within the last year (historically the risky phase)"), "YELLOW"
    note = "inverted" if latest < 0 else "normal"
    return f"OK: 10Y-2Y spread {latest:+.2f} ({note})", "GREEN"


def _check_curve_3m10y():
    obs = _fetch_series("T10Y3M", limit=CURVE_3M10Y_LOOKBACK_OBS)
    if len(obs) < 60:
        return "WARN: T10Y3M history unavailable this run", "UNKNOWN"
    vals = [float(o["value"]) for o in obs]
    latest = vals[0]
    inverted_within_period = min(vals) < 0
    if inverted_within_period and latest > 0:
        return (f"YELLOW: 10Y-3M spread {latest:+.2f} -- re-steepened to positive after inversion "
                f"within ~19 months (NY Fed recession-model input; dis-inversion has historically "
                f"landed close to the recession start)"), "YELLOW"
    if latest < 0:
        return (f"YELLOW: 10Y-3M spread {latest:+.2f} -- inverted (NY Fed recession-model input; "
                f"inversions have historically preceded recessions by ~12-18 months)"), "YELLOW"
    return f"OK: 10Y-3M spread {latest:+.2f} (normal)", "GREEN"


def _check_lending_standards():
    obs = _fetch_series("DRTSCILM", limit=6)
    if not obs:
        return "WARN: DRTSCILM unavailable this run", "UNKNOWN"
    latest = obs[0]
    val = float(latest["value"])
    delta = ""
    if len(obs) > 1:
        prior_val = float(obs[1]["value"])
        delta = f", {val - prior_val:+.1f}pt vs prior quarter"

    if val > LENDING_STANDARDS_RED_PCT:
        return (f"RED: Senior Loan Officer Survey net {val:.0f}% of banks tightening C&I lending "
                f"standards ({latest['date']}{delta}) -- crisis-level, trigger > {LENDING_STANDARDS_RED_PCT}%"), "RED"
    if val > LENDING_STANDARDS_YELLOW_PCT:
        return (f"YELLOW: Senior Loan Officer Survey net {val:.0f}% of banks tightening C&I lending "
                f"standards ({latest['date']}{delta}), trigger > {LENDING_STANDARDS_YELLOW_PCT}%"), "YELLOW"
    return (f"OK: Senior Loan Officer Survey net {val:.0f}% tightening C&I lending standards "
            f"({latest['date']}{delta})"), "GREEN"


def _check_credit_spread():
    obs = _fetch_series("BAMLH0A0HYM2", limit=70)
    if len(obs) < 64:
        return "WARN: insufficient BAMLH0A0HYM2 history this run", "UNKNOWN"

    latest_val = float(obs[0]["value"])
    prior_1m = float(obs[21]["value"])   # ~21 trading days back
    prior_3m = float(obs[63]["value"])   # ~63 trading days back
    delta_1m = (latest_val - prior_1m) * 100
    delta_3m = (latest_val - prior_3m) * 100

    if delta_1m > CREDIT_SPREAD_TRIGGER_BPS:
        return (f"RED: US HY OAS widened {delta_1m:.0f}bps over ~1 month "
                f"({prior_1m:.2f}% -> {latest_val:.2f}%), trigger > {CREDIT_SPREAD_TRIGGER_BPS}bps"), "RED"
    if delta_3m > CREDIT_SPREAD_3M_TRIGGER_BPS:
        return (f"YELLOW: US HY OAS widened {delta_3m:.0f}bps over ~3 months "
                f"({prior_3m:.2f}% -> {latest_val:.2f}%), trigger > {CREDIT_SPREAD_3M_TRIGGER_BPS}bps"), "YELLOW"
    return (f"OK: US HY OAS {latest_val:.2f}% ({delta_1m:+.0f}bps ~1mo, "
            f"{delta_3m:+.0f}bps ~3mo)"), "GREEN"


def _check_sahm():
    obs = _fetch_series("UNRATE", limit=18)
    if len(obs) < 15:
        return "WARN: UNRATE history unavailable this run", "UNKNOWN"
    rates = [float(o["value"]) for o in reversed(obs)]  # oldest first
    three_mo = [sum(rates[i - 2:i + 1]) / 3 for i in range(2, len(rates))]
    latest = three_mo[-1]
    low_12m = min(three_mo[-13:-1])
    gap = latest - low_12m
    if gap >= SAHM_TRIGGER_PTS:
        return (f"RED: Sahm rule {gap:.2f}pt above 12-month low (3mo avg {latest:.2f}%, "
                f"trigger {SAHM_TRIGGER_PTS}pt)"), "RED"
    return f"OK: Sahm rule gap {gap:.2f}pt (3mo avg {latest:.2f}%, trigger {SAHM_TRIGGER_PTS}pt)", "GREEN"


def _check_claims():
    obs = _fetch_series("ICSA", limit=54)
    if len(obs) < 52:
        return "WARN: ICSA history unavailable this run", "UNKNOWN"
    vals = [float(o["value"]) for o in obs]  # newest first
    avg4 = sum(vals[:4]) / 4
    low_52w = min(vals[:52])
    ratio = avg4 / low_52w
    if ratio > CLAIMS_TRIGGER_RATIO:
        return (f"YELLOW: initial claims 4-wk avg {avg4:,.0f} is {(ratio - 1) * 100:.0f}% above "
                f"52-week low {low_52w:,.0f} (trigger {(CLAIMS_TRIGGER_RATIO - 1) * 100:.0f}%)"), "YELLOW"
    return f"OK: initial claims 4-wk avg {avg4:,.0f} ({(ratio - 1) * 100:+.0f}% vs 52-week low)", "GREEN"


def _check_nfci():
    obs = _fetch_series("NFCI", limit=5)
    if not obs:
        return "WARN: NFCI unavailable this run", "UNKNOWN"
    val = float(obs[0]["value"])
    if val > 0:
        return f"YELLOW: Chicago Fed NFCI {val:+.2f} -- financial conditions tighter than average", "YELLOW"
    return f"OK: Chicago Fed NFCI {val:+.2f} (looser than average)", "GREEN"


def _safe(check):
    """Run one check. An exception becomes an UNKNOWN finding, never a pass."""
    try:
        return check()
    except Exception as e:
        return f"WARN: {check.__name__} failed ({e})", "UNKNOWN"


def run():
    checks = [_check_fomc_list, _check_fed_funds_target, _check_yield_curve,
              _check_curve_3m10y, _check_credit_spread, _check_sahm, _check_claims,
              _check_nfci, _check_lending_standards]
    findings = []
    statuses = []
    for check in checks:
        msg, st = _safe(check)
        if msg is None:
            continue
        findings.append(msg)
        statuses.append(st)

    if "RED" in statuses:
        status = "RED"
    elif "YELLOW" in statuses:
        status = "YELLOW"
    elif "UNKNOWN" in statuses:
        status = "UNKNOWN"
    else:
        status = "GREEN"

    return {
        "pillar": "3: Macro Credit & Fed Pivot",
        "status": status,
        "findings": findings,
    }
