"""
Backtest the tripwire triggers against past S&P 500 drawdowns.

For each signal:
- A "drawdown" is an S&P 500 peak-to-trough fall of at least 20%.
- A signal is "caught" a drawdown if it turned on within 12 months before the
  peak (or within 30 days after it). Lead time = peak date minus signal date.
- A "false alarm" is a signal turn-on with no 20%+ drawdown peak in the 12 months after.

Caveats (say these with any result):
- FRED series are today's revised vintages, not point-in-time. UNRATE and
  NFCI in particular get revised, so past signals may look slightly cleaner.
- Series are forward-filled to daily; publication lags (up to ~5 weeks for
  UNRATE) are not modeled. That flatters lead times slightly.
- RSP (equal weight) only exists from 2003, so the breadth proxy covers
  that window only.
- Few independent episodes exist. Treat counts as a sanity check, not
  statistical proof.

Usage: python backtest.py   (writes logs/backtest_report.txt)
"""
import datetime as dt
import requests
import pandas as pd
import yfinance as yf

from config import FRED_API_KEY, LOG_DIR

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
START = "1990-01-01"
DRAWDOWN_EVENT = -15.0   # percent; 20% gives only 4 episodes since 1990
CATCH_BEFORE_DAYS = 365


def fred(series_id):
    params = {"series_id": series_id, "api_key": FRED_API_KEY, "file_type": "json",
              "observation_start": START}
    resp = requests.get(FRED_URL, params=params, timeout=60)
    resp.raise_for_status()
    obs = [o for o in resp.json()["observations"] if o["value"] not in (None, ".")]
    s = pd.Series({pd.Timestamp(o["date"]): float(o["value"]) for o in obs})
    return s.sort_index()


def daily(s, index):
    return s.reindex(s.index.union(index)).ffill().reindex(index)


def drawdown_events(spx):
    """Return (peak, trough) date pairs for each episode that falls at least
    DRAWDOWN_EVENT percent from its peak before recovering."""
    running_max = spx.cummax()
    dd = (spx / running_max - 1) * 100
    events = []
    peak_date, trough_date, trough_val, in_event = None, None, 0.0, False
    for date, val in dd.items():
        if val == 0:
            if in_event and trough_val <= DRAWDOWN_EVENT:
                events.append((peak_date, trough_date))
            peak_date, in_event, trough_val = date, False, 0.0
        else:
            if val < trough_val:
                trough_val, trough_date = val, date
            if val <= DRAWDOWN_EVENT:
                in_event = True
    return events


def rising_edges(sig):
    prev = sig.shift(1, fill_value=False)
    return list(sig.index[sig & ~prev])


def score(name, sig, events):
    """A signal catches an event if it turns on from 12 months before the peak
    through the trough. A signal that turns on after the peak still gives
    warning while the market is still falling, which is when reallocation
    could still help."""
    edges = rising_edges(sig)
    caught = {}
    for peak, trough in events:
        window_start = peak - pd.Timedelta(days=CATCH_BEFORE_DAYS)
        hits = [e for e in edges if window_start <= e <= trough]
        if hits:
            caught[peak] = (peak - hits[0]).days
    false = [e for e in edges
             if not any(p - pd.Timedelta(days=CATCH_BEFORE_DAYS) <= e <= t for p, t in events)]
    return {
        "name": name, "episodes": len(edges),
        "caught": len(caught), "of": len(events),
        "median_lead_days": int(pd.Series(list(caught.values())).median()) if caught else None,
        "false_alarms": len(false),
    }


def main():
    spx = yf.download("^GSPC", start=START, interval="1d", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    events = drawdown_events(spx)
    idx = spx.index

    hy = daily(fred("BAMLH0A0HYM2"), idx)
    curve = daily(fred("T10Y2Y"), idx)
    nfci = daily(fred("NFCI"), idx)

    # Sahm and claims are computed on their own frequency (monthly, weekly),
    # then forward-filled. Rolling over the daily-filled series would count
    # the same value many times.
    unrate_m = fred("UNRATE")                       # monthly
    u3 = unrate_m.rolling(3).mean()                 # 3-month average
    sahm_gap_m = u3 - u3.rolling(12).min().shift(1)  # vs prior 12-month low
    sahm_gap = daily(sahm_gap_m, idx)

    claims_w = fred("ICSA")                          # weekly
    claims_ratio_w = claims_w.rolling(4).mean() / claims_w.rolling(52).min()
    claims_ratio = daily(claims_ratio_w, idx)

    signals = {
        "HY OAS +50bp / 1mo (RED)": (hy - hy.shift(21)) > 0.5,
        "HY OAS +75bp / 3mo (YELLOW)": (hy - hy.shift(63)) > 0.75,
        "Sahm gap >= 0.5 (RED)": sahm_gap >= 0.5,
        "Claims 4wk > 1.25x 52wk low (YELLOW)": claims_ratio > 1.25,
        "NFCI > 0 (YELLOW)": nfci > 0,
        "Curve re-steepened after inversion (YELLOW)":
            (curve.rolling(252, min_periods=60).min() < 0) & (curve > 0),
    }
    signals = {k: v.fillna(False).astype(bool) for k, v in signals.items()}

    rsp = yf.download("RSP", start="2003-05-01", interval="1d", auto_adjust=True, progress=False)["Close"].squeeze()
    spy = yf.download("SPY", start="2003-05-01", interval="1d", auto_adjust=True, progress=False)["Close"].squeeze()
    ratio = (rsp / spy).dropna()
    ew_chg = (ratio / ratio.shift(40) - 1) * 100
    ew_sig = (ew_chg < -4.0).reindex(idx).ffill().fillna(False).astype(bool)

    lines = [f"Backtest run {dt.datetime.now().isoformat(timespec='minutes')}",
             f"S&P 500 drawdown episodes >= {abs(DRAWDOWN_EVENT):.0f}% since {START}: {len(events)}",
             "  " + "; ".join(f"peak {p.date()} -> trough {t.date()}" for p, t in events),
             ""]
    for name, sig in signals.items():
        lines.append(_fmt(score(name, sig, events)))
    lines.append("")
    ew_events = [(p, t) for p, t in events if p >= pd.Timestamp("2003-05-01")]
    lines.append(f"Equal-weight proxy (RSP/SPY -4% / 40d), from 2003 -- {len(ew_events)} episodes in window:")
    lines.append(_fmt(score("RSP/SPY breadth (YELLOW)", ew_sig, ew_events)))
    lines.append("")
    lines.append("Lead = days from signal turn-on to peak; negative = turned on after the peak, mid-decline.")
    lines.append("Caveats: revised FRED vintages, no publication lags, only 8 episodes -- do not overfit to them.")

    text = "\n".join(lines)
    print(text)
    (LOG_DIR / "backtest_report.txt").write_text(text + "\n", encoding="utf-8")


def _fmt(r):
    lead = f"{r['median_lead_days']}d" if r["median_lead_days"] is not None else "n/a"
    return (f"{r['name']:<46} caught {r['caught']}/{r['of']} drawdowns, "
            f"median lead {lead:>6}, {r['episodes']} signal turn-ons, {r['false_alarms']} false alarms")


if __name__ == "__main__":
    main()
