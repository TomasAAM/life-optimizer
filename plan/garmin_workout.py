"""Turn a planned session into a Garmin Connect workout payload.

Pure mapping, no I/O: :mod:`plan.garmin_sync` handles Supabase and Garmin. The
payload is Garmin's own workout DTO, built as plain dicts rather than with the
typed models in ``garminconnect.workout``: the pinned 0.3.5 has no pace target,
and its ``ConditionType`` enum labels id 1 as distance, while Garmin uses 1 for
the lap button and 3 for distance. The ids here were checked against real
workouts from the athlete's library (``tests/fixtures/garmin_reference_workouts.json``).

Only the running part of a session reaches the watch. Strength and note steps are
dropped, and station or rest steps are kept only when they sit between run steps,
as in a compromised-running sim, so an AM gym finisher never lands in front of a
PM easy run.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any

from plan.models import PlannedSession, Step

WORKOUT_PREFIX = "LOD"

# Garmin needs a two-sided HR range. Easy steps only carry a ceiling, so the
# floor sits low enough that the watch alerts on the ceiling alone.
HR_FLOOR_BPM = 100

# Garmin silently truncates names past 256 characters. Description limits are
# not documented; this cap keeps well inside what other providers send.
_NAME_MAX_CHARS = 256
_STEP_DESCRIPTION_MAX_CHARS = 250
_DESCRIPTION_MAX_CHARS = 900

_HASH_MARKER = re.compile(r"\[lod:([0-9a-f]{12})\]")

_RUNNING = {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1}

_STEP_TYPES = {
    "warmup": {"stepTypeId": 1, "stepTypeKey": "warmup", "displayOrder": 1},
    "cooldown": {"stepTypeId": 2, "stepTypeKey": "cooldown", "displayOrder": 2},
    "interval": {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3},
    "recovery": {"stepTypeId": 4, "stepTypeKey": "recovery", "displayOrder": 4},
    "repeat": {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
    "other": {"stepTypeId": 7, "stepTypeKey": "other", "displayOrder": 7},
}

_LAP_BUTTON = {"conditionTypeId": 1, "conditionTypeKey": "lap.button", "displayOrder": 1, "displayable": True}
_TIME = {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True}
_DISTANCE = {"conditionTypeId": 3, "conditionTypeKey": "distance", "displayOrder": 3, "displayable": True}
_ITERATIONS = {"conditionTypeId": 7, "conditionTypeKey": "iterations", "displayOrder": 7, "displayable": False}

_NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
_HR_TARGET = {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 4}
_PACE_TARGET = {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone", "displayOrder": 6}

_WATCH_KINDS = {"run", "rest", "station"}


class UnstructuredSessionError(ValueError):
    """A run step has no machine-readable dose, so no faithful workout exists."""


def has_run_steps(session: PlannedSession) -> bool:
    """Tell whether a session has any running to put on the watch.

    Parameters
    ----------
    session : PlannedSession
        The planned session.

    Returns
    -------
    bool
        ``True`` when at least one step is a run.
    """
    return any(step.kind == "run" for step in session.steps)


def workout_name(session_date: date, title: str) -> str:
    """Build the Garmin workout name that marks a workout as synced by this tool.

    Parameters
    ----------
    session_date : datetime.date
        The day the session is planned.
    title : str
        The session title.

    Returns
    -------
    str
        For example ``"LOD 10-20 Threshold 5x8 min"``.

    Examples
    --------
    >>> workout_name(date(2026, 10, 20), "Threshold 5x8 min")
    'LOD 10-20 Threshold 5x8 min'
    """
    return f"{WORKOUT_PREFIX} {session_date:%m-%d} {title}"[:_NAME_MAX_CHARS]


def is_synced_workout(name: str | None) -> bool:
    """Tell whether a Garmin workout was created by this tool.

    Parameters
    ----------
    name : str or None
        The Garmin workout name.

    Returns
    -------
    bool
        ``True`` only for names carrying the sync prefix.
    """
    return bool(name) and name.startswith(f"{WORKOUT_PREFIX} ")


def read_content_hash(description: str | None) -> str | None:
    """Extract the content hash a synced workout carries in its description.

    Parameters
    ----------
    description : str or None
        The Garmin workout description.

    Returns
    -------
    str or None
        The 12-character hash, or ``None`` when the marker is absent.
    """
    match = _HASH_MARKER.search(description or "")
    return match.group(1) if match else None


def build_workout(session: PlannedSession, session_date: date) -> dict[str, Any]:
    """Map a planned session to a Garmin running-workout payload.

    Parameters
    ----------
    session : PlannedSession
        A session with at least one run step.
    session_date : datetime.date
        The day it is planned, used in the workout name.

    Returns
    -------
    dict
        A payload for ``Garmin.upload_workout``. Its description ends with a
        ``[lod:<hash>]`` marker of the step content, so a later sync can tell
        an unchanged workout from a revised one.

    Raises
    ------
    UnstructuredSessionError
        If the session has no run steps, or a run step has neither
        ``duration_s`` nor ``distance_m``.

    Examples
    --------
    >>> payload = build_workout(session, date(2026, 10, 20))  # doctest: +SKIP
    >>> payload["workoutName"]  # doctest: +SKIP
    'LOD 10-20 Threshold 5x8 min'
    """
    steps = _watch_steps(session)
    missing = [s.metric for s in steps if s.kind == "run" and s.duration_s is None and s.distance_m is None]
    if missing:
        raise UnstructuredSessionError(
            f"Run steps without duration_s or distance_m: {', '.join(missing)}"
        )

    flat: list[dict[str, Any]] = []
    for step in steps:
        flat.extend(_to_garmin_steps(step))
    garmin_steps = _number(_fold_repeats(flat))

    content_hash = _hash(garmin_steps)
    prescription = session.prescription[:_DESCRIPTION_MAX_CHARS]
    payload: dict[str, Any] = {
        "workoutName": workout_name(session_date, session.title),
        "description": f"{prescription}\n\n[lod:{content_hash}]",
        "sportType": _RUNNING,
        "workoutSegments": [
            {"segmentOrder": 1, "sportType": _RUNNING, "workoutSteps": garmin_steps}
        ],
    }
    if session.duration_min:
        payload["estimatedDurationInSecs"] = session.duration_min * 60
    return payload


def content_hash_of(payload: dict[str, Any]) -> str:
    """Return the content hash embedded in a payload from :func:`build_workout`.

    Parameters
    ----------
    payload : dict
        A payload built by :func:`build_workout`.

    Returns
    -------
    str
        The 12-character content hash.

    Raises
    ------
    ValueError
        If the payload carries no hash marker.
    """
    found = read_content_hash(payload.get("description"))
    if found is None:
        raise ValueError("Payload has no [lod:<hash>] marker.")
    return found


def _watch_steps(session: PlannedSession) -> list[Step]:
    """Keep the steps that belong on the watch, in order.

    The span runs from the first run step to the last, so stations and rests
    before or after the running (a gym finisher, a strength block) fall away,
    while those between runs (a sim's stations, jog recoveries) stay.
    """
    run_positions = [i for i, step in enumerate(session.steps) if step.kind == "run"]
    if not run_positions:
        raise UnstructuredSessionError(f"'{session.title}' has no run steps.")
    span = session.steps[run_positions[0] : run_positions[-1] + 1]
    return [step for step in span if step.kind in _WATCH_KINDS]


def _to_garmin_steps(step: Step) -> list[dict[str, Any]]:
    """Map one plan step to one Garmin step, or to a repeat group for ``repeats``."""
    description = f"{step.metric}: {step.target}" if step.target else step.metric
    executable = {
        "type": "ExecutableStepDTO",
        "stepType": _STEP_TYPES[_step_type_key(step)],
        "description": description[:_STEP_DESCRIPTION_MAX_CHARS],
        **_end_condition(step),
        **_target(step),
    }
    if step.repeats is None:
        return [executable]

    executable["stepType"] = _STEP_TYPES["interval"]
    walk_back = {
        "type": "ExecutableStepDTO",
        "stepType": _STEP_TYPES["recovery"],
        "description": "Walk back, press lap when ready",
        "endCondition": _LAP_BUTTON,
        "endConditionValue": None,
        "targetType": _NO_TARGET,
    }
    return [_repeat_group(step.repeats, [executable, walk_back])]


def _step_type_key(step: Step) -> str:
    """Pick the Garmin step type for a plan step."""
    if step.kind == "station":
        return "other"
    if step.kind == "rest":
        return "recovery"
    if step.phase in ("warmup", "cooldown"):
        return step.phase
    return "interval"


def _end_condition(step: Step) -> dict[str, Any]:
    """Time, distance, or the lap button when the plan gives no dose."""
    if step.duration_s is not None:
        return {"endCondition": _TIME, "endConditionValue": float(step.duration_s)}
    if step.distance_m is not None:
        return {"endCondition": _DISTANCE, "endConditionValue": float(step.distance_m)}
    return {"endCondition": _LAP_BUTTON, "endConditionValue": None}


def _target(step: Step) -> dict[str, Any]:
    """Resolve which target the watch alerts on, then encode it.

    Pace goes in metres per second with the fast end first, matching how Garmin
    stores pace ranges from other providers.
    """
    choice = step.watch_target
    if choice is None:
        if step.pace_fast_s_per_km is not None:
            choice = "pace"
        elif step.hr_max is not None:
            choice = "hr"
        else:
            choice = "none"

    if choice == "pace":
        return {
            "targetType": _PACE_TARGET,
            "targetValueOne": round(1000 / step.pace_fast_s_per_km, 7),
            "targetValueTwo": round(1000 / step.pace_slow_s_per_km, 7),
        }
    if choice == "hr":
        return {
            "targetType": _HR_TARGET,
            "targetValueOne": float(step.hr_min if step.hr_min is not None else HR_FLOOR_BPM),
            "targetValueTwo": float(step.hr_max),
        }
    return {"targetType": _NO_TARGET}


def _repeat_group(iterations: int, children: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap steps in a Garmin repeat group."""
    return {
        "type": "RepeatGroupDTO",
        "stepType": _STEP_TYPES["repeat"],
        "numberOfIterations": iterations,
        "endCondition": _ITERATIONS,
        "endConditionValue": float(iterations),
        "smartRepeat": False,
        "workoutSteps": children,
    }


def _signature(step: dict[str, Any]) -> str:
    """Structural identity of a step, used to spot repeated work/recovery pairs.

    Descriptions are ignored so a final rep with an extra cue still folds with the
    others, except on station steps, where the description is the station itself.
    """
    keep = {k: v for k, v in step.items() if k != "description"}
    if step["stepType"]["stepTypeKey"] == "other":
        keep["description"] = step["description"]
    return json.dumps(keep, sort_keys=True)


def _fold_repeats(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold consecutive identical (work, recovery) pairs into repeat groups.

    ``R r R r R r R r R`` becomes ``4 x [R r]`` followed by the final ``R`` as its
    own step, which keeps the session exact without relying on Garmin's
    skip-last-recovery flag.
    """
    folded: list[dict[str, Any]] = []
    i = 0
    while i < len(steps):
        is_pair = (
            i + 1 < len(steps)
            and steps[i]["type"] == "ExecutableStepDTO"
            and steps[i + 1]["type"] == "ExecutableStepDTO"
            and steps[i + 1]["stepType"]["stepTypeKey"] == "recovery"
        )
        if is_pair:
            pair = (_signature(steps[i]), _signature(steps[i + 1]))
            count = 1
            while (
                i + 2 * count + 1 < len(steps)
                and (_signature(steps[i + 2 * count]), _signature(steps[i + 2 * count + 1])) == pair
            ):
                count += 1
            if count >= 2:
                folded.append(_repeat_group(count, [steps[i], steps[i + 1]]))
                i += 2 * count
                continue
        folded.append(steps[i])
        i += 1
    return folded


def _number(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign Garmin's depth-first ``stepOrder`` and per-group ``childStepId``."""
    order = 0
    group_id = 0
    numbered: list[dict[str, Any]] = []
    for step in steps:
        order += 1
        if step["type"] != "RepeatGroupDTO":
            numbered.append({**step, "stepOrder": order})
            continue
        group_id += 1
        group_order = order
        children = []
        for child in step["workoutSteps"]:
            order += 1
            children.append({**child, "stepOrder": order, "childStepId": group_id})
        numbered.append(
            {**step, "stepOrder": group_order, "childStepId": group_id, "workoutSteps": children}
        )
    return numbered


def _hash(steps: list[dict[str, Any]]) -> str:
    """Hash the steps only, so editing the session's prose prescription never forces a re-sync."""
    return hashlib.sha256(json.dumps(steps, sort_keys=True).encode("utf-8")).hexdigest()[:12]
