"""Tests for deciding and applying the plan-to-Garmin sync."""

from datetime import date
from typing import Any

from plan.garmin_sync import (
    PlannedRun,
    SyncOptions,
    SyncedWorkout,
    apply_actions,
    describe_steps,
    fetch_planned_runs,
    fetch_scheduled,
    fetch_synced_workouts,
    format_report,
    plan_actions,
    sync,
)
from plan.garmin_workout import build_workout, content_hash_of
from plan.models import PlannedSession

_START = date(2026, 10, 19)
_TUESDAY = date(2026, 10, 20)


def _session(title: str = "Threshold 5x8 min", warmup_s: int = 900, **overrides: Any) -> PlannedSession:
    """Build a small threshold session.

    Parameters
    ----------
    title : str
        Session title.
    warmup_s : int
        Warm-up length, varied to change the content hash.
    **overrides
        Session fields to replace.

    Returns
    -------
    PlannedSession
        The validated session.
    """
    payload = {
        "day": "Tuesday",
        "session_type": "run",
        "title": title,
        "zone": "Threshold",
        "intensity": "hard",
        "duration_min": 60,
        "distance_m": 12000,
        "prescription": "Threshold.",
        "steps": [
            {"phase": "warmup", "kind": "run", "metric": "15 min easy", "duration_s": warmup_s, "hr_max": 145},
            {"phase": "main", "kind": "run", "metric": "8 min threshold", "duration_s": 480,
             "pace_fast_s_per_km": 248, "pace_slow_s_per_km": 252},
        ],
        "purpose": "Raise LT2.",
        "why": "Fixed pace.",
        "hyrox_focus": None,
    }
    payload.update(overrides)
    return PlannedSession.model_validate(payload)


def _synced_copy(session: PlannedSession, session_date: date, workout_id: int = 900) -> SyncedWorkout:
    """Return the Garmin-side record of a session uploaded earlier."""
    payload = build_workout(session, session_date)
    return SyncedWorkout(workout_id, payload["workoutName"], content_hash_of(payload))


class FakeGarmin:
    """In-memory stand-in for ``garminconnect.Garmin``, recording every write."""

    def __init__(self, workouts: list[dict[str, Any]] | None = None,
                 calendar: list[dict[str, Any]] | None = None) -> None:
        self.workouts = workouts or []
        self.calendar = calendar or []
        self.calls: list[tuple] = []

    def get_workouts(self, start: int, limit: int) -> list[dict[str, Any]]:
        return self.workouts[start : start + limit]

    def get_scheduled_workouts(self, year: int, month: int) -> dict[str, Any]:
        items = [i for i in self.calendar if i["date"].startswith(f"{year}-{month:02d}")]
        return {"calendarItems": items}

    def upload_workout(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("upload", payload["workoutName"]))
        return {"workoutId": 1000 + len(self.calls)}

    def schedule_workout(self, workout_id: int, date_str: str) -> dict[str, Any]:
        self.calls.append(("schedule", workout_id, date_str))
        return {}

    def delete_workout(self, workout_id: int) -> None:
        self.calls.append(("delete", workout_id))


class FakeQuery:
    """Chainable stand-in for a Supabase table query."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.filters: list[tuple[str, str, str]] = []

    def select(self, _columns: str) -> "FakeQuery":
        return self

    def gte(self, column: str, value: str) -> "FakeQuery":
        self.filters.append(("gte", column, value))
        return self

    def lte(self, column: str, value: str) -> "FakeQuery":
        self.filters.append(("lte", column, value))
        return self

    def order(self, _column: str) -> "FakeQuery":
        return self

    def execute(self) -> Any:
        return type("Result", (), {"data": self.rows})()


class FakeSupabase:
    """Minimal Supabase client returning fixed ``planned_sessions`` rows."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.query = FakeQuery(rows)

    def table(self, _name: str) -> FakeQuery:
        return self.query


def _row(session: PlannedSession, session_date: date) -> dict[str, Any]:
    """Shape a session like a ``planned_sessions`` row."""
    return {
        "session_date": session_date.isoformat(),
        "session_type": session.session_type,
        "title": session.title,
        "zone": session.zone,
        "intensity": session.intensity,
        "prescription": {
            "detail": session.prescription,
            "duration_min": session.duration_min,
            "distance_m": session.distance_m,
            "steps": [s.model_dump() for s in session.steps],
            "why": session.why,
        },
        "purpose": session.purpose,
        "hyrox_focus": session.hyrox_focus,
    }


def test_new_session_is_uploaded() -> None:
    """A planned run with no synced copy gets uploaded."""
    actions = plan_actions([PlannedRun(_TUESDAY, _session())], [], set(), SyncOptions(_START))

    assert [(a.kind, a.name) for a in actions] == [("upload", "LOD 10-20 Threshold 5x8 min")]


def test_unchanged_scheduled_workout_is_left_alone() -> None:
    """Re-running the sync after a successful one changes nothing."""
    synced = _synced_copy(_session(), _TUESDAY)

    actions = plan_actions([PlannedRun(_TUESDAY, _session())], [synced], {(900, _TUESDAY)},
                           SyncOptions(_START))

    assert [a.kind for a in actions] == ["unchanged"]


def test_uploaded_but_unscheduled_workout_is_scheduled() -> None:
    """A run whose scheduling failed last time gets scheduled, not re-uploaded."""
    synced = _synced_copy(_session(), _TUESDAY)

    actions = plan_actions([PlannedRun(_TUESDAY, _session())], [synced], set(), SyncOptions(_START))

    assert [(a.kind, a.workout_id) for a in actions] == [("schedule", 900)]


def test_changed_plan_is_reported_until_replace_is_allowed() -> None:
    """A revised session is never deleted without --replace."""
    synced = _synced_copy(_session(warmup_s=900), _TUESDAY)
    runs = [PlannedRun(_TUESDAY, _session(warmup_s=1200))]

    report_only = plan_actions(runs, [synced], {(900, _TUESDAY)}, SyncOptions(_START))
    replacing = plan_actions(runs, [synced], {(900, _TUESDAY)}, SyncOptions(_START, replace=True))

    assert [a.kind for a in report_only] == ["stale"]
    assert [(a.kind, a.workout_id) for a in replacing] == [("replace", 900)]


def test_synced_workout_whose_session_is_gone_is_an_orphan() -> None:
    """A moved or renamed session leaves its old synced workout as an orphan."""
    moved = _synced_copy(_session(title="Compromised Sim"), date(2026, 10, 23), workout_id=901)

    actions = plan_actions([], [moved], set(), SyncOptions(_START))
    deleting = plan_actions([], [moved], set(), SyncOptions(_START, replace=True))

    assert [(a.kind, a.workout_id) for a in actions] == [("orphan", 901)]
    assert [a.kind for a in deleting] == ["delete_orphan"]


def test_renamed_double_day_uploads_new_and_orphans_old() -> None:
    """A double day synced under its gym-led title is replaced by its run-only name."""
    double = _session(title="Upper Strength (AM) + Easy Run (PM)", session_type="strength", steps=[
        {"kind": "strength", "metric": "OHP 3x5", "load": "62.5 kg"},
        {"kind": "run", "metric": "8 km easy (PM)", "distance_m": 8000, "hr_max": 145},
    ])
    payload = build_workout(double, date(2026, 10, 19))
    old = SyncedWorkout(903, "LOD 10-19 Upper Strength (AM) + Easy Run (PM)", content_hash_of(payload))

    actions = plan_actions([PlannedRun(date(2026, 10, 19), double)], [old], {(903, date(2026, 10, 19))},
                           SyncOptions(_START, replace=True))

    assert [(a.kind, a.name) for a in actions] == [
        ("upload", "LOD 10-19 Run: 8 km easy (PM)"),
        ("delete_orphan", "LOD 10-19 Upper Strength (AM) + Easy Run (PM)"),
    ]


def test_synced_workouts_outside_the_window_are_ignored() -> None:
    """Earlier synced workouts are history, not orphans."""
    old = _synced_copy(_session(), date(2026, 10, 6), workout_id=902)

    assert plan_actions([], [old], set(), SyncOptions(_START)) == []


def test_runs_before_the_window_are_never_synced() -> None:
    """A past session is skipped even if the caller passes it in."""
    actions = plan_actions([PlannedRun(date(2026, 10, 18), _session())], [], set(), SyncOptions(_START))

    assert actions == []


def test_unstructured_session_is_reported_not_uploaded() -> None:
    """A run step with no dose is flagged so the plan gets fixed, not guessed."""
    session = _session(steps=[{"kind": "run", "metric": "Easy jog to 9 km total"}])

    actions = plan_actions([PlannedRun(_TUESDAY, session)], [], set(), SyncOptions(_START))

    assert actions[0].kind == "unstructured"
    assert "Easy jog to 9 km total" in actions[0].detail


def test_apply_uploads_schedules_and_replaces() -> None:
    """Upload schedules the new id; replace deletes before re-uploading."""
    client = FakeGarmin()
    stale = _synced_copy(_session(warmup_s=900), _TUESDAY)
    runs = [PlannedRun(_TUESDAY, _session(warmup_s=1200)),
            PlannedRun(date(2026, 10, 21), _session(title="Easy Aerobic"))]

    apply_actions(client, plan_actions(runs, [stale], set(), SyncOptions(_START, replace=True)))

    assert client.calls == [
        ("delete", 900),
        ("upload", "LOD 10-20 Threshold 5x8 min"),
        ("schedule", 1002, "2026-10-20"),
        ("upload", "LOD 10-21 Easy Aerobic"),
        ("schedule", 1004, "2026-10-21"),
    ]


def test_apply_never_touches_report_only_actions() -> None:
    """Stale, orphan, unchanged and unstructured actions send nothing."""
    client = FakeGarmin()
    stale = _synced_copy(_session(warmup_s=900), _TUESDAY)
    orphan = _synced_copy(_session(title="Old"), date(2026, 10, 22), workout_id=901)
    actions = plan_actions([PlannedRun(_TUESDAY, _session(warmup_s=1200))], [stale, orphan], set(),
                           SyncOptions(_START))

    apply_actions(client, actions)

    assert {a.kind for a in actions} == {"stale", "orphan"}
    assert client.calls == []


def test_only_prefixed_workouts_are_read_as_synced() -> None:
    """The athlete's own and third-party workouts are invisible to the sync."""
    client = FakeGarmin(workouts=[
        {"workoutId": 1, "workoutName": "W11 Wed Intervals", "description": "Runna"},
        {"workoutId": 2, "workoutName": "LOD 10-20 Threshold 5x8 min", "description": "x\n\n[lod:0123456789ab]"},
        {"workoutId": 3, "workoutName": "Easy Run", "description": None},
    ])

    assert fetch_synced_workouts(client) == [
        SyncedWorkout(2, "LOD 10-20 Threshold 5x8 min", "0123456789ab")
    ]


def test_scheduled_lookup_spans_month_boundaries() -> None:
    """A window crossing into November reads both months' calendars."""
    client = FakeGarmin(calendar=[
        {"itemType": "workout", "workoutId": 7, "date": "2026-10-30"},
        {"itemType": "workout", "workoutId": 8, "date": "2026-11-02"},
        {"itemType": "activity", "workoutId": None, "date": "2026-11-01"},
        {"itemType": "workout", "workoutId": 9, "date": "2026-11-20"},
    ])

    found = fetch_scheduled(client, date(2026, 10, 26), date(2026, 11, 8))

    assert found == {(7, date(2026, 10, 30)), (8, date(2026, 11, 2))}


def test_planned_runs_skip_sessions_without_running() -> None:
    """Pure gym days are read from Supabase but never become watch workouts."""
    gym = _session(title="Upper Strength", session_type="strength",
                   steps=[{"kind": "strength", "metric": "OHP 3x5", "load": "62.5 kg"}])
    supabase = FakeSupabase([_row(_session(), _TUESDAY), _row(gym, date(2026, 10, 21))])

    runs = fetch_planned_runs(supabase, _START, date(2026, 11, 1))

    assert [(r.session_date, r.session.title) for r in runs] == [(_TUESDAY, "Threshold 5x8 min")]
    assert ("gte", "session_date", "2026-10-19") in supabase.query.filters


def test_dry_run_sync_sends_nothing_and_reports_steps() -> None:
    """Without --apply the sync only reads, and the report shows the steps."""
    client = FakeGarmin()
    options = SyncOptions(_START)

    actions = sync(options, supabase=FakeSupabase([_row(_session(), _TUESDAY)]), client=client)
    report = format_report(actions, options)

    assert client.calls == []
    assert "DRY RUN" in report
    assert "[upload] LOD 10-20 Threshold 5x8 min" in report
    assert "pace 4:08-4:12/km" in report


def test_describe_steps_reads_like_the_watch() -> None:
    """The dry-run lines show dose and target for each step."""
    lines = describe_steps(build_workout(_session(), _TUESDAY))

    assert lines[0].startswith("warmup    15:00      HR 100-145")
    assert lines[1].startswith("interval  8:00       pace 4:08-4:12/km")
