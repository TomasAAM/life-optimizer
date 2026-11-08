"""Pace helpers: formatting, and the reference easy pace behind time-based easy runs.

Paces are stored as integer seconds per kilometre (so they sort and compare
cleanly) and displayed as ``"mm:ss"``. Kept self-contained so the dashboard does
not depend on the garmin-pipeline package.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd


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


@dataclass(frozen=True)
class EasyPaceReference:
    """The pace that converts planned easy km into prescribed minutes.

    Parameters
    ----------
    pace_s_per_km : int
        Reference easy pace in seconds per km.
    n_runs : int
        Qualifying runs behind the median; 0 when the fallback is used.
    window_days : int
        How far back the runs were taken from.
    from_data : bool
        ``True`` when the pace is the median of recorded runs, ``False`` when
        too few qualified and the configured fallback is used.
    """

    pace_s_per_km: int
    n_runs: int
    window_days: int
    from_data: bool


def reference_easy_pace(
    runs: pd.DataFrame,
    today: date,
    window_days: int,
    hr_cap: float | None,
    min_runs: int,
    min_km: float,
    fallback_s_per_km: int,
) -> EasyPaceReference:
    """Median pace of recent outdoor easy runs, or the fallback when too few exist.

    A run qualifies when it is outdoor, has a plausible pace, covers at least
    ``min_km``, averages at or under ``hr_cap`` and falls in the
    ``window_days`` up to and including ``today``. Treadmill runs are left out
    because belt pace is chosen, not run.

    Parameters
    ----------
    runs : pandas.DataFrame
        Output of :func:`dashboard.activity_metrics.prepare_runs`: needs
        ``date``, ``km``, ``pace_s_km``, ``avg_hr``, ``is_treadmill`` and
        ``implausible``.
    today : datetime.date
        Last day of the window.
    window_days : int
        Length of the window in days.
    hr_cap : float or None
        Easy-run HR ceiling (LT1). ``None`` means LT1 is unknown, so no run can
        be shown to be easy and the fallback is used.
    min_runs : int
        Fewest qualifying runs for the median to be used.
    min_km : float
        Shortest qualifying run in km.
    fallback_s_per_km : int
        Pace returned when too few runs qualify.

    Returns
    -------
    EasyPaceReference
        The reference pace and how it was obtained.

    Examples
    --------
    >>> runs = pd.DataFrame({
    ...     "date": pd.to_datetime(["2026-11-01"] * 6), "km": [8.0] * 6,
    ...     "pace_s_km": [340, 345, 345, 350, 355, 360], "avg_hr": [135] * 6,
    ...     "is_treadmill": [False] * 6, "implausible": [False] * 6})
    >>> reference_easy_pace(runs, date(2026, 11, 8), 42, 145, 6, 5.0, 345).pace_s_per_km
    348
    """
    fallback = EasyPaceReference(
        pace_s_per_km=fallback_s_per_km, n_runs=0, window_days=window_days, from_data=False
    )
    if runs.empty or hr_cap is None:
        return fallback

    dates = pd.to_datetime(runs["date"]).dt.date
    start = today - timedelta(days=window_days - 1)
    qualifies = (
        dates.between(start, today)
        & ~runs["is_treadmill"].astype(bool)
        & ~runs["implausible"].astype(bool)
        & (pd.to_numeric(runs["km"], errors="coerce") >= min_km)
        & (pd.to_numeric(runs["avg_hr"], errors="coerce") <= hr_cap)
    )
    paces = pd.to_numeric(runs.loc[qualifies, "pace_s_km"], errors="coerce").dropna()
    if len(paces) < min_runs:
        return fallback
    return EasyPaceReference(
        pace_s_per_km=int(round(float(paces.median()))),
        n_runs=len(paces),
        window_days=window_days,
        from_data=True,
    )


def easy_minutes(km: float, pace_s_per_km: int, round_to_min: int = 5) -> int:
    """Convert planned easy km into prescribed minutes, rounded up.

    Rounding up rather than to the nearest step keeps the conversion from
    shaving volume off the planned km.

    Parameters
    ----------
    km : float
        Planned distance in km.
    pace_s_per_km : int
        Reference easy pace in seconds per km.
    round_to_min : int, default 5
        Step the minutes are rounded up to.

    Returns
    -------
    int
        Prescribed minutes.

    Examples
    --------
    >>> easy_minutes(9, 345)
    55
    >>> easy_minutes(16, 345)
    95
    """
    minutes = km * pace_s_per_km / 60.0
    # Guard float noise so an exact multiple (e.g. 60.000000001) is not pushed a step up.
    return int(math.ceil(round(minutes, 6) / round_to_min) * round_to_min)
