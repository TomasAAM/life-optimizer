"""Deterministic periodization logic.

The phase a given week sits in is a pure function of how many weeks remain until
the race — no model involved, so it is fully reproducible and unit-testable. The
generator uses the phase to bias the week's structure and weekly-load target.

Phase map (by whole weeks remaining until the race):

* ``>= 9``  base       — aerobic volume, build the engine
* ``4..8``  build      — threshold + race-specific intensity
* ``3``     peak        — highest specificity, race simulation
* ``1..2``  taper       — cut volume, retain intensity, arrive fresh
* ``<= 0``  off         — race done / transition
"""

from __future__ import annotations

import math
from datetime import date

# Weekly-load multipliers applied to the chronic (CTL-derived) weekly load to set
# the target band for each phase. Taper deliberately drops volume.
_PHASE_LOAD_MULT: dict[str, float] = {
    "base": 1.00,
    "build": 1.10,
    "peak": 1.00,
    "taper": 0.55,
    "off": 0.30,
}

# Weekly running-volume (km) multipliers. Deliberately gentler than the load
# multipliers: the undated 21k is a standing-readiness goal, so an aerobic-volume
# floor is held year-round and only the race-week taper / post-race off week cut
# mileage hard. Easy runs carry this volume (polarized).
_PHASE_KM_MULT: dict[str, float] = {
    "base": 1.00,
    "build": 1.05,
    "peak": 0.90,
    "taper": 0.90,
    "off": 0.50,
}

# Recovery-based load scaler bounds. Gentle and err-high: default 1.0 (no cut),
# only trims when recovery is genuinely suppressed. A firmer floor applies on a
# red flag so a real hole still forces a deload.
_SCALER_NORMAL_FLOOR = 0.85
_SCALER_REDFLAG_FLOOR = 0.75
# Upper acute:chronic ratio the weekly-load band may never exceed — a safety rail
# against a rising-CTL ratchet quietly running the load away over a block.
_ACWR_CEILING = 1.25


def weeks_to_race(week_start: date, race_date: date) -> int:
    """Whole weeks remaining from the start of a plan week to the race.

    Parameters
    ----------
    week_start : datetime.date
        Monday of the plan week.
    race_date : datetime.date
        Date of the target race.

    Returns
    -------
    int
        Number of whole weeks until the race (0 once the race week has passed).

    Examples
    --------
    >>> weeks_to_race(date(2026, 6, 22), date(2026, 8, 2))
    6
    >>> weeks_to_race(date(2026, 7, 27), date(2026, 8, 2))
    1
    """
    days = (race_date - week_start).days
    if days <= 0:
        return 0
    return math.ceil(days / 7)


def classify_phase(weeks_remaining: int) -> str:
    """Map whole weeks remaining to a periodization phase.

    Parameters
    ----------
    weeks_remaining : int
        Output of :func:`weeks_to_race`.

    Returns
    -------
    str
        One of ``base``, ``build``, ``peak``, ``taper``, ``off``.
    """
    if weeks_remaining <= 0:
        return "off"
    if weeks_remaining <= 2:
        return "taper"
    if weeks_remaining == 3:
        return "peak"
    if weeks_remaining <= 8:
        return "build"
    return "base"


def phase_for_week(week_start: date, race_date: date) -> tuple[str, int]:
    """Return the phase and weeks-remaining for a plan week.

    Parameters
    ----------
    week_start : datetime.date
        Monday of the plan week.
    race_date : datetime.date
        Date of the target race.

    Returns
    -------
    tuple of (str, int)
        The phase label and the whole weeks remaining until the race.
    """
    remaining = weeks_to_race(week_start, race_date)
    return classify_phase(remaining), remaining


def recovery_scaler(
    readiness_scores: list[int],
    hrv_status: str | None,
    hrv_night: float | None,
    hrv_baseline_low: float | None,
    tsb: float,
) -> float:
    """Gentle, err-high recovery multiplier for the weekly-load band.

    Defaults to 1.0 (no cut) and only *subtracts* when a recovery signal is
    genuinely suppressed. Penalties are small so a normal down-week barely moves;
    a firmer floor applies on a red flag (readiness trend in the tank, deep
    negative TSB, or HRV LOW alongside a low readiness trend) so a real hole still
    forces a deload. HRV UNBALANCED is direction-aware — only penalized when the
    night value is at/below the baseline floor, since UNBALANCED can also mean
    unusually high HRV.

    Parameters
    ----------
    readiness_scores : list of int
        Recent daily morning readiness scores (oldest to newest); the last 5 are
        averaged.
    hrv_status : str or None
        Latest HRV status (BALANCED / UNBALANCED / LOW).
    hrv_night : float or None
        Latest nightly HRV.
    hrv_baseline_low : float or None
        Low edge of the HRV baseline.
    tsb : float
        Training-stress balance (form).

    Returns
    -------
    float
        Multiplier in [0.75, 1.0], rounded to 2 dp.
    """
    penalty = 0.0

    recent = [s for s in readiness_scores if s is not None][-5:]
    rmean = sum(recent) / len(recent) if recent else None
    if rmean is not None:
        if rmean < 40:
            penalty -= 0.15
        elif rmean < 55:
            penalty -= 0.10
        elif rmean < 65:
            penalty -= 0.05

    status = (hrv_status or "").upper()
    if status == "LOW":
        penalty -= 0.10
    elif status == "UNBALANCED":
        if hrv_night is not None and hrv_baseline_low is not None and hrv_night <= hrv_baseline_low:
            penalty -= 0.05

    if tsb < -25:
        penalty -= 0.10
    elif tsb < -10:
        penalty -= 0.05

    redflag = (
        (rmean is not None and rmean < 40)
        or tsb < -25
        or (status == "LOW" and rmean is not None and rmean < 50)
    )
    floor = _SCALER_REDFLAG_FLOOR if redflag else _SCALER_NORMAL_FLOOR
    return round(max(1.0 + penalty, floor), 2)


def weekly_km_target(base_weekly_km: float, phase: str) -> tuple[float, float]:
    """Phase-scaled weekly running-volume target (km), as a +/-10% band.

    Parameters
    ----------
    base_weekly_km : float
        The athlete's normal base weekly running volume.
    phase : str
        Phase label from :func:`classify_phase`.

    Returns
    -------
    tuple of (float, float)
        Lower and upper weekly-km targets.
    """
    midpoint = base_weekly_km * _PHASE_KM_MULT.get(phase, 1.0)
    return round(midpoint * 0.9, 1), round(midpoint * 1.1, 1)


def load_target_band(
    weekly_chronic_load: float, phase: str, scaler: float = 1.0
) -> tuple[float, float]:
    """Compute an ACWR-bounded weekly training-load target for a phase.

    The midpoint is the chronic (CTL-derived) weekly load scaled by the phase
    multiplier and the recovery ``scaler``; the band spans roughly an acute:chronic
    ratio of 0.9 to 1.1 around that midpoint. The upper bound is additionally
    capped at :data:`_ACWR_CEILING` times chronic so a rising-CTL ratchet cannot
    run the load away over a block.

    Parameters
    ----------
    weekly_chronic_load : float
        Chronic training load expressed per week (CTL * 7).
    phase : str
        Phase label from :func:`classify_phase`.
    scaler : float, optional
        Recovery multiplier from :func:`recovery_scaler` (default 1.0 = no cut).

    Returns
    -------
    tuple of (float, float)
        Lower and upper weekly-load targets.
    """
    mult = _PHASE_LOAD_MULT.get(phase, 1.0)
    midpoint = weekly_chronic_load * mult * scaler
    lower = round(midpoint * 0.9, 0)
    upper = round(midpoint * 1.1, 0)
    upper = min(upper, round(weekly_chronic_load * _ACWR_CEILING, 0))
    return min(lower, upper), upper


def upcoming_monday(today: date) -> date:
    """Return the Monday of the week to plan for.

    If ``today`` is already a Monday, that day is returned; otherwise the next
    Monday is returned. Run on the Sunday cron this yields the week about to
    start; run mid-week (manual) it yields next week.

    Parameters
    ----------
    today : datetime.date
        Reference date.

    Returns
    -------
    datetime.date
        Monday of the week to generate.
    """
    days_ahead = (0 - today.weekday()) % 7
    return today if days_ahead == 0 else date.fromordinal(today.toordinal() + days_ahead)
