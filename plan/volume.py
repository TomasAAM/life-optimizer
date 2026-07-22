"""Trailing actual running volume — descriptive grounding for the km target.

This module answers one question: *how much has the athlete actually been
running lately?* It exists so the configured ``base_weekly_km`` can be
sanity-checked against reality in the generation brief.

It is deliberately **not** auto-regulation. Nothing here consumes recovery data
(HRV/CTL/readiness) and nothing here changes a prescription — the athlete still
self-regulates on the day. The generator simply sees achieved run volume as
context alongside the deterministic, phase-scaled target, so a target can't
silently drift far from what the athlete is really doing.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

# Garmin ``activity_type`` values that carry running kilometres. Station/strength
# and cycling sessions are excluded — they don't count toward running volume
# (mirrors the generator guardrail "easy runs carry the km").
RUN_TYPES: frozenset[str] = frozenset(
    {
        "running",
        "treadmill_running",
        "trail_running",
        "track_running",
        "indoor_running",
        "virtual_run",
    }
)


def _week_monday(d: date) -> date:
    """Return the Monday of the ISO week containing ``d``."""
    return d - timedelta(days=d.weekday())


def recent_weekly_km(
    activities: pd.DataFrame,
    *,
    weeks: int = 4,
    today: date | None = None,
) -> float | None:
    """Mean weekly running volume (km) over the last ``weeks`` complete weeks.

    Only whole Monday-Sunday weeks *before* the current week are counted, so the
    in-progress week never drags the average down. Purely descriptive context for
    the generation brief — never an auto-regulation input.

    Parameters
    ----------
    activities : pandas.DataFrame
        Activity rows with at least ``start_time_local`` (parseable to a
        datetime), ``activity_type`` and ``distance_m`` (metres).
    weeks : int
        Number of complete weeks to average over (default 4). Must be >= 1.
    today : datetime.date, optional
        Reference date; defaults to :func:`datetime.date.today`.

    Returns
    -------
    float or None
        Mean running kilometres per week, rounded to one decimal, or ``None``
        when there is no running data in the window.
    """
    if activities is None or activities.empty or weeks < 1:
        return None
    required = {"start_time_local", "activity_type", "distance_m"}
    if not required.issubset(activities.columns):
        return None

    df = activities[activities["activity_type"].isin(RUN_TYPES)].copy()
    if df.empty:
        return None

    day = pd.to_datetime(df["start_time_local"], errors="coerce").dt.date
    df = df.assign(_day=day).dropna(subset=["_day"])
    if df.empty:
        return None

    this_monday = _week_monday(today or date.today())
    window_start = this_monday - timedelta(days=7 * weeks)
    in_window = (df["_day"] >= window_start) & (df["_day"] < this_monday)
    win = df.loc[in_window]
    if win.empty:
        return None

    total_km = pd.to_numeric(win["distance_m"], errors="coerce").fillna(0).sum() / 1000.0
    return round(total_km / weeks, 1)
