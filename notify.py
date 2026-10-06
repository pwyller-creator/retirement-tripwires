def toast(overall_status, red_lines, yellow_lines, unknown_lines=()):
    # Data gaps alert too: a pillar that couldn't check its triggers must not
    # look like an all-clear.
    if overall_status == "GREEN" and not unknown_lines:
        return
    try:
        from winotify import Notification
    except ImportError:
        return  # winotify not installed; terminal/log output still has the result

    lines = (red_lines + yellow_lines + list(unknown_lines))[:4]
    body = "\n".join(lines) if lines else "See log for details."
    title = f"Portfolio Tripwires: {overall_status}"
    if unknown_lines:
        title += " (data gaps)"

    n = Notification(
        app_id="Retirement Tripwires",
        title=title,
        msg=body,
        duration="long",
    )
    n.show()
