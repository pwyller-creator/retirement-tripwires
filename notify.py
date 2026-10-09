def toast(overall_status, red_lines, yellow_lines, unknown_lines=(), log_path=None, portfolio_line=None):
    # Data gaps alert too: a pillar that couldn't check its triggers must not
    # look like an all-clear.
    if overall_status == "GREEN" and not unknown_lines:
        return
    try:
        from winotify import Notification, audio
    except ImportError:
        return  # winotify not installed; terminal/log output still has the result

    sections = []
    if red_lines:
        sections.append("RED -- act on this:")
        sections.extend(f"  {line}" for line in red_lines)
    if yellow_lines:
        sections.append("YELLOW -- worth reading:")
        sections.extend(f"  {line}" for line in yellow_lines)
    if unknown_lines:
        gap_pillars = [line.split(":", 1)[0] for line in unknown_lines]
        sections.append(f"Data gaps (not checked, not green): pillar(s) {', '.join(gap_pillars)}")
    if portfolio_line:
        sections.append("")
        sections.append(portfolio_line)

    body = "\n".join(sections) if sections else "See log for details."
    title = f"Portfolio Tripwires: {overall_status}"
    if unknown_lines:
        title += " (data gaps)"

    kwargs = {}
    if log_path is not None:
        kwargs["launch"] = str(log_path)

    n = Notification(
        app_id="Retirement Tripwires",
        title=title,
        msg=body,
        duration="long",
        **kwargs,
    )
    if overall_status == "RED":
        n.set_audio(audio.Default, loop=False)
    if log_path is not None:
        n.add_actions(label="Open today's log", launch=str(log_path))
    n.show()
