"""Put the persisted plan's runs on the Garmin calendar as structured workouts.

Reads ``planned_sessions`` from Supabase (persisting is the approval gate, so
only reviewed weeks reach the watch), builds one Garmin workout per session that
has running in it (:mod:`plan.garmin_workout`), uploads it and schedules it on
its date.

The sync is idempotent and conservative:

- A workout this tool created is named ``LOD MM-DD <title>`` and carries a hash
  of its content. Workouts without the prefix are never read for changes,
  rescheduled or deleted.
- An unchanged workout is skipped. A revised one is reported as stale and only
  replaced (deleted, then re-uploaded) with ``--replace``. The same goes for a
  synced workout whose session no longer exists in the plan.
- Nothing is sent without ``--apply``; the default prints the plan of actions.

Run with ``python -m plan.garmin_sync [--start YYYY-MM-DD] [--days N] [--apply] [--replace]``.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv

from plan.export import _to_session
from plan.garmin_workout import (
    UnstructuredSessionError,
    WORKOUT_PREFIX,
    build_workout,
    content_hash_of,
    has_run_steps,
    is_synced_workout,
    read_content_hash,
    session_workout_name,
)
from plan.models import PlannedSession

_PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)

logger = logging.getLogger(__name__)

DEFAULT_DAYS = 14
_WORKOUT_PAGE_SIZE = 100

ActionKind = Literal[
    "upload", "schedule", "unchanged", "stale", "replace", "orphan", "delete_orphan", "unstructured"
]


@dataclass(frozen=True)
class SyncOptions:
    """What window to sync and how far the sync may go.

    Parameters
    ----------
    start : datetime.date
        First day of the window.
    days : int
        Window length in days, including ``start``.
    apply : bool
        Send changes to Garmin. ``False`` only reports them.
    replace : bool
        Allow deleting stale or orphaned synced workouts so they can be replaced.
    """

    start: date
    days: int = DEFAULT_DAYS
    apply: bool = False
    replace: bool = False

    @property
    def end(self) -> date:
        """Last day of the window, inclusive."""
        return self.start + timedelta(days=self.days - 1)


@dataclass(frozen=True)
class PlannedRun:
    """A persisted session with running in it, and the day it is planned."""

    session_date: date
    session: PlannedSession


@dataclass(frozen=True)
class SyncedWorkout:
    """A workout in the Garmin library that this tool created."""

    workout_id: int
    name: str
    content_hash: str | None


@dataclass(frozen=True)
class SyncAction:
    """One decision of the sync, executed only with ``--apply``."""

    kind: ActionKind
    name: str
    detail: str
    session_date: date | None = None
    payload: dict[str, Any] | None = field(default=None, compare=False)
    workout_id: int | None = None


def fetch_planned_runs(supabase: Any, start: date, end: date) -> list[PlannedRun]:
    """Read the persisted sessions in a window that contain running.

    Parameters
    ----------
    supabase : supabase.Client
        Authenticated Supabase client.
    start, end : datetime.date
        Window bounds, both inclusive.

    Returns
    -------
    list of PlannedRun
        Sessions in date order.
    """
    result = (
        supabase.table("planned_sessions")
        .select("*")
        .gte("session_date", start.isoformat())
        .lte("session_date", end.isoformat())
        .order("session_date")
        .execute()
    )
    runs = []
    for row in result.data or []:
        session = _to_session(row)
        if has_run_steps(session):
            runs.append(PlannedRun(date.fromisoformat(str(row["session_date"])), session))
    return runs


def fetch_synced_workouts(client: Any) -> list[SyncedWorkout]:
    """List the workouts in the Garmin library that carry the sync prefix.

    Parameters
    ----------
    client : garminconnect.Garmin
        Authenticated Garmin client.

    Returns
    -------
    list of SyncedWorkout
        Synced workouts with the content hash read from their description.
    """
    synced: list[SyncedWorkout] = []
    offset = 0
    while True:
        page = client.get_workouts(offset, _WORKOUT_PAGE_SIZE) or []
        for workout in page:
            name = workout.get("workoutName")
            if is_synced_workout(name):
                synced.append(
                    SyncedWorkout(
                        workout_id=int(workout["workoutId"]),
                        name=name,
                        content_hash=read_content_hash(workout.get("description")),
                    )
                )
        if len(page) < _WORKOUT_PAGE_SIZE:
            return synced
        offset += _WORKOUT_PAGE_SIZE


def fetch_scheduled(client: Any, start: date, end: date) -> set[tuple[int, date]]:
    """Return the (workout id, date) pairs already on the Garmin calendar.

    Parameters
    ----------
    client : garminconnect.Garmin
        Authenticated Garmin client.
    start, end : datetime.date
        Window bounds, both inclusive.

    Returns
    -------
    set of tuple
        One ``(workout_id, date)`` per scheduled workout in the window.
    """
    days = (start + timedelta(days=i) for i in range((end - start).days + 1))
    months = sorted({(d.year, d.month) for d in days})
    scheduled: set[tuple[int, date]] = set()
    for year, month in months:
        calendar = client.get_scheduled_workouts(year, month) or {}
        for item in calendar.get("calendarItems") or []:
            if item.get("itemType") != "workout" or item.get("workoutId") is None:
                continue
            item_date = date.fromisoformat(str(item["date"]))
            if start <= item_date <= end:
                scheduled.add((int(item["workoutId"]), item_date))
    return scheduled


def plan_actions(
    runs: list[PlannedRun],
    synced: list[SyncedWorkout],
    scheduled: set[tuple[int, date]],
    options: SyncOptions,
) -> list[SyncAction]:
    """Decide what the sync should do, without touching Garmin.

    Parameters
    ----------
    runs : list of PlannedRun
        Planned sessions with running in the window.
    synced : list of SyncedWorkout
        Workouts already created by this tool.
    scheduled : set of tuple
        ``(workout_id, date)`` pairs already on the calendar.
    options : SyncOptions
        Window and permissions.

    Returns
    -------
    list of SyncAction
        One action per planned run, plus one per orphaned synced workout.
    """
    by_name = {w.name: w for w in synced}
    actions: list[SyncAction] = []
    wanted_names: set[str] = set()

    for run in runs:
        if not options.start <= run.session_date <= options.end:
            continue
        name = session_workout_name(run.session, run.session_date)
        wanted_names.add(name)
        try:
            payload = build_workout(run.session, run.session_date)
        except UnstructuredSessionError as error:
            actions.append(SyncAction("unstructured", name, str(error), run.session_date))
            continue

        existing = by_name.get(name)
        if existing is None:
            actions.append(SyncAction("upload", name, "new", run.session_date, payload))
        elif existing.content_hash == content_hash_of(payload):
            if (existing.workout_id, run.session_date) in scheduled:
                actions.append(SyncAction("unchanged", name, "already on the calendar",
                                          run.session_date, workout_id=existing.workout_id))
            else:
                actions.append(SyncAction("schedule", name, "uploaded but not on the calendar",
                                          run.session_date, workout_id=existing.workout_id))
        elif options.replace:
            actions.append(SyncAction("replace", name, "plan changed; delete and re-upload",
                                      run.session_date, payload, existing.workout_id))
        else:
            actions.append(SyncAction("stale", name, "plan changed; rerun with --replace",
                                      run.session_date, payload, existing.workout_id))

    window_days = {
        f"{options.start + timedelta(days=i):%m-%d}" for i in range(options.days)
    }
    for workout in synced:
        if workout.name in wanted_names or _name_day(workout.name) not in window_days:
            continue
        kind: ActionKind = "delete_orphan" if options.replace else "orphan"
        actions.append(SyncAction(kind, workout.name, "no matching session in the plan",
                                  workout_id=workout.workout_id))
    return actions


def apply_actions(client: Any, actions: list[SyncAction]) -> None:
    """Send the decided actions to Garmin.

    Parameters
    ----------
    client : garminconnect.Garmin
        Authenticated Garmin client.
    actions : list of SyncAction
        Actions from :func:`plan_actions`. Report-only kinds are ignored.
    """
    for action in actions:
        if action.kind in ("replace", "delete_orphan"):
            client.delete_workout(action.workout_id)
            logger.info("Deleted %s (%s)", action.name, action.workout_id)
        if action.kind in ("upload", "replace"):
            uploaded = client.upload_workout(action.payload)
            workout_id = int(uploaded["workoutId"])
            client.schedule_workout(workout_id, action.session_date.isoformat())
            logger.info("Uploaded and scheduled %s on %s", action.name, action.session_date)
        elif action.kind == "schedule":
            client.schedule_workout(action.workout_id, action.session_date.isoformat())
            logger.info("Scheduled %s on %s", action.name, action.session_date)


def describe_steps(payload: dict[str, Any]) -> list[str]:
    """Render a payload's steps as short lines for the dry-run report.

    Parameters
    ----------
    payload : dict
        A payload from :func:`plan.garmin_workout.build_workout`.

    Returns
    -------
    list of str
        One line per step; repeat groups list their children indented.

    Examples
    --------
    >>> describe_steps(payload)  # doctest: +SKIP
    ['warmup    15:00     HR 100-145', '4x repeat', '  interval  8:00  pace 4:08-4:12/km', ...]
    """
    lines: list[str] = []
    for step in payload["workoutSegments"][0]["workoutSteps"]:
        if step["type"] == "RepeatGroupDTO":
            lines.append(f"{step['numberOfIterations']}x repeat")
            lines.extend(f"  {_describe_step(child)}" for child in step["workoutSteps"])
        else:
            lines.append(_describe_step(step))
    return lines


def format_report(actions: list[SyncAction], options: SyncOptions) -> str:
    """Summarise the actions for the terminal.

    Parameters
    ----------
    actions : list of SyncAction
        Actions from :func:`plan_actions`.
    options : SyncOptions
        Window and permissions, shown in the header.

    Returns
    -------
    str
        The report text.
    """
    mode = "APPLY" if options.apply else "DRY RUN (nothing sent; add --apply)"
    lines = [f"Garmin sync {options.start}..{options.end} - {mode}", ""]
    for action in actions:
        lines.append(f"[{action.kind}] {action.name} - {action.detail}")
        if action.payload is not None and action.kind in ("upload", "replace", "stale"):
            lines.extend(f"      {line}" for line in describe_steps(action.payload))
    if not actions:
        lines.append("No sessions with running in this window.")
    return "\n".join(lines)


def sync(options: SyncOptions, supabase: Any = None, client: Any = None) -> list[SyncAction]:
    """Read the plan and Garmin, decide the actions, and apply them if allowed.

    Parameters
    ----------
    options : SyncOptions
        Window and permissions.
    supabase : supabase.Client, optional
        Injected for tests; built from the environment when omitted.
    client : garminconnect.Garmin, optional
        Injected for tests; authenticated from the environment when omitted.

    Returns
    -------
    list of SyncAction
        The decided actions.
    """
    if supabase is None:
        from dashboard import query

        supabase = query.get_supabase_client()
    if client is None:
        from ingest.garmin import get_client

        client = get_client()

    runs = fetch_planned_runs(supabase, options.start, options.end)
    actions = plan_actions(
        runs,
        fetch_synced_workouts(client),
        fetch_scheduled(client, options.start, options.end),
        options,
    )
    if options.apply:
        apply_actions(client, actions)
    return actions


def _describe_step(step: dict[str, Any]) -> str:
    """One report line for an executable step."""
    kind = step["stepType"]["stepTypeKey"]
    condition = step["endCondition"]["conditionTypeKey"]
    value = step.get("endConditionValue")
    if condition == "time":
        dose = f"{int(value) // 60}:{int(value) % 60:02d}"
    elif condition == "distance":
        dose = f"{value / 1000:g} km"
    else:
        dose = "lap button"

    target_key = step["targetType"]["workoutTargetTypeKey"]
    if target_key == "pace.zone":
        target = f"pace {_pace(step['targetValueOne'])}-{_pace(step['targetValueTwo'])}/km"
    elif target_key == "heart.rate.zone":
        target = f"HR {step['targetValueOne']:.0f}-{step['targetValueTwo']:.0f}"
    else:
        target = ""
    return f"{kind:<9} {dose:<10} {target:<22} {step['description']}".rstrip()


def _pace(metres_per_second: float) -> str:
    """Format a speed as min:ss per km."""
    seconds = round(1000 / metres_per_second)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _name_day(name: str) -> str:
    """The ``MM-DD`` a synced workout name carries, e.g. ``10-20``."""
    return name[len(WORKOUT_PREFIX) + 1 : len(WORKOUT_PREFIX) + 6]


def main() -> None:
    """Parse the command line and run the sync."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Sync planned runs to the Garmin calendar.")
    parser.add_argument("--start", type=date.fromisoformat, default=date.today(),
                        help="First day to sync (default: today). Past dates are refused.")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS,
                        help=f"Window length in days (default: {DEFAULT_DAYS}).")
    parser.add_argument("--apply", action="store_true", help="Send changes to Garmin.")
    parser.add_argument("--replace", action="store_true",
                        help="Delete and re-upload synced workouts whose plan changed, and "
                        "delete synced workouts whose session is gone.")
    args = parser.parse_args()
    if args.start < date.today():
        parser.error("--start is in the past; the sync never writes past dates.")
    if args.days < 1:
        parser.error("--days must be at least 1.")

    options = SyncOptions(args.start, args.days, args.apply, args.replace)
    print(format_report(sync(options), options))


if __name__ == "__main__":
    main()
