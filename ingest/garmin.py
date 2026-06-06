"""Garmin Connect ingestion module.

Fetches daily wellness data and raw time-series readings from
Garmin Connect and upserts them into Supabase.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Any

from garminconnect import Garmin
from supabase import Client

logger = logging.getLogger(__name__)


def get_client() -> Garmin:
    """Authenticate with Garmin Connect.

    Returns
    -------
    Garmin
        Authenticated Garmin client.
    """
    email = os.environ["GARMIN_EMAIL"]
    password = os.environ["GARMIN_PASSWORD"]
    client = Garmin(email=email, password=password)
    client.login()
    logger.info("Authenticated with Garmin Connect")
    return client


def _date_range(since: date, until: date) -> list[date]:
    """Generate a list of dates from since to until inclusive.

    Parameters
    ----------
    since : date
        Start date.
    until : date
        End date.

    Returns
    -------
    list[date]
        All dates in the range.
    """
    days = (until - since).days + 1
    return [since + timedelta(days=i) for i in range(days)]


def _ingest_daily_wellness(garmin: Garmin, supabase: Client, target_date: date) -> None:
    """Fetch and upsert daily wellness summary for one date.

    Parameters
    ----------
    garmin : Garmin
        Authenticated Garmin client.
    supabase : Client
        Authenticated Supabase client.
    target_date : date
        The date to fetch data for.
    """
    date_str = target_date.isoformat()
    try:
        summary = garmin.get_user_summary(date_str)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not fetch daily summary for %s: %s", date_str, exc)
        return

    row = {
        "date": date_str,
        "resting_hr": summary.get("restingHeartRate"),
        "min_hr": summary.get("minHeartRate"),
        "max_hr": summary.get("maxHeartRate"),
        "avg_stress": summary.get("averageStressLevel"),
        "max_stress": summary.get("maxStressLevel"),
        "avg_spo2": summary.get("averageSpo2"),
        "lowest_spo2": summary.get("lowestSpo2"),
        "body_battery_wake": summary.get("bodyBatteryAtWakeTime"),
        "body_battery_high": summary.get("bodyBatteryHighestValue"),
        "body_battery_low": summary.get("bodyBatteryLowestValue"),
        "body_battery_now": summary.get("bodyBatteryMostRecentValue"),
        "total_steps": summary.get("totalSteps"),
        "active_calories": summary.get("activeKilocalories"),
        "total_calories": summary.get("totalKilocalories"),
        "avg_respiration": summary.get("avgWakingRespirationValue"),
    }
    supabase.table("garmin_daily_wellness").upsert(row, on_conflict="date").execute()
    logger.info("Upserted daily wellness for %s", date_str)


def _ingest_hrv(garmin: Garmin, supabase: Client, target_date: date) -> None:
    """Fetch and upsert HRV readings for one date.

    Parameters
    ----------
    garmin : Garmin
        Authenticated Garmin client.
    supabase : Client
        Authenticated Supabase client.
    target_date : date
        The date to fetch data for.
    """
    date_str = target_date.isoformat()
    try:
        data = garmin.get_hrv_data(date_str)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not fetch HRV for %s: %s", date_str, exc)
        return

    if not data or "hrvSummary" not in data:
        return

    summary = data["hrvSummary"]
    readings = data.get("hrvReadings", [])

    rows = [
        {
            "date": date_str,
            "ts": r.get("hrvTime"),
            "hrv_ms": r.get("hrvValue"),
            "hrv_avg_night": summary.get("lastNight"),
            "hrv_weekly_avg": summary.get("weeklyAvg"),
            "hrv_baseline_low": summary.get("baseline", {}).get("lowUpper"),
            "hrv_baseline_high": summary.get("baseline", {}).get("balancedUpper"),
            "hrv_status": summary.get("status"),
        }
        for r in readings
        if r.get("hrvTime")
    ]

    if rows:
        supabase.table("garmin_hrv_readings").upsert(rows, on_conflict="date,ts").execute()
        logger.info("Upserted %d HRV readings for %s", len(rows), date_str)


def _ingest_heart_rate(garmin: Garmin, supabase: Client, target_date: date) -> None:
    """Fetch and upsert heart rate readings for one date.

    Parameters
    ----------
    garmin : Garmin
        Authenticated Garmin client.
    supabase : Client
        Authenticated Supabase client.
    target_date : date
        The date to fetch data for.
    """
    date_str = target_date.isoformat()
    try:
        data = garmin.get_heart_rates(date_str)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not fetch heart rates for %s: %s", date_str, exc)
        return

    values = data.get("heartRateValues") or []
    rows = [
        {"date": date_str, "ts": v[0], "hr_bpm": v[1]}
        for v in values
        if v[1] is not None
    ]

    if rows:
        supabase.table("garmin_heart_rate_readings").upsert(rows, on_conflict="date,ts").execute()
        logger.info("Upserted %d HR readings for %s", len(rows), date_str)


def _ingest_stress(garmin: Garmin, supabase: Client, target_date: date) -> None:
    """Fetch and upsert stress readings for one date.

    Parameters
    ----------
    garmin : Garmin
        Authenticated Garmin client.
    supabase : Client
        Authenticated Supabase client.
    target_date : date
        The date to fetch data for.
    """
    date_str = target_date.isoformat()
    try:
        data = garmin.get_stress_data(date_str)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not fetch stress for %s: %s", date_str, exc)
        return

    values = data.get("stressValuesArray") or []
    rows = [
        {"date": date_str, "ts": v[0], "stress_level": v[1]}
        for v in values
    ]

    if rows:
        supabase.table("garmin_stress_readings").upsert(rows, on_conflict="date,ts").execute()
        logger.info("Upserted %d stress readings for %s", len(rows), date_str)


def _ingest_training_readiness(garmin: Garmin, supabase: Client, target_date: date) -> None:
    """Fetch and upsert training readiness snapshots for one date.

    Parameters
    ----------
    garmin : Garmin
        Authenticated Garmin client.
    supabase : Client
        Authenticated Supabase client.
    target_date : date
        The date to fetch data for.
    """
    date_str = target_date.isoformat()
    try:
        data = garmin.get_training_readiness(date_str)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not fetch training readiness for %s: %s", date_str, exc)
        return

    if not data:
        return

    snapshots = data if isinstance(data, list) else [data]
    rows = [
        {
            "date": date_str,
            "ts": s.get("timestamp"),
            "context": s.get("context"),
            "score": s.get("score"),
            "level": s.get("level"),
            "recovery_time_h": s.get("recoveryTime"),
            "acute_load": s.get("acuteLoad"),
            "hrv_weekly_avg": s.get("hrvWeeklyAverage"),
            "sleep_score": s.get("sleepScore"),
        }
        for s in snapshots
        if s.get("timestamp")
    ]

    if rows:
        supabase.table("garmin_training_readiness").upsert(rows, on_conflict="date,ts").execute()
        logger.info("Upserted %d readiness snapshots for %s", len(rows), date_str)


def ingest(supabase: Client, since: date) -> None:
    """Fetch new Garmin data and upsert into Supabase.

    Parameters
    ----------
    supabase : Client
        Authenticated Supabase client.
    since : date
        Fetch data from this date onwards.
    """
    garmin = get_client()
    today = date.today()
    dates = _date_range(since, today)

    logger.info("Ingesting Garmin data for %d days (%s to %s)", len(dates), since, today)

    for target_date in dates:
        _ingest_daily_wellness(garmin, supabase, target_date)
        _ingest_hrv(garmin, supabase, target_date)
        _ingest_heart_rate(garmin, supabase, target_date)
        _ingest_stress(garmin, supabase, target_date)
        _ingest_training_readiness(garmin, supabase, target_date)

    logger.info("Garmin ingestion complete")
