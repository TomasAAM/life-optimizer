"""Dashboard build orchestrator.

Pulls data from Supabase, computes the load and HRV metrics, renders the HTML
report, and writes it to ``public/index.html`` for GitHub Pages.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

from dashboard import (
    activity_metrics,
    adherence,
    adherence_panel,
    body_metrics,
    body_tab,
    metrics,
    metrics_tab,
    query,
    recap_metrics,
    recap_tab,
    render,
    strength_metrics,
    strength_tab,
    zones,
)
from plan.config import DEFAULT_CONFIG
from plan.phase import current_monday

_PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_OUTPUT_PATH = _PROJECT_ROOT / "public" / "index.html"

# Completed plan weeks shown in the planned-versus-done panel, before the week
# in progress.
_ADHERENCE_HISTORY_WEEKS = 8


def _build_plan_view(supabase, activities) -> render.PlanView:
    """Assemble the training-plan view model for the whole current block.

    Reads every week of the block from the week the dashboard should be showing
    onward — the week in progress, or on a Sunday the week starting tomorrow —
    each with its sessions scored for adherence against actual activities, plus
    the lactate zones. Every week is loaded so the rendered page can switch
    between them client-side, and the block is anchored to the displayed week so
    the strip and the session list never disagree. Degrades gracefully to an
    empty view when no plan has been generated yet.

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
    today = date.today()
    current = query.fetch_current_plan_week(supabase, today.isoformat())
    if current is None:
        return render.PlanView(weeks=[], zones=zones_df, selected_week_start="")

    # Anchored to the displayed week, not to today's Monday, so the selected week
    # is always the first cell of the strip — including on a Sunday, when the
    # displayed week is the one starting tomorrow.
    headers = query.fetch_plan_block(supabase, current["week_start"])
    weeks = [
        render.PlanWeekView(
            header=header,
            sessions=adherence.score_sessions(
                query.fetch_planned_sessions(supabase, header["week_start"]),
                activities,
                today,
            ),
        )
        for header in headers
    ]
    logger.info("Loaded %d plan weeks for the block", len(weeks))
    return render.PlanView(
        weeks=weeks,
        zones=zones_df,
        selected_week_start=current["week_start"],
        adherence_html=_adherence_html(supabase, activities, today),
    )


def _adherence_html(supabase, activities, today: date) -> str:
    """Score the recent plan weeks against activities and render the panel.

    Covers the week in progress plus the ``_ADHERENCE_HISTORY_WEEKS`` before it.

    Parameters
    ----------
    supabase : supabase.Client
        Authenticated Supabase client.
    activities : pandas.DataFrame
        Every activity.
    today : datetime.date
        The build date.

    Returns
    -------
    str
        The planned-versus-done panel, or an empty string with no plan history.
    """
    this_monday = current_monday(today)
    first_monday = this_monday - timedelta(weeks=_ADHERENCE_HISTORY_WEEKS)
    planned = query.fetch_planned_sessions_between(
        supabase, first_monday.isoformat(), this_monday.isoformat()
    )
    scored = adherence.score_sessions(planned, activities, today)
    weeks = adherence.weekly_adherence(scored, activities, today)
    logger.info("Adherence: %d plan weeks scored", len(weeks))
    return adherence_panel.adherence_section_html(weeks)


def _recap_html(
    supabase,
    activities,
    runs,
    zones_df,
    strength_sets,
    body,
    hrv_series,
    today: date,
) -> str:
    """Build every month's recap and render the Recap tab.

    Planned sessions are fetched once for the whole history and scored with the
    same rules as the Training plan tab, so the two can never disagree.

    Parameters
    ----------
    supabase : supabase.Client
        Authenticated Supabase client.
    activities : pandas.DataFrame
        Every activity.
    runs : pandas.DataFrame
        Output of :func:`dashboard.activity_metrics.prepare_runs`.
    zones_df : pandas.DataFrame
        The lactate zone table.
    strength_sets : pandas.DataFrame
        Output of :func:`dashboard.strength_metrics.prepare_sets`.
    body : pandas.DataFrame
        Raw weigh-ins from :func:`dashboard.query.fetch_body_composition`.
    hrv_series : pandas.DataFrame
        Output of :func:`dashboard.metrics.build_hrv_series`.
    today : datetime.date
        The build date.

    Returns
    -------
    str
        The Recap tab fragment, or an empty string with no activities.
    """
    months = recap_metrics.available_months(activities, today)
    if not months:
        return ""
    first_monday = current_monday(months[-1])
    planned = query.fetch_planned_sessions_between(
        supabase, first_monday.isoformat(), current_monday(today).isoformat()
    )
    scored = adherence.score_sessions(planned, activities, today)
    weigh_ins = body_metrics.prepare_weigh_ins(body)
    recaps = [
        recap_metrics.build_month_recap(
            month, today, activities, runs, zones_df, scored,
            strength_sets, weigh_ins, hrv_series, DEFAULT_CONFIG.races,
        )
        for month in months
    ]
    # Open on the last finished month: on the 2nd, two days of October say
    # far less than the whole of September.
    finished = [r for r in recaps if not r.in_progress]
    selected = (finished[0] if finished else recaps[0]).key
    logger.info("Recap: %d months, opening on %s", len(recaps), selected)
    return recap_tab.recap_section_html(recaps, selected)


def main() -> None:
    """Build the dashboard HTML and write it to ``public/index.html``."""
    logger.info("Building dashboard")

    supabase = query.get_supabase_client()
    activities = query.fetch_activities(supabase)
    hrv_raw = query.fetch_hrv(supabase)
    source_status = query.fetch_ingestion_status(supabase)
    logger.info(
        "Fetched %d activities, %d HRV reading rows", len(activities), len(hrv_raw)
    )

    load_series = metrics.build_load_series(activities)
    hrv_series = metrics.build_hrv_series(hrv_raw)

    if load_series.empty:
        logger.warning("No activity load data available; nothing to render")
        return

    weekly = metrics.weekly_summary(load_series, hrv_series)
    snapshot = metrics.latest_snapshot(load_series, hrv_series)

    plan_view = _build_plan_view(supabase, activities)

    today = date.today()
    runs = activity_metrics.prepare_runs(activities)
    metrics_html = metrics_tab.metrics_section_html(
        runs, activities, query.fetch_training_zones(supabase), today
    )
    logger.info(
        "Metrics: %d runs (%d excluded for implausible pace)",
        len(runs),
        int(runs["implausible"].sum()) if not runs.empty else 0,
    )

    body = query.fetch_body_composition(supabase)
    body_html = body_tab.body_section_html(body, today)
    logger.info("Body composition: %d weigh-ins", len(body))

    exercises = strength_metrics.prepare_exercises(
        query.fetch_activity_exercises(supabase), activities
    )
    strength_sets = strength_metrics.prepare_sets(
        query.fetch_exercise_sets(supabase), activities
    )
    strength_html = strength_tab.strength_section_html(exercises, strength_sets, today)
    logger.info(
        "Strength: %d exercises over %d sessions, %d working sets (%d identified)",
        len(exercises),
        exercises["activity_id"].nunique() if not exercises.empty else 0,
        len(strength_sets),
        int(strength_sets["settled"].sum()) if not strength_sets.empty else 0,
    )

    recap_html = _recap_html(
        supabase,
        activities,
        runs,
        query.fetch_training_zones(supabase),
        strength_sets,
        body,
        hrv_series,
        today,
    )

    fig = render.build_figure(load_series, hrv_series)
    zones_fig = zones.build_zone_comparison_figure()
    pace_fig = zones.build_pace_comparison_figure()
    html = render.render_html(
        fig,
        snapshot,
        weekly,
        zones_fig,
        pace_fig,
        plan=plan_view,
        metrics_html=metrics_html,
        body_html=body_html,
        strength_html=strength_html,
        source_status=source_status,
        recap_html=recap_html,
    )

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
