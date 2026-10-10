"""
Pillar 4: Regulatory friction & AI disruption triggers.

Scans free RSS feeds for headlines that co-occur a regulatory-action term
with a major-lab name. ftc.gov sits behind Akamai bot management that
fingerprints the TLS/HTTP handshake itself -- plain `requests` gets a fake
404 on literally every request (even the homepage), no matter what headers
are sent, because the block happens before HTTP headers are even read. Real
browsers get through fine, so feed fetches go through curl_cffi impersonating
Chrome's TLS fingerprint instead of plain `requests`. If a feed starts
reliably returning nothing even through that, it has likely actually moved
-- check/update its URL below.
"""
import datetime as dt
import time

import feedparser
from curl_cffi import requests as creq

import state

FEEDS = {
    "TechCrunch": "https://techcrunch.com/feed/",
    "Ars Technica": "https://feeds.arstechnica.com/arstechnica/index",
    "FTC Press Releases": "https://www.ftc.gov/feeds/press-release.xml",
    "DOJ Antitrust Division": (
        "https://www.justice.gov/news/rss?type%5B0%5D=image_gallery&type%5B1%5D=press_release"
        "&type%5B2%5D=speech&type%5B3%5D=youtube_video&field_component=376"
        "&search_api_language=en&show_public_archived=0&require_all=0"
    ),
}

_FEED_RETRIES = 3

ACTION_TERMS = [
    "export control", "national security review", "government audit",
    "antitrust", "ftc", "doj", "federal halt", "regulatory freeze",
    "emergency order", "blocked", "banned", "injunction",
]
HALT_TERMS = ["halt", "blocked", "banned", "emergency order", "injunction", "suspend"]
LAB_TERMS = ["openai", "anthropic", "google", "deepmind", "gemini", "meta ai"]


def _matches(text):
    low = text.lower()
    action_hit = next((t for t in ACTION_TERMS if t in low), None)
    lab_hit = next((t for t in LAB_TERMS if t in low), None)
    if action_hit and lab_hit:
        severe = any(h in low for h in HALT_TERMS)
        return action_hit, lab_hit, severe
    return None


def run():
    seen = state.load("regulatory_seen_entries", default={"ids": []})
    seen_ids = set(seen["ids"])

    findings = []
    new_hits = []
    dead_feeds = []
    status = "GREEN"

    for name, url in FEEDS.items():
        parsed = None
        for attempt in range(_FEED_RETRIES):
            try:
                resp = creq.get(url, impersonate="chrome", timeout=20)
                resp.raise_for_status()
                candidate = feedparser.parse(resp.content)
                if candidate.entries:
                    parsed = candidate
                    break
            except Exception:
                pass
            if attempt < _FEED_RETRIES - 1:
                time.sleep(3)
        if parsed is None:
            dead_feeds.append(name)
            continue

        for entry in parsed.entries[:40]:
            entry_id = entry.get("id") or entry.get("link")
            if not entry_id or entry_id in seen_ids:
                continue
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            match = _matches(f"{title} {summary}")
            if not match:
                continue
            seen_ids.add(entry_id)
            action_hit, lab_hit, severe = match
            new_hits.append({
                "feed": name, "title": title, "link": entry.get("link", ""),
                "action_hit": action_hit, "lab_hit": lab_hit, "severe": severe,
            })

    state.save("regulatory_seen_entries", {"ids": list(seen_ids)})

    # Headline keywords are noisy (a dismissed lawsuit matched as a hit), so
    # this pillar is context only: it can raise YELLOW but never RED on its own.
    if new_hits:
        status = "YELLOW"
        for h in new_hits:
            findings.append(
                f"YELLOW: [{h['feed']}] \"{h['title']}\" (matched '{h['action_hit']}' + '{h['lab_hit']}') -- {h['link']}"
            )
    else:
        findings.append("OK: no new regulatory/AI-lab co-occurrence hits across tracked feeds")

    if dead_feeds:
        # A dead feed is a coverage gap, so this pillar can't call itself GREEN.
        status = "UNKNOWN"
        findings.append(f"WARN: unreachable/empty feed(s), check URL: {', '.join(dead_feeds)}")

    return {
        "pillar": "4: Regulatory Friction & AI Disruption",
        "status": status,
        "findings": findings,
    }
