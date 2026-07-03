"""
Pillar 4: Regulatory friction & AI disruption triggers.

Scans free RSS feeds for headlines that co-occur a regulatory-action term
with a major-lab name. FTC/DOJ feed URLs occasionally change on the
government side -- each feed fetch is wrapped so one dead feed doesn't
break the run; if a feed starts silently returning nothing, check/update
its URL below.
"""
import datetime as dt
import feedparser
import requests

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

# Both ftc.gov and justice.gov 403 requests with no User-Agent, so fetch the
# raw bytes ourselves and hand them to feedparser instead of letting it fetch.
_UA = {"User-Agent": "Mozilla/5.0 (retirement-tripwires script)"}

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
        try:
            resp = requests.get(url, headers=_UA, timeout=20)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
            if not parsed.entries:
                dead_feeds.append(name)
                continue
        except Exception:
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

    if new_hits:
        for h in new_hits:
            level = "RED" if h["severe"] else "YELLOW"
            if level == "RED":
                status = "RED"
            elif status == "GREEN":
                status = "YELLOW"
            findings.append(
                f"{level}: [{h['feed']}] \"{h['title']}\" (matched '{h['action_hit']}' + '{h['lab_hit']}') -- {h['link']}"
            )
    else:
        findings.append("OK: no new regulatory/AI-lab co-occurrence hits across tracked feeds")

    if dead_feeds:
        findings.append(f"WARN: unreachable/empty feed(s), check URL: {', '.join(dead_feeds)}")

    return {
        "pillar": "4: Regulatory Friction & AI Disruption",
        "status": status,
        "findings": findings,
    }
