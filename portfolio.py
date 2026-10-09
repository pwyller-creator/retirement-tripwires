"""
Translates an equity-market drawdown into an estimated hit to the account,
using a hand-entered holdings snapshot (portfolio_data.py, gitignored --
see portfolio_data.py.example).

This is not investment advice and not a live feed -- it's a rough order-of-
magnitude translation of "the market is at risk" into "here's about how
much of my account that touches," so a RED/YELLOW tripwire reads as
something more concrete than an abstract macro signal. Any reallocation
decision is still yours to make.
"""
DRAWDOWN_SCENARIOS = [15, 20, 30]  # percent equity-market drawdown


def _load():
    try:
        import portfolio_data
        return portfolio_data.HOLDINGS, portfolio_data.AS_OF
    except ImportError:
        return None, None


def equity_fraction(holdings):
    return sum(pct * eq for _, pct, eq in holdings) / 100


def estimate():
    """Returns (equity_fraction, lines) or (None, []) if no holdings snapshot
    is configured (portfolio_data.py not present)."""
    holdings, as_of = _load()
    if not holdings:
        return None, []

    total_pct = sum(pct for _, pct, _ in holdings)
    eq_frac = equity_fraction(holdings)
    lines = [
        f"Portfolio impact estimate (snapshot as of {as_of}, {total_pct:.1f}% of account covered):",
        f"  est. {eq_frac * 100:.0f}% effective equity exposure "
        f"(target-date funds' equity share is a glide-path estimate, not live data)",
    ]
    for dd in DRAWDOWN_SCENARIOS:
        hit = eq_frac * dd
        lines.append(f"  a {dd}% equity-market drawdown -> est. {hit:.1f}% hit to total account value")
    return eq_frac, lines


def toast_line():
    """One short line for the toast -- just the headline 20%-drawdown case."""
    eq_frac, _ = estimate()
    if eq_frac is None:
        return None
    hit = eq_frac * 20
    return f"Est. {eq_frac * 100:.0f}% equity exposure -- a 20% market drawdown ~ {hit:.1f}% hit to account"
