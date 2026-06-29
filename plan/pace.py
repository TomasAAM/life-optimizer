"""Pace formatting helpers.

Paces are stored as integer seconds per kilometre (so they sort and compare
cleanly) and displayed as ``"mm:ss"``. Kept self-contained so the dashboard does
not depend on the garmin-pipeline package.
"""

from __future__ import annotations


def pace_to_seconds(pace: str) -> int:
    """Convert a ``"mm:ss"`` per-km pace string to seconds per kilometre.

    Parameters
    ----------
    pace : str
        Pace as minutes and seconds per kilometre, e.g. ``"4:34"``.

    Returns
    -------
    int
        Seconds per kilometre.
    """
    minutes, seconds = pace.split(":")
    return int(minutes) * 60 + int(seconds)


def seconds_to_pace(seconds: int | None) -> str:
    """Convert seconds per kilometre to a ``"mm:ss"`` pace string.

    Parameters
    ----------
    seconds : int or None
        Seconds per kilometre, or ``None`` for an open-ended bound.

    Returns
    -------
    str
        Pace as ``"mm:ss"``, or ``"—"`` when ``seconds`` is ``None``.
    """
    if seconds is None or seconds != seconds:  # None or NaN
        return "—"
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"
