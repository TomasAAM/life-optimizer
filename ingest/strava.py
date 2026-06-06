"""Strava ingestion module.

Fetches activities and per-second streams from the Strava API
and upserts them into Supabase.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests
from supabase import Client

logger = logging.getLogger(__name__)

STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"

STREAM_TYPES = [
    "time",
    "heartrate",
    "cadence",
    "distance",
    "altitude",
    "velocity_smooth",
    "watts",
    "grade_smooth",
    "latlng",
    "temp",
]


@dataclass(frozen=True)
class StravaConfig:
    """Strava API credentials."""

    client_id: str
    client_secret: str
    refresh_token: str

    @classmethod
    def from_env(cls) -> "StravaConfig":
        """Load credentials from environment variables."""
        return cls(
            client_id=os.environ["STRAVA_CLIENT_ID"],
            client_secret=os.environ["STRAVA_CLIENT_SECRET"],
            refresh_token=os.environ["STRAVA_REFRESH_TOKEN"],
        )


def get_access_token(config: StravaConfig) -> str:
    """Exchange refresh token for a short-lived access token.

    Parameters
    ----------
    config : StravaConfig
        Strava API credentials.

    Returns
    -------
    str
        A valid access token (expires in 6 hours).
    """
    response = requests.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "refresh_token": config.refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def fetch_activities(
    access_token: str,
    after: datetime,
    per_page: int = 100,
) -> list[dict[str, Any]]:
    """Fetch all activities after a given datetime.

    Parameters
    ----------
    access_token : str
        Valid Strava access token.
    after : datetime
        Only return activities after this timestamp.
    per_page : int
        Page size (max 100).

    Returns
    -------
    list[dict[str, Any]]
        Raw activity objects from the Strava API.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    activities: list[dict[str, Any]] = []
    page = 1
    after_ts = int(after.timestamp())

    while True:
        response = requests.get(
            f"{STRAVA_API_BASE}/athlete/activities",
            headers=headers,
            params={"after": after_ts, "per_page": per_page, "page": page},
            timeout=30,
        )
        response.raise_for_status()
        batch = response.json()
        if not batch:
            break
        activities.extend(batch)
        if len(batch) < per_page:
            break
        page += 1

    logger.info("Fetched %d activities from Strava", len(activities))
    return activities


def fetch_activity_streams(
    access_token: str,
    activity_id: int,
) -> dict[str, list[Any]]:
    """Fetch per-second time-series streams for a single activity.

    Parameters
    ----------
    access_token : str
        Valid Strava access token.
    activity_id : int
        Strava activity ID.

    Returns
    -------
    dict[str, list[Any]]
        Mapping of stream type to list of values.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(
        f"{STRAVA_API_BASE}/activities/{activity_id}/streams",
        headers=headers,
        params={"keys": ",".join(STREAM_TYPES), "key_by_type": True},
        timeout=30,
    )
    if response.status_code == 404:
        return {}
    response.raise_for_status()
    raw = response.json()
    return {k: v["data"] for k, v in raw.items()}


def _parse_activity(activity: dict[str, Any]) -> dict[str, Any]:
    """Map a raw Strava activity to our database schema.

    Parameters
    ----------
    activity : dict[str, Any]
        Raw activity object from Strava API.

    Returns
    -------
    dict[str, Any]
        Row ready for upsert into strava_activities.
    """
    return {
        "activity_id": activity["id"],
        "start_date": activity.get("start_date"),
        "sport_type": activity.get("sport_type"),
        "name": activity.get("name"),
        "distance_m": activity.get("distance"),
        "moving_time_s": activity.get("moving_time"),
        "elapsed_time_s": activity.get("elapsed_time"),
        "elevation_gain_m": activity.get("total_elevation_gain"),
        "avg_hr": activity.get("average_heartrate"),
        "max_hr": activity.get("max_heartrate"),
        "avg_watts": activity.get("average_watts"),
        "avg_speed_ms": activity.get("average_speed"),
        "avg_cadence": activity.get("average_cadence"),
        "relative_effort": activity.get("suffer_score"),
        "calories": activity.get("kilojoules"),
    }


def _parse_streams(
    activity_id: int,
    streams: dict[str, list[Any]],
) -> list[dict[str, Any]]:
    """Map raw stream data to rows for strava_activity_streams.

    Parameters
    ----------
    activity_id : int
        Strava activity ID.
    streams : dict[str, list[Any]]
        Mapping of stream type to list of values.

    Returns
    -------
    list[dict[str, Any]]
        Rows ready for upsert into strava_activity_streams.
    """
    if not streams or "time" not in streams:
        return []

    time_series = streams["time"]
    rows = []

    for i, t in enumerate(time_series):
        latlng = streams.get("latlng", [])
        lat = latlng[i][0] if i < len(latlng) and latlng[i] else None
        lng = latlng[i][1] if i < len(latlng) and latlng[i] else None

        def safe_get(key: str) -> Any:
            arr = streams.get(key, [])
            return arr[i] if i < len(arr) else None

        rows.append({
            "activity_id": activity_id,
            "t_seconds": t,
            "hr_bpm": safe_get("heartrate"),
            "cadence": safe_get("cadence"),
            "distance_m": safe_get("distance"),
            "altitude_m": safe_get("altitude"),
            "velocity_ms": safe_get("velocity_smooth"),
            "watts": safe_get("watts"),
            "grade_pct": safe_get("grade_smooth"),
            "lat": lat,
            "lng": lng,
            "temp_c": safe_get("temp"),
        })

    return rows


def ingest(supabase: Client, since: datetime) -> None:
    """Fetch new Strava data and upsert into Supabase.

    Parameters
    ----------
    supabase : Client
        Authenticated Supabase client.
    since : datetime
        Only fetch activities after this datetime.
    """
    config = StravaConfig.from_env()
    access_token = get_access_token(config)
    activities = fetch_activities(access_token, after=since)

    for activity in activities:
        activity_id = activity["id"]

        row = _parse_activity(activity)
        supabase.table("strava_activities").upsert(row, on_conflict="activity_id").execute()
        logger.info("Upserted activity %s", activity_id)

        streams = fetch_activity_streams(access_token, activity_id)
        stream_rows = _parse_streams(activity_id, streams)

        if stream_rows:
            batch_size = 500
            for i in range(0, len(stream_rows), batch_size):
                batch = stream_rows[i : i + batch_size]
                supabase.table("strava_activity_streams").upsert(
                    batch, on_conflict="activity_id,t_seconds"
                ).execute()
            logger.info("Upserted %d stream rows for activity %s", len(stream_rows), activity_id)

    logger.info("Strava ingestion complete: %d activities processed", len(activities))
