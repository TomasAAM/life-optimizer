"""Tests for ingestion orchestration, source isolation, and deployment gating."""

from __future__ import annotations

from datetime import date

from ingest import run
from ingest.garmin_activities import GarminActivitiesResult
from ingest.status import SourceResult


def _successful_result(source: str) -> SourceResult:
    """Build a successful one-request source result."""
    return SourceResult.from_counts(source, attempted=1, succeeded=1, rows_written=1)


def _wire_successful_pipeline(monkeypatch) -> list[SourceResult]:
    """Replace every external boundary with a deterministic successful result."""
    recorded: list[SourceResult] = []
    monkeypatch.setattr(run, "get_supabase_client", lambda: object())
    monkeypatch.setattr(
        run, "get_last_synced_date", lambda *args, **kwargs: date(2026, 9, 10)
    )
    monkeypatch.setattr(run.garmin, "get_client", lambda: object())
    monkeypatch.setattr(
        run.garmin,
        "ingest",
        lambda *args, **kwargs: _successful_result("garmin_wellness"),
    )
    monkeypatch.setattr(
        run.garmin_activities,
        "ingest",
        lambda *args, **kwargs: GarminActivitiesResult(
            summary=_successful_result("garmin_activities"),
            activities=(),
        ),
    )
    monkeypatch.setattr(
        run.exercise_sets,
        "ingest",
        lambda *args, **kwargs: SourceResult(
            source="garmin_exercise_sets", status="skipped"
        ),
    )
    monkeypatch.setattr(
        run.body_composition,
        "ingest",
        lambda *args, **kwargs: SourceResult(
            source="body_composition", status="skipped"
        ),
    )
    monkeypatch.setattr(
        run,
        "record_source_result",
        lambda _client, result, attempted_at=None: recorded.append(result),
    )
    monkeypatch.setattr(run, "source_is_stale", lambda *args, **kwargs: False)
    return recorded


def test_successful_critical_sources_allow_deployment(monkeypatch) -> None:
    """A current Garmin refresh exits zero even when the optional body feed is off."""
    recorded = _wire_successful_pipeline(monkeypatch)
    assert run.main() == 0
    assert {result.source for result in recorded} == {
        "garmin_auth",
        "garmin_wellness",
        "garmin_activities",
        "garmin_exercise_sets",
        "body_composition",
    }


def test_failed_activity_fetch_blocks_deployment(monkeypatch) -> None:
    """A green wellness refresh cannot hide a failed activity source."""
    _wire_successful_pipeline(monkeypatch)
    monkeypatch.setattr(
        run.garmin_activities,
        "ingest",
        lambda *args, **kwargs: GarminActivitiesResult(
            summary=SourceResult(
                source="garmin_activities",
                status="failed",
                attempted=1,
                detail_code="garmin_activity_fetch_failed",
            ),
            activities=(),
        ),
    )
    assert run.main() == 1


def test_stale_critical_source_blocks_deployment(monkeypatch) -> None:
    """A stale last-success timestamp blocks deployment even without an exception."""
    _wire_successful_pipeline(monkeypatch)
    monkeypatch.setattr(
        run,
        "source_is_stale",
        lambda _client, source, **kwargs: source == "garmin_activities",
    )
    assert run.main() == 1


def test_status_storage_failure_blocks_deployment(monkeypatch) -> None:
    """The workflow cannot claim observability when source status was not stored."""
    _wire_successful_pipeline(monkeypatch)

    def _fail_record(*args, **kwargs) -> None:
        raise RuntimeError("status table unavailable")

    monkeypatch.setattr(run, "record_source_result", _fail_record)
    assert run.main() == 1


def test_watermark_is_source_specific_and_overlapping() -> None:
    """The restart date rewinds one source without consulting another table."""

    class _Query:
        def select(self, column: str) -> "_Query":
            assert column == "start_time"
            return self

        def order(self, column: str, desc: bool) -> "_Query":
            assert column == "start_time"
            assert desc
            return self

        def limit(self, count: int) -> "_Query":
            assert count == 1
            return self

        def execute(self):
            return type(
                "Response", (), {"data": [{"start_time": "2026-09-12T07:00:00Z"}]}
            )()

    class _Client:
        def table(self, name: str) -> _Query:
            assert name == "garmin_activities"
            return _Query()

    assert run.get_last_synced_date(
        _Client(), "garmin_activities", "start_time", overlap_days=2
    ) == date(2026, 9, 10)
