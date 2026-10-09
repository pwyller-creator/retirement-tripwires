import csv
import datetime as dt

import portfolio
from config import LOG_DIR, redact

# UNKNOWN means a data source failed, so the pillar could not check its
# triggers. It is not GREEN. Overall, it counts as YELLOW (see build()).
STATUS_RANK = {"GREEN": 0, "UNKNOWN": 1, "YELLOW": 1, "RED": 2}


def build(pillar_results):
    for p in pillar_results:
        p["findings"] = [redact(f) for f in p["findings"]]

    overall = "GREEN"
    for p in pillar_results:
        if STATUS_RANK[p["status"]] > STATUS_RANK[overall]:
            overall = p["status"]
    gaps = [p["pillar"].split(":")[0] for p in pillar_results if p["status"] == "UNKNOWN"]

    now = dt.datetime.now()
    header = f" OVERALL: {overall}"
    if gaps:
        header += f"   (DATA GAPS in pillar(s) {', '.join(gaps)} -- not checked, not green)"
    lines = [
        "=" * 72,
        f" RETIREMENT PORTFOLIO TRIPWIRES -- {now.strftime('%Y-%m-%d %H:%M')}",
        header,
        "=" * 72,
    ]
    for p in pillar_results:
        lines.append(f"\n[{p['status']}] Pillar {p['pillar']}")
        for f in p["findings"]:
            lines.append(f"    - {f}")

    portfolio_line = None
    if overall != "GREEN":
        _, portfolio_lines = portfolio.estimate()
        if portfolio_lines:
            lines.append("")
            lines.extend(portfolio_lines)
            portfolio_line = portfolio.toast_line()

    text = "\n".join(lines)

    log_path = LOG_DIR / f"tripwires_{now.strftime('%Y-%m-%d')}.log"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(text + "\n\n")

    _write_history(now, overall, pillar_results)

    def lines_for(status):
        return [f"{p['pillar']}: " + "; ".join(x for x in p["findings"] if x.startswith(status))
                for p in pillar_results if p["status"] == status]

    red_lines = lines_for("RED")
    yellow_lines = lines_for("YELLOW")
    unknown_lines = [f"{p['pillar']}: " + "; ".join(x for x in p["findings"] if x.startswith("WARN"))
                     for p in pillar_results if p["status"] == "UNKNOWN"]

    return overall, text, red_lines, yellow_lines, unknown_lines, log_path, portfolio_line


def _write_history(now, overall, pillar_results):
    """One row per calendar day. A manual re-run replaces that day's row
    instead of appending a duplicate."""
    history_path = LOG_DIR / "history.csv"
    header = ["timestamp", "overall_status"] + [f"pillar{i}" for i in range(1, len(pillar_results) + 1)]
    row = [now.isoformat(), overall] + [p["status"] for p in pillar_results]

    rows = []
    if history_path.exists():
        with open(history_path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
    today = now.date().isoformat()
    body = [r for r in rows[1:] if r and not r[0].startswith(today)]
    body.append(row)

    with open(history_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(body)
