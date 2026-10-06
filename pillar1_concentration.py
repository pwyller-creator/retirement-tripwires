"""
Pillar 1: S&P 500 concentration & technical breadth.

Metric 1 (weekly, full-universe scan): combined market-cap weight of
MSFT/GOOGL/AMZN/META/NVDA vs the rest of the S&P 500. Trigger: > 32%.

Metric 2 (daily, 2 tickers): QQQ / SMH breaking below their 50-day MA on
high volume, plus (from the same weekly scan) % of S&P 500 names trading
above their own 200-day MA. Trigger: breakdown, or breadth < 50%.

The full 500-ticker scan only runs once every 7 days to stay well clear of
yfinance's free-tier rate limits; daily runs reuse last week's snapshot.
"""
import time
import datetime as dt
from io import StringIO
import requests
import pandas as pd
import yfinance as yf

import state

TOP5 = ["MSFT", "GOOGL", "AMZN", "META", "NVDA"]
CONCENTRATION_TRIGGER_PCT = 32.0
BREADTH_TRIGGER_PCT = 50.0
EW_LOOKBACK_DAYS = 40      # ~2 months of trading days
EW_LOSS_TRIGGER_PCT = 4.0  # RSP underperforming SPY by more than this = narrowing
SCAN_MAX_AGE_DAYS = 7
SP500_LIST_MAX_AGE_DAYS = 30

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def _normalize_ticker(t):
    # yfinance wants BRK-B, not BRK.B
    return t.strip().upper().replace(".", "-")


def get_sp500_tickers():
    cached = state.load("sp500_constituents", default=None)
    if cached:
        fetched = dt.datetime.fromisoformat(cached["fetched_at"])
        if (dt.datetime.now() - fetched).days < SP500_LIST_MAX_AGE_DAYS:
            return cached["tickers"]

    # Wikipedia 403s requests with no User-Agent (blocks pandas' default urllib fetch).
    resp = requests.get(WIKI_URL, headers={"User-Agent": "Mozilla/5.0 (retirement-tripwires script)"}, timeout=20)
    resp.raise_for_status()
    tables = pd.read_html(StringIO(resp.text))
    tickers = [_normalize_ticker(t) for t in tables[0]["Symbol"].tolist()]
    state.save("sp500_constituents", {
        "fetched_at": dt.datetime.now().isoformat(),
        "tickers": tickers,
    })
    return tickers


def _weekly_scan():
    tickers = get_sp500_tickers()
    total_mcap = 0.0
    top5_mcap = 0.0
    above_200 = 0
    valid = 0
    errors = []

    # yfinance batches best in chunks; keep chunks small and pause between
    # them so the free endpoint doesn't start throttling mid-scan.
    chunk_size = 40
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        try:
            hist = yf.download(
                tickers=chunk, period="300d", interval="1d",
                group_by="ticker", threads=True, progress=False,
                auto_adjust=True,
            )
        except Exception as e:
            errors.append(f"chunk {i}: {e}")
            time.sleep(2)
            continue

        for tkr in chunk:
            try:
                df = hist[tkr] if len(chunk) > 1 else hist
                closes = df["Close"].dropna()
                if len(closes) < 200:
                    continue
                last_close = closes.iloc[-1]
                sma200 = closes.tail(200).mean()

                fast = yf.Ticker(tkr).fast_info
                mcap = getattr(fast, "market_cap", None) if fast else None
                if not mcap:
                    continue

                total_mcap += mcap
                valid += 1
                if last_close > sma200:
                    above_200 += 1
                if tkr in TOP5:
                    top5_mcap += mcap
            except Exception as e:
                errors.append(f"{tkr}: {e}")
        time.sleep(1.5)

    result = {
        "scan_date": dt.datetime.now().isoformat(),
        "valid_tickers": valid,
        "total_market_cap": total_mcap,
        "top5_market_cap": top5_mcap,
        "concentration_pct": (top5_mcap / total_mcap * 100) if total_mcap else None,
        "pct_above_200dma": (above_200 / valid * 100) if valid else None,
        "errors": errors[:20],
    }
    state.save("weekly_scan", result)
    return result


def get_weekly_scan(force=False):
    cached = state.load("weekly_scan", default=None)
    if cached and not force:
        scanned = dt.datetime.fromisoformat(cached["scan_date"])
        if (dt.datetime.now() - scanned).days < SCAN_MAX_AGE_DAYS:
            return cached
    return _weekly_scan()


def _breadth_breakdown_check(ticker):
    df = yf.Ticker(ticker).history(period="90d", interval="1d", auto_adjust=True)
    if df.empty or len(df) < 51:
        return {"ticker": ticker, "status": "UNKNOWN", "detail": "insufficient history"}

    df["sma50"] = df["Close"].rolling(50).mean()
    df["avg_vol20"] = df["Volume"].rolling(20).mean()

    today = df.iloc[-1]
    yesterday = df.iloc[-2]

    below_now = today["Close"] < today["sma50"]
    fresh_break = below_now and (yesterday["Close"] >= yesterday["sma50"])
    high_volume = today["Volume"] > 1.5 * today["avg_vol20"]

    if fresh_break and high_volume:
        return {
            "ticker": ticker, "status": "RED",
            "detail": f"broke below 50DMA today on {today['Volume'] / today['avg_vol20']:.1f}x avg volume",
        }
    if below_now:
        return {"ticker": ticker, "status": "YELLOW", "detail": "trading below 50DMA"}
    return {"ticker": ticker, "status": "GREEN", "detail": "above 50DMA"}


def _equal_weight_check():
    """RSP (equal-weight S&P 500) vs SPY (cap-weight). A falling ratio means the
    average stock is lagging the index. Independent of the weekly scan."""
    df = yf.download(["RSP", "SPY"], period="200d", interval="1d",
                     auto_adjust=True, progress=False)["Close"].dropna()
    if len(df) < EW_LOOKBACK_DAYS + 1:
        return {"status": "UNKNOWN", "detail": "insufficient RSP/SPY history"}
    ratio = df["RSP"] / df["SPY"]
    change = (ratio.iloc[-1] / ratio.iloc[-1 - EW_LOOKBACK_DAYS] - 1) * 100
    msg = f"equal-weight vs cap-weight (RSP/SPY) {change:+.1f}% over ~{EW_LOOKBACK_DAYS} trading days"
    if change < -EW_LOSS_TRIGGER_PCT:
        return {"status": "YELLOW", "detail": msg + f", trigger < -{EW_LOSS_TRIGGER_PCT}%"}
    return {"status": "GREEN", "detail": msg}


def run():
    try:
        scan = get_weekly_scan()
    except Exception as e:
        return {
            "pillar": "1: S&P 500 Concentration & Tech Breadth",
            "status": "UNKNOWN",
            "findings": [f"WARN: weekly S&P 500 scan failed ({e}); concentration and breadth not checked"],
        }

    breakdowns = [_breadth_breakdown_check(t) for t in ("QQQ", "SMH")]
    try:
        ew = _equal_weight_check()
    except Exception as e:
        ew = {"status": "UNKNOWN", "detail": f"RSP/SPY check failed ({e})"}

    findings = []
    status = "GREEN"
    gap = False

    conc = scan.get("concentration_pct")
    if conc is not None:
        if conc > CONCENTRATION_TRIGGER_PCT:
            status = "RED"
            findings.append(f"RED: Top-5 mega-cap concentration {conc:.1f}% > {CONCENTRATION_TRIGGER_PCT}% trigger")
        else:
            findings.append(f"OK: Top-5 mega-cap concentration {conc:.1f}% (trigger {CONCENTRATION_TRIGGER_PCT}%)")
    else:
        gap = True
        findings.append("WARN: concentration data unavailable this run")

    breadth = scan.get("pct_above_200dma")
    if breadth is not None:
        if breadth < BREADTH_TRIGGER_PCT:
            status = "RED"
            findings.append(f"RED: only {breadth:.1f}% of S&P 500 above 200DMA (trigger < {BREADTH_TRIGGER_PCT}%)")
        else:
            findings.append(f"OK: {breadth:.1f}% of S&P 500 above 200DMA")
    else:
        gap = True
        findings.append("WARN: breadth data unavailable this run")

    for b in breakdowns + [ew]:
        label = b.get("ticker", "RSP/SPY")
        findings.append(f"{b['status']}: {label} -- {b['detail']}")
        if b["status"] == "UNKNOWN":
            gap = True
        elif b["status"] == "RED":
            status = "RED"
        elif b["status"] == "YELLOW" and status == "GREEN":
            status = "YELLOW"

    # A data gap can't be GREEN, but a real RED/YELLOW still shows as such.
    if gap and status == "GREEN":
        status = "UNKNOWN"

    return {
        "pillar": "1: S&P 500 Concentration & Tech Breadth",
        "status": status,
        "findings": findings,
        "scan_age_days": (dt.datetime.now() - dt.datetime.fromisoformat(scan["scan_date"])).days,
    }
