"""Tests for typed ingestion outcomes and persistent source freshness."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from ingest.status import SourceResult, record_source_result, source_is_stale


class _StatusTable:
    """Minimal fluent table capturing status writes and serving status reads."""

    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []
        self.written: dict | None = None
        self.source: str | None = None

    def select(self, _columns: str) -> "_StatusTable":
        return self

    def eq(self, _column: str, source: str) -> "_StatusTable":
        self.source = source
        return self

    def limit(self, _count: int) -> "_StatusTable":
        return self

    def upsert(self, row: dict, on_conflict: str) -> "_StatusTable":
        assert on_conflict == "source"
        self.written = row
        return self

    def execute(self) -> SimpleNamespace:
        selected = [row for row in self.rows if row.get("source") == self.source]
        return SimpleNamespace(data=selected)


class _StatusClient:
    """Expose one status table through the Supabase client shape."""

    def __init__(self, rows: list[dict] | None = None) -> None:
        self.status = _StatusTable(rows)

    def table(self, name: str) -> _StatusTable:
        assert name == "ingestion_source_status"
        return self.status


def test_result_classifies_success_degradation_failure_and_skip() -> None:
    """Counts must produce the four statuses used by CI and the dashboard."""
    assert SourceResult.from_counts("a", 2, 2, 10).status == "success"
    assert SourceResult.from_counts("a", 2, 1, 5).status == "degraded"
    assert SourceResult.from_counts("a", 2, 0, 0).status == "failed"
    assert SourceResult.from_counts("a", 0, 0, 0).status == "skipped"


def test_result_rejects_impossible_counts() -> None:
    """A misleading source summary must fail before it reaches the status table."""
    with pytest.raises(ValueError, match="cannot be negative"):
        SourceResult.from_counts("a", -1, 0, 0)
    with pytest.raises(ValueError, match="cannot exceed"):
        SourceResult.from_counts("a", 1, 2, 0)


def test_success_records_last_success_at() -> None:
    """A valid provider response advances both attempt and success timestamps."""
    client = _StatusClient()
    stamp = datetime(2026, 9, 12, 9, tzinfo=timezone.utc)
    record_source_result(
        client,
        SourceResult.from_counts("garmin_activities", 1, 1, 3),
        attempted_at=stamp,
    )
    assert client.status.written is not None
    assert client.status.written["last_attempt_at"] == stamp.isoformat()
    assert client.status.written["last_success_at"] == stamp.isoformat()


def test_failure_does_not_overwrite_last_success_at() -> None:
    """Omitting last_success_at lets an upsert retain the previous good instant."""
    client = _StatusClient()
    record_source_result(
        client,
        SourceResult(
            source="garmin_activities",
            status="failed",
            attempted=1,
            detail_code="garmin_activity_fetch_failed",
        ),
    )
    assert client.status.written is not None
    assert "last_success_at" not in client.status.written
    assert client.status.written["detail_code"] == "garmin_activity_fetch_failed"


def test_freshness_uses_last_success_not_last_attempt() -> None:
    """Repeated failed attempts cannot make an old source appear current."""
    now = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)
    client = _StatusClient(
        [
            {
                "source": "garmin_activities",
                "last_success_at": "2026-09-10T00:00:00+00:00",
            }
        ]
    )
    assert source_is_stale(
        client, "garmin_activities", timedelta(hours=36), now=now
    )
    assert not source_is_stale(
        client, "garmin_activities", timedelta(hours=72), now=now
    )


def test_missing_source_is_stale() -> None:
    """Absence of a recorded success must fail the deployment freshness gate."""
    assert source_is_stale(
        _StatusClient(),
        "garmin_activities",
        timedelta(hours=36),
        now=datetime(2026, 9, 12, tzinfo=timezone.utc),
    )
