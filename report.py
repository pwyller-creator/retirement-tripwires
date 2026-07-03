import csv
import datetime as dt

from config import LOG_DIR

STATUS_RANK = {"GREEN": 0, "YELLOW": 1, "RED": 2}


def build(pillar_results):
    overall = "GREEN"
    for p in pillar_results:
        if STATUS_RANK[p["status"]] > STATUS_RANK[overall]:
            overall = p["status"]

    now = dt.datetime.now()
    lines = [
        "=" * 72,
        f" RETIREMENT PORTFOLIO TRIPWIRES -- {now.strftime('%Y-%m-%d %H:%M')}",
        f" OVERALL: {overall}",
        "=" * 72,
    ]
    for p in pillar_results:
        lines.append(f"\n[{p['status']}] Pillar {p['pillar']}")
        for f in p["findings"]:
            lines.append(f"    - {f}")

    text = "\n".join(lines)

    log_path = LOG_DIR / f"tripwires_{now.strftime('%Y-%m-%d')}.log"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(text + "\n\n")

    history_path = LOG_DIR / "history.csv"
    is_new = not history_path.exists()
    with open(history_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["timestamp", "overall_status"] + [p["pillar"].split(":")[0] for p in pillar_results])
        writer.writerow([now.isoformat(), overall] + [p["status"] for p in pillar_results])

    red_lines = [f"{p['pillar']}: " + "; ".join(x for x in p["findings"] if x.startswith("RED")) for p in pillar_results if p["status"] == "RED"]
    yellow_lines = [f"{p['pillar']}: " + "; ".join(x for x in p["findings"] if x.startswith("YELLOW")) for p in pillar_results if p["status"] == "YELLOW"]

    return overall, text, red_lines, yellow_lines
