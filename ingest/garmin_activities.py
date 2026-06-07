"""Garmin activities ingestion module.

Fetches training activities directly from Garmin Connect and upserts them into
Supabase. Garmin is the source of truth for activities because it keeps
multisport sessions (e.g. HYROX) as a single unified record with a native
``activityTrainingLoad``, whereas Strava fragments the same session into many
zero-duration child activities.
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
        "is_multisport": type_key == _MULTISPORT_TYPE_KEY,
    }


def ingest(supabase: Client, garmin: Garmin, since: date) -> None:
    """Fetch Garmin activities since a date and upsert them into Supabase.

    Parameters
    ----------
    supabase : Client
        Authenticated Supabase client.
    garmin : Garmin
        Authenticated Garmin client (reused from the wellness ingestion so we
        do not trigger a second SSO login).
    since : date
        Fetch activities from this date onwards.
    """
    today = date.today()
    try:
        activities = garmin.get_activities_by_date(since.isoformat(), today.isoformat())
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not fetch Garmin activities: %s", exc)
        return

    if not activities:
        logger.info("No Garmin activities found from %s to %s", since, today)
        return

    rows = [_parse_activity(a) for a in activities if a.get("activityId") is not None]

    if rows:
        supabase.table("garmin_activities").upsert(rows, on_conflict="activity_id").execute()

    multisport = sum(1 for r in rows if r["is_multisport"])
    logger.info(
        "Garmin activities ingestion complete: %d activities (%d multisport)",
        len(rows),
        multisport,
    )
