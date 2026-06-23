"""Dashboard build orchestrator.

Pulls data from Supabase, computes the load and HRV metrics, renders the HTML
report, and writes it to ``public/index.html`` for GitHub Pages.
"""

from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv

from dashboard import metrics, query, render, zones

_PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_OUTPUT_PATH = _PROJECT_ROOT / "public" / "index.html"


def _build_plan_view(supabase, activities) -> render.PlanView:
    """Assemble the training-plan view model from the latest generated week.

    Reads the most recent plan week, its sessions (scored for adherence against
    actual activities), and the lactate zones. Degrades gracefully to an empty
    view when no plan has been generated yet.

    Parameters
    ----------
    supabase : supabase.Client
        Authenticated Supabase client.
    activities : pandas.DataFrame
        Activities used to score session adherence.

    Returns
    -------
    render.PlanView
        View model consumed by :func:`dashboard.render.render_html`.
    """
    zones_df = query.fetch_training_zones(supabase)
    week = query.fetch_latest_plan_week(supabase)
    if week is None:
        return render.PlanView(
            week=None, sessions=query.fetch_planned_sessions(supabase, ""), zones=zones_df
        )

    sessions = query.fetch_planned_sessions(supabase, week["week_start"])
    sessions = metrics.compute_adherence(sessions, activities)
    return render.PlanView(week=week, sessions=sessions, zones=zones_df)


def main() -> None:
    """Build the dashboard HTML and write it to ``public/index.html``."""
    logger.info("Building dashboard")

    supabase = query.get_supabase_client()
    activities = query.fetch_activities(supabase)
    hrv_raw = query.fetch_hrv(supabase)
    logger.info("Fetched %d activities, %d HRV reading rows", len(activities), len(hrv_raw))

    load_series = metrics.build_load_series(activities)
    hrv_series = metrics.build_hrv_series(hrv_raw)

    if load_series.empty:
        logger.warning("No activity load data available; nothing to render")
        return

    weekly = metrics.weekly_summary(load_series, hrv_series)
    snapshot = metrics.latest_snapshot(load_series, hrv_series)

    plan_view = _build_plan_view(supabase, activities)

    fig = render.build_figure(load_series, hrv_series)
    zones_fig = zones.build_zone_comparison_figure()
    pace_fig = zones.build_pace_comparison_figure()
    html = render.render_html(fig, snapshot, weekly, zones_fig, pace_fig, plan=plan_view)

    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_PATH.write_text(html, encoding="utf-8")
    logger.info("Dashboard written to %s", _OUTPUT_PATH)
    logger.info(
        "Snapshot: CTL=%.1f ATL=%.1f TSB=%+.1f (%s) | HRV=%s status=%s",
        snapshot.ctl,
        snapshot.atl,
        snapshot.tsb,
        snapshot.tsb_label,
        snapshot.hrv_night,
        snapshot.hrv_status,
    )


if __name__ == "__main__":
    main()
