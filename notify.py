def toast(overall_status, red_lines, yellow_lines):
    if overall_status == "GREEN":
        return
    try:
        from winotify import Notification
    except ImportError:
        return  # winotify not installed; terminal/log output still has the result

    lines = (red_lines + yellow_lines)[:4]
    body = "\n".join(lines) if lines else "See log for details."

    n = Notification(
        app_id="Retirement Tripwires",
        title=f"Portfolio Tripwires: {overall_status}",
        msg=body,
        duration="long",
    )
    n.show()
