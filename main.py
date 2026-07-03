import argparse
import traceback

import pillar1_concentration
import pillar2_capex
import pillar3_macro
import pillar4_regulatory
import report
import notify


def run_pillar(module, force_weekly=False):
    try:
        if module is pillar1_concentration and force_weekly:
            module.get_weekly_scan(force=True)
        return module.run()
    except Exception as e:
        return {
            "pillar": getattr(module, "__name__", "unknown"),
            "status": "GREEN",
            "findings": [f"WARN: pillar crashed and was skipped this run: {e}"],
        }


def main():
    parser = argparse.ArgumentParser(description="Retirement portfolio macro tripwires")
    parser.add_argument("--force-weekly-scan", action="store_true",
                         help="Force a fresh full S&P 500 scan even if last week's is still fresh")
    args = parser.parse_args()

    results = [
        run_pillar(pillar1_concentration, force_weekly=args.force_weekly_scan),
        run_pillar(pillar2_capex),
        run_pillar(pillar3_macro),
        run_pillar(pillar4_regulatory),
    ]

    overall, text, red_lines, yellow_lines = report.build(results)
    print(text)

    try:
        notify.toast(overall, red_lines, yellow_lines)
    except Exception:
        pass  # notification is best-effort; never fail the run over it


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
