"""Export the training block Supabase currently holds back to JSON.

:mod:`plan.persist` is one-way: it reads ``data/plan_block.json`` and pushes it
into Supabase. Anything that edits the plan directly in the database - a manual
correction, a mid-week revision - leaves the JSON behind, and the next
``python -m plan.persist`` would silently overwrite the database with the stale
file.

This module closes the loop. It reads back exactly the weeks
:func:`plan.context.compute_block` says the block covers, maps the stored rows
to the same :class:`~plan.models.PlannedBlock` schema the generator writes, and
rewrites the JSON. Running ``export`` and then ``persist`` is therefore a no-op,
which is the property that makes the file safe to keep in version control.

Run with ``python -m plan.export [path]``.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from dashboard import query
from plan import context
from plan.config import DEFAULT_CONFIG, PlanConfig
from plan.models import PlannedBlock, PlannedSession, PlannedWeek, Step

_PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)

logger = logging.getLogger(__name__)

_DAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def _fetch_week_header(supabase, week_start_iso: str) -> dict[str, Any] | None:
    """Fetch one ``training_plan_weeks`` row by its Monday.

    Parameters
    ----------
    supabase : supabase.Client
        Authenticated Supabase client.
    week_start_iso : str
        ISO date of the plan week's Monday.

    Returns
    -------
    dict or None
        The week header, or ``None`` when the week has not been persisted.
    """
    result = (
        supabase.table("training_plan_weeks")
        .select("*")
        .eq("week_start", week_start_iso)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def _to_session(row: dict[str, Any]) -> PlannedSession:
    """Map a ``planned_sessions`` row back to a :class:`PlannedSession`.

    The inverse of :func:`plan.persist._to_rows`: the flat columns come straight
    back, and the fields packed into the ``prescription`` JSON blob (detail,
    duration, distance, steps, why) are unpacked. ``day`` is not stored - it is
    recovered from ``session_date``.

    Parameters
    ----------
    row : dict
        One ``planned_sessions`` row.

    Returns
    -------
    PlannedSession
        The validated session model.
    """
    prescription = row.get("prescription") or {}
    session_date = date.fromisoformat(str(row["session_date"]))
    return PlannedSession(
        day=_DAY_NAMES[session_date.weekday()],
        session_type=row["session_type"],
        title=row["title"],
        zone=row.get("zone"),
        intensity=row["intensity"],
        duration_min=prescription.get("duration_min"),
        distance_m=prescription.get("distance_m"),
        prescription=prescription.get("detail") or "",
        steps=[Step(**step) for step in prescription.get("steps") or []],
        purpose=row["purpose"],
        why=prescription.get("why") or "",
        hyrox_focus=row.get("hyrox_focus"),
    )


def _to_week(header: dict[str, Any], rows: list[dict[str, Any]]) -> PlannedWeek:
    """Assemble one :class:`PlannedWeek` from its header and session rows.

    Parameters
    ----------
    header : dict
        The ``training_plan_weeks`` row.
    rows : list of dict
        That week's ``planned_sessions`` rows, in date order.

    Returns
    -------
    PlannedWeek
        The validated week model.
    """
    return PlannedWeek(
        rationale=header.get("rationale") or "",
        methodology=header.get("methodology") or "",
        sessions=[_to_session(r) for r in rows],
    )


def export(path: Path, cfg: PlanConfig = DEFAULT_CONFIG) -> int:
    """Write the block Supabase currently holds to ``path`` as JSON.

    Parameters
    ----------
    path : pathlib.Path
        Destination for the ``PlannedBlock`` JSON.
    cfg : PlanConfig
        Plan configuration; determines which weeks make up the current block.

    Returns
    -------
    int
        Number of weeks written.

    Raises
    ------
    ValueError
        If a week in the current block has no header or no sessions in the
        database - exporting a partial block would produce a file that
        :mod:`plan.persist` rejects, or worse, silently accepts.
    """
    supabase = query.get_supabase_client()
    meta = context.compute_block(cfg)

    weeks: list[PlannedWeek] = []
    for wctx in meta:
        week_iso = wctx.week_start.isoformat()
        header = _fetch_week_header(supabase, week_iso)
        if header is None:
            raise ValueError(
                f"No training_plan_weeks row for {week_iso}. The current block spans "
                f"{meta[0].week_start}..{meta[-1].week_start}; generate the missing "
                "week before exporting."
            )
        rows = query.fetch_planned_sessions(supabase, week_iso).to_dict("records")
        if not rows:
            raise ValueError(f"Week {week_iso} has a header but no planned_sessions rows.")
        weeks.append(_to_week(header, rows))
        logger.info("  week %s: %d sessions", week_iso, len(rows))

    block = PlannedBlock(weeks=weeks)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(block.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info(
        "Exported %d weeks (%s..%s) to %s",
        len(weeks),
        meta[0].week_start,
        meta[-1].week_start,
        path,
    )
    return len(weeks)


def main() -> None:
    """Export the current block to the path named on the command line."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(
        description="Export the persisted training block from Supabase to JSON."
    )
    parser.add_argument(
        "path", nargs="?", default=str(context.PLAN_FILE),
        help="Destination for the PlannedBlock JSON (default: data/plan_block.json)",
    )
    args = parser.parse_args()
    export(Path(args.path))


if __name__ == "__main__":
    main()
