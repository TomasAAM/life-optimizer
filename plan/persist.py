"""Persist a Claude-Code-generated training block to Supabase.

Reads the ``PlannedBlock`` JSON the agent wrote (default ``data/plan_block.json``),
validates it against the Pydantic schema, assigns each week its deterministic
``week_start`` (block start + 7*i, recomputed here so dates are authoritative
regardless of what the agent wrote), and upserts ``training_plan_weeks`` +
``planned_sessions`` for every week in the block.

Run with ``python -m plan.persist [path]``.
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from dashboard import query
from plan import context
from plan.config import DEFAULT_CONFIG, PlanConfig
from plan.context import WeekContext
from plan.models import PlannedBlock, PlannedWeek

logger = logging.getLogger(__name__)

# Recorded as the "model" for audit: generation is done by the Claude Code agent,
# not an API model.
_GENERATOR = "claude-code"

_DAY_INDEX = {
    "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
    "Friday": 4, "Saturday": 5, "Sunday": 6,
}


def _to_rows(week: PlannedWeek, week_start: date) -> list[dict[str, Any]]:
    """Map a validated ``PlannedWeek`` to ``planned_sessions`` rows."""
    rows: list[dict[str, Any]] = []
    for s in week.sessions:
        session_date = week_start + timedelta(days=_DAY_INDEX[s.day])
        rows.append(
            {
                "week_start": week_start.isoformat(),
                "session_date": session_date.isoformat(),
                "session_type": s.session_type,
                "title": s.title,
                "zone": s.zone,
                "intensity": s.intensity,
                "prescription": {
                    "detail": s.prescription,
                    "duration_min": s.duration_min,
                    "distance_m": s.distance_m,
                    "steps": [step.model_dump() for step in s.steps],
                    "why": s.why,
                },
                "purpose": s.purpose,
                "hyrox_focus": s.hyrox_focus,
            }
        )
    return rows


def _persist_week(supabase, week: PlannedWeek, wctx: WeekContext, cfg: PlanConfig) -> int:
    """Upsert one week's header and its sessions; return the session count."""
    week_start = wctx.week_start
    supabase.table("training_plan_weeks").upsert(
        {
            "week_start": week_start.isoformat(),
            "target_race": wctx.race_name or "none",
            "race_date": wctx.race_date.isoformat() if wctx.race_date else None,
            "phase": wctx.phase_name,
            "weeks_to_race": wctx.weeks_remaining,
            # Load band is intentionally null: volume is driven by the km target
            # and session structure, not a Garmin-CTL-derived load band.
            "load_target_low": None,
            "load_target_high": None,
            "model": _GENERATOR,
            "input_summary": None,
            "rationale": week.rationale,
            "methodology": week.methodology,
        },
        on_conflict="week_start",
    ).execute()

    supabase.table("planned_sessions").delete().eq(
        "week_start", week_start.isoformat()
    ).execute()
    rows = _to_rows(week, week_start)
    supabase.table("planned_sessions").upsert(rows).execute()
    logger.info("  week %s (%s): %d sessions", week_start, wctx.phase_name, len(rows))
    return len(rows)


def persist(path: Path, cfg: PlanConfig = DEFAULT_CONFIG) -> int:
    """Validate and store a generated block.

    Parameters
    ----------
    path : pathlib.Path
        Path to the ``PlannedBlock`` JSON written by the agent.
    cfg : PlanConfig
        Plan configuration.

    Returns
    -------
    int
        Total number of planned sessions written across the block.

    Raises
    ------
    ValueError
        If the block's week count does not match the configured block length.
    """
    block = PlannedBlock.model_validate_json(path.read_text(encoding="utf-8"))
    meta = context.compute_block(cfg)
    if len(block.weeks) != len(meta):
        raise ValueError(
            f"Block has {len(block.weeks)} weeks but the config expects {len(meta)} "
            f"(block_weeks={cfg.block_weeks}). Regenerate to match."
        )

    supabase = query.get_supabase_client()
    total = 0
    for week, wctx in zip(block.weeks, meta):
        total += _persist_week(supabase, week, wctx, cfg)

    logger.info(
        "Persisted %d sessions across %d weeks (%s..%s)",
        total,
        len(meta),
        meta[0].week_start,
        meta[-1].week_start,
    )
    return total


def main() -> None:
    """Persist the plan JSON named on the command line (or the default path)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Persist a generated training block.")
    parser.add_argument(
        "path", nargs="?", default=str(context.PLAN_FILE),
        help="Path to the PlannedBlock JSON (default: data/plan_block.json)",
    )
    args = parser.parse_args()
    persist(Path(args.path))


if __name__ == "__main__":
    main()
