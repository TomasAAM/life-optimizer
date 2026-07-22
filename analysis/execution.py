"""Post-session execution analysis: prescribed week vs. what was actually done.

The plan is a *reference* for execution review — this module closes that loop. It
diffs the prescribed sessions for a plan week (``planned_sessions``) against the
Garmin activities actually recorded (``garmin_activities``), judged against the
lactate-anchored ``training_zones``, and produces a per-day adherence review plus
a short markdown digest.

Design mirrors the rest of the project: the scoring is a **pure function**
(:func:`review_week`) over DataFrames so it is deterministic and unit-testable;
the only I/O lives in :func:`main`, which pulls from Supabase and writes the
digest. Recovery data (HRV/CTL/readiness) is intentionally not used — this judges
*execution*, not readiness, consistent with the athlete self-regulating on the day.

Important limitation: run checks use session-average HR against the prescribed
zone. That is a clean test for easy/steady runs (which should sit in-zone
throughout) but only a directional one for interval sessions, where warm-up and
recoveries pull the average below the work HR. Interval sessions are therefore
assessed by the peak zone touched, not the average.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Map a planned session_type to the Garmin activity_type values that satisfy it.
_TYPE_MATCH: dict[str, frozenset[str]] = {
    "run": frozenset(
        {"running", "treadmill_running", "trail_running", "track_running",
         "indoor_running", "virtual_run"}
    ),
    "strength": frozenset({"strength_training", "indoor_cardio", "hiit"}),
    "functional": frozenset({"indoor_cardio", "hiit", "multi_sport", "fitness_equipment"}),
    "sim": frozenset({"indoor_cardio", "multi_sport", "running", "treadmill_running"}),
    "cross": frozenset({"indoor_cycling", "cycling", "open_water_swimming", "lap_swimming"}),
}
_RUN_TYPES = _TYPE_MATCH["run"]

# Zones whose intent is "stay easy" — a session average above the zone ceiling is
# a grey-zone breach worth flagging (the plan's "kill the grey zone" rule).
_EASY_ZONES = frozenset({"recovery", "endurance"})
_HARD_ZONES = frozenset({"tempo", "threshold", "vo2max"})

# Tolerance (bpm) before an easy run's average is called a grey-zone breach.
_GREY_TOLERANCE_BPM = 3


@dataclass(frozen=True)
class DayReview:
    """Prescribed-vs-actual outcome for a single day of the week."""

    day: str
    session_date: date
    planned_type: Optional[str]
    planned_title: Optional[str]
    planned_zone: Optional[str]
    planned_intensity: Optional[str]
    actual_type: Optional[str]
    actual_km: float
    actual_avg_hr: Optional[float]
    actual_max_hr: Optional[float]
    status: str  # done | missed | unplanned | rest_ok
    flags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WeekReview:
    """Whole-week adherence summary plus the per-day detail."""

    week_start: date
    planned_sessions: int
    completed_sessions: int
    planned_km: float
    actual_km: float
    grey_zone_breaches: int
    days: list[DayReview]

    @property
    def adherence_pct(self) -> Optional[int]:
        if self.planned_sessions == 0:
            return None
        return round(100 * self.completed_sessions / self.planned_sessions)

    def to_markdown(self) -> str:
        """Render the review as a compact markdown digest."""
        km_line = f"{self.actual_km:.1f} / {self.planned_km:.1f} km"
        adh = "n/a" if self.adherence_pct is None else f"{self.adherence_pct}%"
        lines = [
            f"# Execution review — week of {self.week_start.isoformat()}",
            "",
            f"- Sessions completed: **{self.completed_sessions}/{self.planned_sessions}** ({adh})",
            f"- Running volume: **{km_line}**",
            f"- Grey-zone breaches (easy runs run too hard): **{self.grey_zone_breaches}**",
            "",
            "| Day | Planned | Actual | Status | Flags |",
            "|---|---|---|---|---|",
        ]
        for d in self.days:
            planned = "rest" if d.planned_type in (None, "rest") else (
                f"{d.planned_title or d.planned_type}"
                + (f" · {d.planned_zone}" if d.planned_zone else "")
            )
            actual = "—"
            if d.actual_type:
                actual = d.actual_type
                if d.actual_km:
                    actual += f" · {d.actual_km:.1f}km"
                if d.actual_avg_hr:
                    actual += f" · {int(d.actual_avg_hr)}bpm"
            flags = ", ".join(d.flags) if d.flags else ""
            lines.append(
                f"| {d.day} | {planned} | {actual} | {d.status} | {flags} |"
            )
        return "\n".join(lines)


def _zone_ceiling(zones: pd.DataFrame, zone_name: str) -> Optional[float]:
    """Return the upper HR bound for a named zone, or ``None`` if unavailable."""
    if zones is None or zones.empty or not zone_name:
        return None
    match = zones[zones["zone_name"].str.lower() == zone_name.lower()]
    if match.empty:
        return None
    hi = match.iloc[0].get("hr_high")
    return None if pd.isna(hi) else float(hi)


def _zone_band(zones: pd.DataFrame, zone_name: str) -> tuple[Optional[float], Optional[float]]:
    """Return (hr_low, hr_high) for a named zone."""
    if zones is None or zones.empty or not zone_name:
        return None, None
    match = zones[zones["zone_name"].str.lower() == zone_name.lower()]
    if match.empty:
        return None, None
    row = match.iloc[0]
    lo = None if pd.isna(row.get("hr_low")) else float(row["hr_low"])
    hi = None if pd.isna(row.get("hr_high")) else float(row["hr_high"])
    return lo, hi


def _num(v: Any) -> float:
    try:
        f = float(v)
        return 0.0 if pd.isna(f) else f
    except (TypeError, ValueError):
        return 0.0


def review_week(
    planned: pd.DataFrame,
    activities: pd.DataFrame,
    zones: pd.DataFrame,
    week_start: date,
) -> WeekReview:
    """Score a plan week's execution against the activities actually recorded.

    Parameters
    ----------
    planned : pandas.DataFrame
        ``planned_sessions`` rows for the week (columns: session_date,
        session_type, title, zone, intensity, prescription).
    activities : pandas.DataFrame
        ``garmin_activities`` rows overlapping the week (start_time_local,
        activity_type, distance_m, avg_hr, max_hr).
    zones : pandas.DataFrame
        ``training_zones`` (zone_name, hr_low, hr_high).
    week_start : datetime.date
        Monday of the plan week.

    Returns
    -------
    WeekReview
        Whole-week adherence plus per-day detail.
    """
    days_order = ["Monday", "Tuesday", "Wednesday", "Thursday",
                  "Friday", "Saturday", "Sunday"]

    # Index activities by local date.
    acts = activities.copy() if activities is not None else pd.DataFrame()
    if not acts.empty and "start_time_local" in acts:
        acts = acts.assign(
            _day=pd.to_datetime(acts["start_time_local"], errors="coerce").dt.date
        )
    else:
        acts = acts.assign(_day=pd.Series(dtype="object"))

    plan = planned.copy() if planned is not None else pd.DataFrame()
    if not plan.empty and "session_date" in plan:
        plan = plan.assign(_day=pd.to_datetime(plan["session_date"], errors="coerce").dt.date)
    else:
        plan = plan.assign(_day=pd.Series(dtype="object"))

    day_reviews: list[DayReview] = []
    planned_sessions = 0
    completed_sessions = 0
    planned_km = 0.0
    actual_km = 0.0
    grey = 0

    for i, day_name in enumerate(days_order):
        d = week_start + timedelta(days=i)
        p_rows = plan[plan["_day"] == d] if not plan.empty else pd.DataFrame()
        a_rows = acts[acts["_day"] == d] if not acts.empty else pd.DataFrame()

        # Planned session for the day (first non-rest, if any).
        p_type = p_title = p_zone = p_intensity = None
        prescribed_km = 0.0
        is_training = False
        if not p_rows.empty:
            # Prefer a non-rest prescription.
            non_rest = p_rows[p_rows["session_type"] != "rest"]
            row = (non_rest.iloc[0] if not non_rest.empty else p_rows.iloc[0])
            p_type = row.get("session_type")
            p_title = row.get("title")
            p_zone = row.get("zone")
            p_intensity = row.get("intensity")
            is_training = p_type not in (None, "rest")
            presc = row.get("prescription")
            if isinstance(presc, str):
                try:
                    presc = json.loads(presc)
                except (json.JSONDecodeError, TypeError):
                    presc = {}
            if isinstance(presc, dict) and presc.get("distance_m"):
                prescribed_km = _num(presc["distance_m"]) / 1000.0

        planned_km += prescribed_km
        if is_training:
            planned_sessions += 1

        # Actual activity for the day.
        a_type = None
        a_km = a_avg = a_max = None
        if not a_rows.empty:
            arow = a_rows.iloc[0]
            a_type = arow.get("activity_type")
            a_km = _num(arow.get("distance_m")) / 1000.0
            a_avg = None if pd.isna(arow.get("avg_hr")) else _num(arow.get("avg_hr"))
            a_max = None if pd.isna(arow.get("max_hr")) else _num(arow.get("max_hr"))
            if a_type in _RUN_TYPES:
                actual_km += a_km

        flags: list[str] = []
        # Determine status.
        if is_training:
            expected = _TYPE_MATCH.get(p_type, frozenset())
            matched = a_type in expected if a_type else False
            if a_type and matched:
                status = "done"
                completed_sessions += 1
            elif a_type and not matched:
                status = "done"  # trained, but different modality than prescribed
                completed_sessions += 1
                flags.append(f"type mismatch (did {a_type})")
            else:
                status = "missed"
        else:
            status = "unplanned" if a_type else "rest_ok"

        # Grey-zone check: easy-intent run whose average sits above the zone ceiling.
        if a_type in _RUN_TYPES and a_avg is not None:
            zone_key = (p_zone or "").lower()
            intent_easy = zone_key in _EASY_ZONES or (p_intensity == "easy")
            if intent_easy:
                ceiling = _zone_ceiling(zones, p_zone) if p_zone else _zone_ceiling(zones, "Endurance")
                if ceiling is not None and a_avg > ceiling + _GREY_TOLERANCE_BPM:
                    flags.append(f"grey-zone: {int(a_avg)}bpm avg > {int(ceiling)} ceiling")
                    grey += 1
            elif zone_key in _HARD_ZONES and a_max is not None:
                lo, hi = _zone_band(zones, p_zone)
                if lo is not None and a_max < lo:
                    flags.append(f"under-target: peak {int(a_max)}bpm below {p_zone} band")

        day_reviews.append(
            DayReview(
                day=day_name,
                session_date=d,
                planned_type=p_type,
                planned_title=p_title,
                planned_zone=p_zone,
                planned_intensity=p_intensity,
                actual_type=a_type,
                actual_km=round(a_km, 2) if a_km else 0.0,
                actual_avg_hr=a_avg,
                actual_max_hr=a_max,
                status=status,
                flags=flags,
            )
        )

    return WeekReview(
        week_start=week_start,
        planned_sessions=planned_sessions,
        completed_sessions=completed_sessions,
        planned_km=round(planned_km, 1),
        actual_km=round(actual_km, 1),
        grey_zone_breaches=grey,
        days=day_reviews,
    )


def _fetch_week_activities(supabase, start: date, end: date) -> pd.DataFrame:
    """Fetch activities with HR + distance for a [start, end) local-date window."""
    result = (
        supabase.table("garmin_activities")
        .select("start_time_local,activity_type,distance_m,avg_hr,max_hr,is_multisport")
        .gte("start_time_local", start.isoformat())
        .lt("start_time_local", end.isoformat())
        .order("start_time_local")
        .execute()
    )
    return pd.DataFrame(result.data or [])


def main() -> None:
    """Review the current plan week and write the digest to ``data/``.

    Wires the pure :func:`review_week` to Supabase: pulls the week in progress,
    its prescribed sessions, the lactate zones and the week's activities, then
    writes ``data/execution_review.md`` + ``.json`` and prints the digest. Meant
    to run right after the Sunday ingestion job so the review reflects a full week.
    """
    import os
    from pathlib import Path

    from dashboard import query
    from plan import phase

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    supabase = query.get_supabase_client()

    today = date.today()
    # Review the most recently completed week by default (Monday just gone).
    week_start = phase.current_monday(today)
    if os.environ.get("REVIEW_LAST_WEEK") == "1":
        week_start = week_start - timedelta(days=7)
    week_end = week_start + timedelta(days=7)

    planned = query.fetch_planned_sessions(supabase, week_start.isoformat())
    zones = query.fetch_training_zones(supabase)
    activities = _fetch_week_activities(supabase, week_start, week_end)

    review = review_week(planned, activities, zones, week_start)
    md = review.to_markdown()
    print(md)

    out_dir = Path(__file__).parent.parent / "data"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "execution_review.md").write_text(md, encoding="utf-8")
    payload = {
        "week_start": review.week_start.isoformat(),
        "adherence_pct": review.adherence_pct,
        "completed_sessions": review.completed_sessions,
        "planned_sessions": review.planned_sessions,
        "planned_km": review.planned_km,
        "actual_km": review.actual_km,
        "grey_zone_breaches": review.grey_zone_breaches,
        "days": [
            {
                "day": d.day,
                "date": d.session_date.isoformat(),
                "planned_type": d.planned_type,
                "planned_title": d.planned_title,
                "planned_zone": d.planned_zone,
                "actual_type": d.actual_type,
                "actual_km": d.actual_km,
                "actual_avg_hr": d.actual_avg_hr,
                "status": d.status,
                "flags": d.flags,
            }
            for d in review.days
        ],
    }
    (out_dir / "execution_review.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Wrote execution review for week %s", week_start)


if __name__ == "__main__":
    main()
