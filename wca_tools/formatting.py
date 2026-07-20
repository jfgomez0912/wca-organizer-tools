"""Formatting helpers for WCA result times."""


def fmt_result(value: int | None, event_id: str = "", *, blank: str = "-") -> str:
    """Format a WCA result value (centiseconds) as a readable string.

    ``blank`` is returned for a missing result (None/0) — pass "" for exports.
    """
    if not value:
        return blank
    if value == -1:
        return "DNF"
    if value == -2:
        return "DNS"
    if event_id in ("333fm", "333mbf"):
        return str(value)
    minutes, remainder = divmod(value, 6000)
    seconds, centis = divmod(remainder, 100)
    return f"{minutes}:{seconds:02d}.{centis:02d}" if minutes else f"{seconds}.{centis:02d}"


def fmt_seconds(s: float) -> str:
    """Format float seconds as M:SS.cc or SS.cc (no suffix)."""
    total_cs = round(s * 100)
    minutes, remainder = divmod(total_cs, 6000)
    secs, centis = divmod(remainder, 100)
    return f"{minutes}:{secs:02d}.{centis:02d}" if minutes else f"{secs}.{centis:02d}"


def fmt_goal(s: float) -> str:
    """Format a sub-X goal, e.g. 10.0 -> 'sub-10.00' (reach it by going under X)."""
    return f"sub-{fmt_seconds(s)}"
