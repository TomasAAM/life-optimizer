"""Supabase read access for the dashboard.

Pulls the raw Garmin activity and wellness data needed to compute the
training-load model and HRV trend. PostgREST caps a single response at 1000
rows, so the per-reading HRV table is fetched with explicit pagination.
"""

from __future__ import annotations

import os

import pandas as pd
from supabase import Client, create_client

_PAGE_SIZE = 1000


def get_supabase_client() -> Client:
    """Create an authenticated Supabase client from environment variables.

    Returns
    -------
    supabase.Client
        Client authenticated with the service role key.
    """
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def _fetch_all(supabase: Client, table: str, columns: str, order_col: str) -> pd.DataFrame:
    """Fetch every row of a table, paginating past the PostgREST 1000-row cap.

    Parameters
    ----------
    supabase : supabase.Client
        Authenticated Supabase client.
    table : str
        Table name to read.
    columns : str
        Comma-separated column list to select.
    order_col : str
        Column to order by (stable pagination requires a deterministic order).

    Returns
    -------
    pandas.DataFrame
        All rows, concatenated across pages.
    """
    frames: list[pd.DataFrame] = []
    offset = 0
    while True:
        result = (
            supabase.table(table)
            .select(columns)
            .order(order_col)
            .range(offset, offset + _PAGE_SIZE - 1)
            .execute()
        )
        rows = result.data or []
        if not rows:
            break
        frames.append(pd.DataFrame(rows))
        if len(rows) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE

    if not frames:
        return pd.DataFrame(columns=columns.split(","))
    return pd.concat(frames, ignore_index=True)


def fetch_activities(supabase: Client) -> pd.DataFrame:
    """Fetch Garmin activities with their native training load.

    Returns
    -------
    pandas.DataFrame
        Columns: start_time_local, activity_name, activity_type,
        training_load, is_multisport.
    """
    return _fetch_all(
        supabase,
        "garmin_activities",
        "start_time_local,activity_name,activity_type,training_load,is_multisport",
        "start_time",
    )


def fetch_running_volume(supabase: Client) -> pd.DataFrame:
    """Fetch the fields needed to compute recent actual running volume.

    Separate from :func:`fetch_activities` (which selects the training-load
    columns) because the volume helper only needs the date, type and distance.

    Returns
    -------
    pandas.DataFrame
        Columns: start_time_local, activity_type, distance_m.
    """
    return _fetch_all(
        supabase,
        "garmin_activities",
        "start_time_local,activity_type,distance_m",
        "start_time",
    )


def fetch_hrv(supabase: Client) -> pd.DataFrame:
    """Fetch Garmin HRV readings (per-reading; aggregated downstream).

    Returns
    -------
    pandas.DataFrame
        Columns: date, hrv_avg_night, hrv_weekly_avg, hrv_baseline_low,
        hrv_baseline_high, hrv_status.
    """
    return _fetch_all(
        supabase,
        "garmin_hrv_readings",
        "date,hrv_avg_night,hrv_weekly_avg,hrv_baseline_low,hrv_baseline_high,hrv_status",
        "date",
    )


def fetch_readiness(supabase: Client) -> pd.DataFrame:
    """Fetch Garmin training-readiness rows for auto-regulation.

    Returns
    -------
    pandas.DataFrame
        Columns: date, ts, score, level, recovery_time_h, acute_load.
    """
    return _fetch_all(
        supabase,
        "garmin_training_readiness",
        "date,ts,score,level,recovery_time_h,acute_load",
        "date",
    )


def fetch_training_zones(supabase: Client) -> pd.DataFrame:
    """Fetch the lactate-anchored training zones.

    Returns
    -------
    pandas.DataFrame
        One row per zone (Recovery..VO2max) with HR/pace bounds and the LT
        anchors, ordered by ``zone_index``.
    """
    result = supabase.table("training_zones").select("*").order("zone_index").execute()
    rows = result.data or []
    return pd.DataFrame(rows)


def fetch_current_plan_week(supabase: Client, today_iso: str) -> dict | None:
    """Fetch the plan-week header for the week in progress.

    Returns the most recent week whose Monday is on or before ``today`` (the week
    currently being trained). Falls back to the earliest upcoming week when the
    whole plan is still in the future, and to ``None`` when no plan exists.

    Parameters
    ----------
    supabase : supabase.Client
        Authenticated Supabase client.
    today_iso : str
        Today's date as an ISO string.

    Returns
    -------
    dict or None
        The current ``training_plan_weeks`` row, or ``None`` if no plan exists.
    """
    current = (
        supabase.table("training_plan_weeks")
        .select("*")
        .lte("week_start", today_iso)
        .order("week_start", desc=True)
        .limit(1)
        .execute()
    )
    if current.data:
        return current.data[0]
    upcoming = (
        supabase.table("training_plan_weeks")
        .select("*")
        .order("week_start")
        .limit(1)
        .execute()
    )
    rows = upcoming.data or []
    return rows[0] if rows else None


def fetch_plan_block(supabase: Client, from_week_iso: str) -> list[dict]:
    """Fetch the plan-week headers from a given week onward (the current block).

    Parameters
    ----------
    supabase : supabase.Client
        Authenticated Supabase client.
    from_week_iso : str
        ISO date of the first week to include (its Monday).

    Returns
    -------
    list of dict
        ``training_plan_weeks`` rows with ``week_start >= from_week_iso``, ordered
        chronologically.
    """
    result = (
        supabase.table("training_plan_weeks")
        .select("*")
        .gte("week_start", from_week_iso)
        .order("week_start")
        .execute()
    )
    return result.data or []


def fetch_planned_sessions(supabase: Client, week_start: str) -> pd.DataFrame:
    """Fetch the prescribed sessions for a given plan week.

    Parameters
    ----------
    supabase : supabase.Client
        Authenticated Supabase client.
    week_start : str
        ISO date of the plan week's Monday.

    Returns
    -------
    pandas.DataFrame
        Sessions ordered by ``session_date``.
    """
    result = (
        supabase.table("planned_sessions")
        .select("*")
        .eq("week_start", week_start)
        .order("session_date")
        .execute()
    )
    rows = result.data or []
    return pd.DataFrame(rows)
