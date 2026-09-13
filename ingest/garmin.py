"""Garmin Connect ingestion module.

Fetches daily wellness data and raw time-series readings from
Garmin Connect and upserts them into Supabase.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from garminconnect import Garmin
from supabase import Client

from ingest.status import SourceResult

logger = logging.getLogger(__name__)


def _to_iso_ts(value: Any) -> str | None:
    """Normalize a Garmin timestamp into an ISO-8601 UTC string.

    Garmin returns per-reading timestamps in mixed formats: epoch milliseconds
    (e.g. heart rate and stress arrays) or already-formatted GMT strings (e.g.
    some HRV payloads). PostgREST needs an explicit ISO timestamp for
    ``timestamptz`` columns.

    Parameters
    ----------
    value : Any
        Epoch-milliseconds int/float, or a string timestamp, or ``None``.

    Returns
    -------
    str or None
        ISO-8601 UTC timestamp, or ``None`` if the input is falsy.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc).isoformat()
    # Already a string: ensure it has a 'T' separator; assume GMT if no offset.
    text = str(value).replace(" ", "T")
    if text.endswith("Z") or "+" in text:
        return text
    return text + "+00:00"

# Cache directory for garth OAuth tokens — avoids re-authenticating on every run
# and prevents hitting Garmin's SSO rate limit.
_TOKEN_DIR = Path(__file__).parent.parent / ".garth_tokens"


def get_client() -> Garmin:
    """Authenticate with Garmin Connect, using a cached token when available.

    Token lookup order:
    1. ``.garth_tokens/`` in the project root (written by this script after
       a successful login).
    2. ``~/.garminconnect`` — the default location used by the Garmin MCP
       server, so a shared desktop session can bootstrap the pipeline without
       a fresh SSO login.
    3. Full SSO login using GARMIN_EMAIL / GARMIN_PASSWORD (writes a new
       token to ``.garth_tokens/`` for future runs).

    Returns
    -------
    Garmin
        Authenticated Garmin client.
    """
    email = os.environ["GARMIN_EMAIL"]
    password = os.environ["GARMIN_PASSWORD"]

    # Directories to probe for cached tokens, in priority order.
    _MCP_TOKEN_DIR = Path.home() / ".garminconnect"
    token_candidates = [_TOKEN_DIR, _MCP_TOKEN_DIR]

    for token_dir in token_candidates:
        if token_dir.exists():
            try:
                client = Garmin(email=email, password=password)
                client.login(str(token_dir))
                logger.info("Authenticated with Garmin Connect (token from %s)", token_dir)
                # Mirror to project-local cache so the MCP dir isn't a hard dependency.
                if token_dir != _TOKEN_DIR:
                    _TOKEN_DIR.mkdir(parents=True, exist_ok=True)
                    client.client.dump(str(_TOKEN_DIR))
                    logger.info("Token mirrored to %s", _TOKEN_DIR)
                return client
            except Exception:  # noqa: BLE001
                logger.info("Token at %s invalid or expired — trying next source", token_dir)

    logger.info("No valid cached token found — performing full SSO login")
    client = Garmin(email=email, password=password)
    client.login()
    _TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    client.client.dump(str(_TOKEN_DIR))
    logger.info("Authenticated with Garmin Connect (full login, token saved to %s)", _TOKEN_DIR)
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


def _ingest_daily_wellness(
    garmin: Garmin, supabase: Client, target_date: date
) -> int | None:
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
        return None

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
    return 1


def _ingest_hrv(garmin: Garmin, supabase: Client, target_date: date) -> int | None:
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
        return None

    if not data or "hrvSummary" not in data:
        return 0

    summary = data["hrvSummary"]
    readings = data.get("hrvReadings", [])

    rows = [
        {
            "date": date_str,
            "ts": _to_iso_ts(r.get("readingTimeGMT")),
            "hrv_ms": r.get("hrvValue"),
            "hrv_avg_night": summary.get("lastNightAvg"),
            "hrv_weekly_avg": summary.get("weeklyAvg"),
            "hrv_baseline_low": summary.get("baseline", {}).get("lowUpper"),
            "hrv_baseline_high": summary.get("baseline", {}).get("balancedUpper"),
            "hrv_status": summary.get("status"),
        }
        for r in readings
        if r.get("readingTimeGMT")
    ]

    if rows:
        supabase.table("garmin_hrv_readings").upsert(rows, on_conflict="date,ts").execute()
        logger.info("Upserted %d HRV readings for %s", len(rows), date_str)
    return len(rows)


def _ingest_heart_rate(
    garmin: Garmin, supabase: Client, target_date: date
) -> int | None:
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
        return None

    values = data.get("heartRateValues") or []
    rows = [
        {"date": date_str, "ts": _to_iso_ts(v[0]), "hr_bpm": v[1]}
        for v in values
        if v[1] is not None
    ]

    if rows:
        supabase.table("garmin_heart_rate_readings").upsert(rows, on_conflict="date,ts").execute()
        logger.info("Upserted %d HR readings for %s", len(rows), date_str)
    return len(rows)


def _ingest_stress(garmin: Garmin, supabase: Client, target_date: date) -> int | None:
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
        return None

    values = data.get("stressValuesArray") or []
    rows = [
        {"date": date_str, "ts": _to_iso_ts(v[0]), "stress_level": v[1]}
        for v in values
    ]

    if rows:
        supabase.table("garmin_stress_readings").upsert(rows, on_conflict="date,ts").execute()
        logger.info("Upserted %d stress readings for %s", len(rows), date_str)
    return len(rows)


def _ingest_training_readiness(
    garmin: Garmin, supabase: Client, target_date: date
) -> int | None:
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
        return None

    if not data:
        return 0

    snapshots = data if isinstance(data, list) else [data]
    rows = [
        {
            "date": date_str,
            "ts": _to_iso_ts(s.get("timestamp")),
            "context": s.get("context"),
            "score": s.get("score"),
            "level": s.get("level"),
            # Garmin reports `recoveryTime` in minutes; store it as hours.
            "recovery_time_h": (
                None
                if s.get("recoveryTime") is None
                else round(s.get("recoveryTime") / 60, 1)
            ),
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
    return len(rows)


def ingest(
    supabase: Client,
    since: date | Mapping[str, date],
    client: Garmin | None = None,
) -> SourceResult:
    """Fetch new Garmin data and upsert into Supabase.

    Parameters
    ----------
    supabase : Client
        Authenticated Supabase client.
    since : date or mapping of str to date
        Fetch data from this date onwards. A mapping supplies independent
        watermarks for ``wellness``, ``hrv``, ``heart_rate``, ``stress``, and
        ``readiness`` so a successful endpoint cannot advance a failed one.
    client : Garmin, optional
        An already-authenticated Garmin client to reuse. If omitted, a new
        client is created via :func:`get_client`. Passing a shared client
        avoids a second SSO login when wellness and activity ingestion run
        in the same pipeline.
    Returns
    -------
    SourceResult
        Aggregate status across all endpoint-day requests.

    Examples
    --------
    Supply a separate restart date for each Garmin endpoint::

        result = ingest(supabase, since=watermarks, client=garmin_client)
        assert result.source == "garmin_wellness"
    """
    garmin = client or get_client()
    today = date.today()
    endpoints = (
        ("wellness", _ingest_daily_wellness),
        ("hrv", _ingest_hrv),
        ("heart_rate", _ingest_heart_rate),
        ("stress", _ingest_stress),
        ("readiness", _ingest_training_readiness),
    )
    attempted = 0
    succeeded = 0
    rows_written = 0

    for source, ingest_one in endpoints:
        endpoint_since = (
            since.get(source, today) if isinstance(since, Mapping) else since
        )
        dates = _date_range(endpoint_since, today)
        logger.info(
            "Ingesting Garmin %s for %d days (%s to %s)",
            source,
            len(dates),
            endpoint_since,
            today,
        )
        for target_date in dates:
            attempted += 1
            written = ingest_one(garmin, supabase, target_date)
            if written is None:
                continue
            succeeded += 1
            rows_written += written

    detail_code = "partial_garmin_endpoint_failure" if succeeded < attempted else None
    result = SourceResult.from_counts(
        source="garmin_wellness",
        attempted=attempted,
        succeeded=succeeded,
        rows_written=rows_written,
        detail_code=detail_code,
    )
    logger.info(
        "Garmin wellness ingestion %s: %d/%d requests, %d rows",
        result.status,
        succeeded,
        attempted,
        rows_written,
    )
    return result
