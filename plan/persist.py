"""Persist a Claude-Code-generated weekly plan to Supabase.

Reads the ``PlannedWeek`` JSON the agent wrote (default ``data/plan_week.json``),
validates it against the Pydantic schema, recomputes the deterministic week
metadata (so the header is authoritative regardless of what the agent wrote),
and upserts ``training_plan_weeks`` + ``planned_sessions``.

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
from plan.models import PlannedWeek

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
                },
                "purpose": s.purpose,
                "hyrox_focus": s.hyrox_focus,
            }
        )
    return rows


def persist(path: Path, cfg: PlanConfig = DEFAULT_CONFIG) -> int:
    """Validate and store the generated week.

    Parameters
    ----------
    path : pathlib.Path
        Path to the ``PlannedWeek`` JSON written by the agent.
    cfg : PlanConfig
        Plan configuration.

    Returns
    -------
    int
        Number of planned sessions written.
    """
    week = PlannedWeek.model_validate_json(path.read_text(encoding="utf-8"))
    bundle = context.gather(cfg)
    supabase = query.get_supabase_client()

    supabase.table("training_plan_weeks").upsert(
        {
            "week_start": bundle.week_start.isoformat(),
            "target_race": cfg.target_race,
            "race_date": cfg.race_date.isoformat(),
            "phase": bundle.phase_name,
            "weeks_to_race": bundle.weeks_remaining,
            "load_target_low": bundle.load_band[0],
            "load_target_high": bundle.load_band[1],
            "model": _GENERATOR,
            "input_summary": bundle.summary,
            "rationale": week.rationale,
        },
        on_conflict="week_start",
    ).execute()

    supabase.table("planned_sessions").delete().eq(
        "week_start", bundle.week_start.isoformat()
    ).execute()
    rows = _to_rows(week, bundle.week_start)
    supabase.table("planned_sessions").upsert(rows).execute()

    logger.info("Persisted %d sessions for week %s", len(rows), bundle.week_start)
    return len(rows)


def main() -> None:
    """Persist the plan JSON named on the command line (or the default path)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Persist a generated weekly plan.")
    parser.add_argument(
        "path", nargs="?", default=str(context.PLAN_FILE),
        help="Path to the PlannedWeek JSON (default: data/plan_week.json)",
    )
    args = parser.parse_args()
    persist(Path(args.path))


if __name__ == "__main__":
    main()
