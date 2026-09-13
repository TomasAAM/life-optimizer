"""Per-set detail for strength and HIIT sessions.

The per-exercise summary in :mod:`ingest.garmin_activities` rides along in the
activity payload and costs nothing. This module fetches the individual sets
behind it, which costs one ``get_activity_exercise_sets`` call per session, and
is worth the call for three things the summary flattens away:

* **Garmin's confidence.** The summary names an exercise; only the per-set
  payload says whether that name was settled or guessed. Across the history at
  the 2026-09-09 backfill, only 139 of 679 active sets carried a certain
  identification -- so without this column a load-progression chart would plot
  the watch's guesswork as training history.
* **The individual set.** ``5 x 3 @ 100 kg`` and ``3 x 5 @ 100 kg`` summarise
  identically. Progressive overload is read off the top set, not the total.
* **Rest.** Rest sets are half of every payload and are stored rather than
  filtered, because rest length is what separates a heavy triple from a metcon
  and cannot be recovered from a table that dropped it.

Only sessions Garmin says have exercises are fetched, so the call count tracks
the two strength sessions a week rather than the whole training log.
"""

from __future__ import annotations

import logging
from typing import Any

from garminconnect import Garmin
from supabase import Client

from ingest.garmin_activities import grams_to_kg, has_exercise_sets
from ingest.status import SourceResult

logger = logging.getLogger(__name__)

# Garmin's identification is settled at this probability: either the watch was
# certain, or the athlete named the movement in Garmin Connect. Anything lower
# arrived alongside two runner-up candidates and is the best of several
# guesses -- see :data:`dashboard.strength_metrics.CONFIRMED_PROBABILITY_PCT`,
# which is where the distinction is acted on.
_CERTAIN_PROBABILITY = 100.0


def _to_utc_iso(start: str | None) -> str | None:
    """Convert an exercise-set ``startTime`` to an ISO-8601 UTC timestamp.

    Garmin stamps these in GMT with no offset marker, the same as
    ``startTimeGMT`` on the activity itself -- verified against a session whose
    07:31 local start appears here as ``10:31``. PostgREST needs the offset
    spelled out or it stores a Santiago morning as a UTC morning.

    Parameters
    ----------
    start : str or None
        Raw ``startTime`` value, e.g. ``"2026-09-08T10:31:10.0"``.

    Returns
    -------
    str or None
        ISO-8601 string with an explicit ``+00:00`` offset, or ``None``.

    Examples
    --------
    >>> _to_utc_iso("2026-09-08T10:31:10.0")
    '2026-09-08T10:31:10.0+00:00'
    >>> _to_utc_iso(None) is None
    True
    """
    if not start:
        return None
    return start.replace(" ", "T") + "+00:00"


def _parse_set(activity_id: int, index: int, raw: dict[str, Any]) -> dict[str, Any]:
    """Map one raw exercise set to the ``garmin_exercise_sets`` schema.

    Keyed on position rather than on Garmin's ``messageIndex``: that field is
    populated on older sessions and ``None`` on every recent one, so keying on
    it would collapse a whole session's sets onto a single null-indexed row.

    Only the top candidate exercise is kept. When Garmin is unsure it returns
    three, but the runner-ups drive no reading of this data -- what matters is
    whether the top one is certain, which ``probability_pct`` already says.

    Parameters
    ----------
    activity_id : int
        The session the set belongs to.
    index : int
        Position of the set within the session, rests included.
    raw : dict
        One entry of the payload's ``exerciseSets`` list.

    Returns
    -------
    dict
        A row ready to insert into ``garmin_exercise_sets``.
    """
    candidates = raw.get("exercises") or []
    top = candidates[0] if candidates else {}
    return {
        "activity_id": activity_id,
        "set_index": index,
        "set_type": raw.get("setType"),
        "start_time": _to_utc_iso(raw.get("startTime")),
        "duration_s": raw.get("duration"),
        "reps": raw.get("repetitionCount"),
        "weight_kg": grams_to_kg(raw.get("weight")),
        # Rest sets carry no exercise at all, so these stay null rather than
        # inheriting the movement that happened to precede them.
        "category": top.get("category"),
        "exercise_name": top.get("name"),
        "probability_pct": top.get("probability"),
    }


def parse_sets(activity_id: int, payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Parse a whole ``get_activity_exercise_sets`` payload.

    Parameters
    ----------
    activity_id : int
        The session the payload belongs to.
    payload : dict or None
        The raw response, or ``None`` when the call returned nothing.

    Returns
    -------
    list of dict
        One row per set, in the order Garmin recorded them. Empty when the
        session has no sets.

    Examples
    --------
    >>> rows = parse_sets(1, {"exerciseSets": [
    ...     {"setType": "ACTIVE", "weight": 100000.0, "repetitionCount": 3,
    ...      "exercises": [{"category": "SQUAT", "name": None,
    ...                     "probability": 100.0}]}]})
    >>> rows[0]["weight_kg"], rows[0]["set_index"], rows[0]["category"]
    (100.0, 0, 'SQUAT')
    """
    raw_sets = (payload or {}).get("exerciseSets") or []
    return [_parse_set(activity_id, i, raw) for i, raw in enumerate(raw_sets)]


def _replace_sets(supabase: Client, activity_id: int, rows: list[dict]) -> None:
    """Rewrite one session's sets.

    Delete-then-insert rather than upsert, for the same reason as the
    per-exercise rows: a re-read is authoritative. If a session is edited in
    Garmin Connect and loses a set, an upsert would leave the trailing index
    behind as a set that was never performed.

    Parameters
    ----------
    supabase : Client
        Authenticated Supabase client.
    activity_id : int
        The session being rewritten.
    rows : list of dict
        Parsed ``garmin_exercise_sets`` rows for that session.
    """
    supabase.table("garmin_exercise_sets").delete().eq(
        "activity_id", activity_id
    ).execute()
    if rows:
        supabase.table("garmin_exercise_sets").insert(rows).execute()


def ingest(
    supabase: Client, garmin: Garmin, activities: list[dict[str, Any]]
) -> SourceResult:
    """Fetch and store the per-set detail of every set-bearing session.

    Takes the activity payloads already fetched by
    :func:`ingest.garmin_activities.ingest` rather than fetching the window a
    second time, so the only new API traffic is the one call per strength or
    HIIT session that the detail actually requires.

    Every session in the window is re-fetched on every run rather than skipped
    when already stored. That is what makes the feed self-healing: naming an
    exercise in Garmin Connect days after the session changes the answer, and a
    fetch-once-and-skip rule would keep serving the watch's original guess.

    Parameters
    ----------
    supabase : Client
        Authenticated Supabase client.
    garmin : Garmin
        Authenticated Garmin client.
    activities : list of dict
        Raw activity payloads for the sync window.

    Returns
    -------
    SourceResult
        Status across the set-bearing sessions attempted.

    Examples
    --------
    Reuse activity payloads already fetched by the activity stage::

        result = ingest(supabase, garmin_client, activities)
    """
    targets = [
        a
        for a in activities
        if a.get("activityId") is not None and has_exercise_sets(a)
    ]
    if not targets:
        logger.info("No set-bearing sessions in the window")
        return SourceResult(
            source="garmin_exercise_sets",
            status="skipped",
            detail_code="no_set_bearing_sessions",
        )

    sessions = 0
    stored = 0
    certain = 0
    failures = 0
    for activity in targets:
        activity_id = activity["activityId"]
        try:
            payload = garmin.get_activity_exercise_sets(activity_id)
        except Exception as exc:  # noqa: BLE001
            # One unreachable session must not cost the rest of the window.
            logger.error("Could not fetch sets for activity %s: %s", activity_id, exc)
            failures += 1
            continue

        rows = parse_sets(activity_id, payload)
        if not rows:
            continue
        try:
            _replace_sets(supabase, activity_id, rows)
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not store sets for activity %s: %s", activity_id, exc)
            failures += 1
            continue

        sessions += 1
        stored += len(rows)
        certain += sum(
            1
            for r in rows
            if r["set_type"] == "ACTIVE"
            and r["probability_pct"] == _CERTAIN_PROBABILITY
        )

    logger.info(
        "Exercise sets stored: %d sets across %d sessions (%d certainly identified)",
        stored,
        sessions,
        certain,
    )
    return SourceResult.from_counts(
        source="garmin_exercise_sets",
        attempted=len(targets),
        succeeded=sessions,
        rows_written=stored,
        detail_code="partial_exercise_set_failure" if failures else None,
    )
