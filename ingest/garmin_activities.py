"""Garmin activities ingestion module.

Fetches training activities directly from Garmin Connect and upserts them into
Supabase. Garmin is the sole source of activity data. It was already preferred
over the since-retired Strava feed because it keeps multisport sessions
(e.g. HYROX) as a single unified record with a native ``activityTrainingLoad``,
where Strava fragmented the same session into many zero-duration child
activities.

The same payload carries ``summarizedExerciseSets`` on strength and HIIT
sessions -- what was lifted, for how many sets and reps, and the heaviest load
-- so the per-exercise breakdown costs no extra API call and is harvested here.
The individual sets behind that summary do cost one call per session and live
in :mod:`ingest.exercise_sets`.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from garminconnect import Garmin
from supabase import Client

logger = logging.getLogger(__name__)

_MULTISPORT_TYPE_KEY = "multi_sport"


def _to_utc_iso(gmt_str: str | None) -> str | None:
    """Convert a Garmin ``startTimeGMT`` string to an ISO-8601 UTC timestamp.

    Garmin returns GMT timestamps as ``"YYYY-MM-DD HH:MM:SS"`` with no timezone
    marker. PostgREST needs an explicit offset to store the value correctly in a
    ``timestamptz`` column.

    Parameters
    ----------
    gmt_str : str or None
        Raw ``startTimeGMT`` value from the Garmin activity payload.

    Returns
    -------
    str or None
        ISO-8601 string with an explicit ``+00:00`` offset, or ``None`` if the
        input is falsy.
    """
    if not gmt_str:
        return None
    return gmt_str.replace(" ", "T") + "+00:00"


# Garmin serialises every load in grams: a 130 kg deadlift arrives as
# 130000.0. Kilograms are what anything downstream reads.
_GRAMS_PER_KG = 1000.0

# Garmin reports the summarised per-exercise duration in milliseconds, while the
# per-set duration in the exercise-sets payload is already in seconds. Two units
# for the same quantity in two payloads from the same session, so neither is
# assumed.
_MS_PER_S = 1000.0


def grams_to_kg(grams: float | int | None) -> float | None:
    """Convert a Garmin load in grams to kilograms, normalising its sentinels.

    Garmin uses two different values for "no load" in the same field: ``0``
    for a bodyweight movement and ``-1`` for a set whose weight was never
    entered. Both become ``None``. Kept as numbers they would look like
    measurements while dragging every tonnage total and mean load toward zero.

    Parameters
    ----------
    grams : float or int or None
        Raw ``weight``, ``maxWeight`` or ``volume`` value.

    Returns
    -------
    float or None
        The load in kilograms, or ``None`` when no load was recorded.

    Examples
    --------
    >>> grams_to_kg(130000.0)
    130.0
    >>> grams_to_kg(-1.0) is None
    True
    >>> grams_to_kg(0) is None
    True
    """
    if grams is None or grams <= 0:
        return None
    return float(grams) / _GRAMS_PER_KG


def _parse_exercise(activity_id: int, entry: dict[str, Any]) -> dict[str, Any]:
    """Map one ``summarizedExerciseSets`` entry to the per-exercise schema.

    Parameters
    ----------
    activity_id : int
        The session the exercise belongs to.
    entry : dict
        One entry of the activity payload's ``summarizedExerciseSets`` list.

    Returns
    -------
    dict
        A row ready to insert into ``garmin_activity_exercises``.
    """
    duration_ms = entry.get("duration")
    return {
        "activity_id": activity_id,
        "category": entry.get("category") or "UNKNOWN",
        # Empty string rather than None: this is part of the primary key, and
        # most of the history names only the category.
        "sub_category": entry.get("subCategory") or "",
        "sets": entry.get("sets"),
        "reps": entry.get("reps"),
        "volume_kg": grams_to_kg(entry.get("volume")),
        "max_weight_kg": grams_to_kg(entry.get("maxWeight")),
        "active_duration_s": None if duration_ms is None else duration_ms / _MS_PER_S,
    }


def _parse_activity(activity: dict[str, Any]) -> dict[str, Any]:
    """Map a raw Garmin activity payload to the ``garmin_activities`` schema.

    Parameters
    ----------
    activity : dict
        A single activity dict as returned by
        ``Garmin.get_activities_by_date``.

    Returns
    -------
    dict
        A row ready to upsert into ``garmin_activities``.
    """
    activity_type = activity.get("activityType") or {}
    type_key = activity_type.get("typeKey")

    return {
        "activity_id": activity.get("activityId"),
        "parent_id": activity.get("parentId"),
        "start_time": _to_utc_iso(activity.get("startTimeGMT")),
        "start_time_local": activity.get("startTimeLocal"),
        "activity_name": activity.get("activityName"),
        "activity_type": type_key,
        "duration_s": activity.get("duration"),
        "elapsed_duration_s": activity.get("elapsedDuration"),
        "moving_duration_s": activity.get("movingDuration"),
        "distance_m": activity.get("distance"),
        "elevation_gain_m": activity.get("elevationGain"),
        "avg_hr": activity.get("averageHR"),
        "max_hr": activity.get("maxHR"),
        "calories": activity.get("calories"),
        "training_load": activity.get("activityTrainingLoad"),
        "aerobic_te": activity.get("aerobicTrainingEffect"),
        "anaerobic_te": activity.get("anaerobicTrainingEffect"),
        "avg_cadence": activity.get("averageRunningCadenceInStepsPerMinute"),
        # Running dynamics. Garmin reports stride length and vertical
        # oscillation in centimetres, vertical ratio as a percentage and
        # ground contact time in milliseconds; the column names carry the
        # unit so nothing downstream has to infer it. Absent on non-running
        # activities, and on the odd run whose distance failed to record.
        "avg_stride_length_cm": activity.get("avgStrideLength"),
        "avg_vertical_oscillation_cm": activity.get("avgVerticalOscillation"),
        "avg_vertical_ratio_pct": activity.get("avgVerticalRatio"),
        "avg_ground_contact_time_ms": activity.get("avgGroundContactTime"),
        "is_multisport": type_key == _MULTISPORT_TYPE_KEY,
    }


def has_exercise_sets(activity: dict[str, Any]) -> bool:
    """Report whether an activity payload carries a per-exercise breakdown.

    The presence of ``summarizedExerciseSets`` is the trigger, in preference to
    an allowlist of activity types. Checked across the whole history on
    2026-09-09, the key appears on exactly the 50 set-bearing sessions -- 36
    ``strength_training`` and 14 ``hiit`` -- and on none of the 178 others, so
    Garmin already answers the question a type list would only approximate, and
    keeps answering it if a session is ever logged under a new type.

    Parameters
    ----------
    activity : dict
        A single activity dict from ``Garmin.get_activities_by_date``.

    Returns
    -------
    bool
        True when the activity has exercises to harvest.

    Examples
    --------
    >>> has_exercise_sets({"summarizedExerciseSets": [{"category": "SQUAT"}]})
    True
    >>> has_exercise_sets({"activityType": {"typeKey": "running"}})
    False
    """
    return bool(activity.get("summarizedExerciseSets"))


def _replace_exercises(supabase: Client, activity_id: int, rows: list[dict]) -> None:
    """Rewrite one session's per-exercise rows.

    Delete-then-insert rather than upsert, because the primary key includes the
    exercise itself. Renaming a movement in Garmin Connect -- which is how an
    ``UNKNOWN`` set becomes a named lift -- writes a row under a new key and
    would leave the old one behind as a ghost exercise that was never
    performed. The two statements are not atomic; a failure between them loses
    that session's exercises until the next run re-reads and rewrites them.

    Parameters
    ----------
    supabase : Client
        Authenticated Supabase client.
    activity_id : int
        The session being rewritten.
    rows : list of dict
        Parsed ``garmin_activity_exercises`` rows for that session.
    """
    supabase.table("garmin_activity_exercises").delete().eq(
        "activity_id", activity_id
    ).execute()
    if rows:
        supabase.table("garmin_activity_exercises").insert(rows).execute()


def ingest(supabase: Client, garmin: Garmin, since: date) -> list[dict[str, Any]]:
    """Fetch Garmin activities since a date and upsert them into Supabase.

    Also writes the per-exercise breakdown of every set-bearing session, which
    rides along in the same payload.

    Parameters
    ----------
    supabase : Client
        Authenticated Supabase client.
    garmin : Garmin
        Authenticated Garmin client (reused from the wellness ingestion so we
        do not trigger a second SSO login).
    since : date
        Fetch activities from this date onwards.

    Returns
    -------
    list of dict
        The raw activity payloads, so :mod:`ingest.exercise_sets` can pick out
        the set-bearing sessions without fetching the same window again. Empty
        when the fetch failed or the window holds nothing.
    """
    today = date.today()
    try:
        activities = garmin.get_activities_by_date(since.isoformat(), today.isoformat())
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not fetch Garmin activities: %s", exc)
        return []

    if not activities:
        logger.info("No Garmin activities found from %s to %s", since, today)
        return []

    rows = [_parse_activity(a) for a in activities if a.get("activityId") is not None]

    if rows:
        supabase.table("garmin_activities").upsert(rows, on_conflict="activity_id").execute()

    multisport = sum(1 for r in rows if r["is_multisport"])
    logger.info(
        "Garmin activities ingestion complete: %d activities (%d multisport)",
        len(rows),
        multisport,
    )

    # After the activities themselves: the exercise rows carry a foreign key
    # onto them, so a session logged inside this window has to exist first.
    exercises = 0
    sessions = 0
    for activity in activities:
        activity_id = activity.get("activityId")
        if activity_id is None or not has_exercise_sets(activity):
            continue
        parsed = [
            _parse_exercise(activity_id, entry)
            for entry in activity["summarizedExerciseSets"]
        ]
        try:
            _replace_exercises(supabase, activity_id, parsed)
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not store exercises for activity %s: %s", activity_id, exc)
            continue
        sessions += 1
        exercises += len(parsed)

    logger.info(
        "Exercise summaries stored: %d exercises across %d sessions",
        exercises,
        sessions,
    )
    return activities
