"""Tests for Garmin endpoint aggregation and independent source watermarks."""

from __future__ import annotations

from datetime import date, timedelta

from ingest import garmin


def test_garmin_endpoint_failures_produce_a_degraded_result(monkeypatch) -> None:
    """One failed request is observable without discarding successful endpoints."""
    monkeypatch.setattr(garmin, "_ingest_daily_wellness", lambda *args: 1)
    monkeypatch.setattr(garmin, "_ingest_hrv", lambda *args: None)
    monkeypatch.setattr(garmin, "_ingest_heart_rate", lambda *args: 4)
    monkeypatch.setattr(garmin, "_ingest_stress", lambda *args: 3)
    monkeypatch.setattr(garmin, "_ingest_training_readiness", lambda *args: 1)
    today = date.today()

    result = garmin.ingest(
        object(),
        since={
            "wellness": today,
            "hrv": today,
            "heart_rate": today,
            "stress": today,
            "readiness": today,
        },
        client=object(),
    )

    assert result.source == "garmin_wellness"
    assert result.status == "degraded"
    assert result.attempted == 5
    assert result.succeeded == 4
    assert result.rows_written == 9


def test_each_endpoint_uses_its_own_restart_date(monkeypatch) -> None:
    """A missing HRV day is retried even when wellness is already current."""
    called: dict[str, list[date]] = {
        "wellness": [],
        "hrv": [],
        "heart_rate": [],
        "stress": [],
        "readiness": [],
    }
    monkeypatch.setattr(
        garmin,
        "_ingest_daily_wellness",
        lambda _client, _db, day: called["wellness"].append(day) or 0,
    )
    monkeypatch.setattr(
        garmin,
        "_ingest_hrv",
        lambda _client, _db, day: called["hrv"].append(day) or 0,
    )
    monkeypatch.setattr(
        garmin,
        "_ingest_heart_rate",
        lambda _client, _db, day: called["heart_rate"].append(day) or 0,
    )
    monkeypatch.setattr(
        garmin,
        "_ingest_stress",
        lambda _client, _db, day: called["stress"].append(day) or 0,
    )
    monkeypatch.setattr(
        garmin,
        "_ingest_training_readiness",
        lambda _client, _db, day: called["readiness"].append(day) or 0,
    )
    today = date.today()
    earlier = today - timedelta(days=1)

    garmin.ingest(
        object(),
        since={
            "wellness": today,
            "hrv": earlier,
            "heart_rate": today,
            "stress": today,
            "readiness": today,
        },
        client=object(),
    )

    assert called["wellness"] == [today]
    assert called["hrv"][0] == earlier
    assert called["hrv"][-1] == today
