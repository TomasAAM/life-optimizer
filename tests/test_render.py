"""Tests for the dashboard rendering: tab layout and training-plan week switching.

The dashboard is a static HTML file, so every week of the block is rendered at
build time and toggled in the browser. These tests pin the invariants that makes
that safe: one strip button and one panel per week, exactly one week active, and
element ids that stay unique across weeks. They also pin which tab opens first,
since every other tab is hidden at load and depends on that being unambiguous.
"""

from __future__ import annotations

import re

import pandas as pd
import plotly.graph_objects as go

from dashboard.metrics import ReadinessSnapshot
from dashboard.render import (
    PlanView,
    PlanWeekView,
    _plan_section,
    build_figure,
    render_html,
)


def _header(week_start: str, phase: str = "base", weeks_to_race: int = 14) -> dict:
    """Build a ``training_plan_weeks`` row for tests."""
    return {
        "week_start": week_start,
        "target_race": "hyrox",
        "race_date": "2026-11-14",
        "phase": phase,
        "weeks_to_race": weeks_to_race,
        "model": "claude-code",
        "rationale": f"Rationale for {week_start}.",
        "methodology": f"Methodology for {week_start}.",
    }


def _sessions(week_start: str, n: int = 2) -> pd.DataFrame:
    """Build a small planned-sessions frame for tests."""
    return pd.DataFrame(
        [
            {
                "week_start": week_start,
                "session_date": f"2026-08-{10 + i:02d}",
                "session_type": "run",
                "title": f"Session {i}",
                "zone": "Endurance",
                "intensity": "easy",
                "prescription": {"detail": "Easy run", "steps": [], "why": "Because."},
                "purpose": "Aerobic base.",
                "hyrox_focus": None,
                "status": "upcoming",
            }
            for i in range(n)
        ]
    )


def _view(selected: str = "2026-08-17") -> PlanView:
    """A three-week block with the middle week selected."""
    starts = ["2026-08-10", "2026-08-17", "2026-08-24"]
    return PlanView(
        weeks=[PlanWeekView(header=_header(s), sessions=_sessions(s)) for s in starts],
        zones=pd.DataFrame(),
        selected_week_start=selected,
    )


def test_empty_plan_renders_placeholder() -> None:
    html = _plan_section(PlanView())
    assert "No plan generated yet" in html


def test_one_strip_button_and_one_panel_per_week() -> None:
    html = _plan_section(_view())
    for week_start in ("2026-08-10", "2026-08-17", "2026-08-24"):
        assert html.count(f'data-week="{week_start}"') == 1
        # cards + week panel + methodology paragraph
        assert html.count(f'data-week-panel="{week_start}"') == 3


def test_exactly_one_week_is_active_and_it_is_the_selected_one() -> None:
    html = _plan_section(_view(selected="2026-08-17"))
    assert html.count('aria-pressed="true"') == 1
    assert html.count("phase-cell selected") == 1
    assert 'data-week="2026-08-17" aria-pressed="true"' in html
    # Three active panes belong to the selected week only.
    assert len(re.findall(r'wk-(?:cards|pane) active" data-week-panel="2026-08-17"', html)) == 3
    assert 'active" data-week-panel="2026-08-10"' not in html


def test_session_ids_are_unique_across_weeks() -> None:
    html = _plan_section(_view())
    ids = re.findall(r"id='(psess-[^']+)'", html)
    assert len(ids) == 6
    assert len(set(ids)) == len(ids)
    assert "psess-2026-08-10-0" in ids
    assert "psess-2026-08-24-1" in ids


def test_selection_falls_back_to_first_week_when_unset() -> None:
    html = _plan_section(_view(selected=""))
    assert 'data-week="2026-08-10" aria-pressed="true"' in html


def test_block_card_numbers_each_week_in_order() -> None:
    html = _plan_section(_view())
    for i in (1, 2, 3):
        assert f"Week {i} of 3" in html


def _snapshot() -> ReadinessSnapshot:
    """A minimal readiness snapshot for the header cards."""
    return ReadinessSnapshot(
        date=pd.Timestamp("2026-09-01"),
        ctl=100.0,
        atl=90.0,
        tsb=10.0,
        tsb_label="Fresh / tapered",
        hrv_night=50.0,
        hrv_status="BALANCED",
    )


def _document() -> str:
    """Render a full document with empty figures and no plan."""
    return render_html(
        go.Figure(),
        _snapshot(),
        pd.DataFrame(columns=["week_start", "total_load"]),
        go.Figure(),
        go.Figure(),
        plan=PlanView(),
    )


def test_training_plan_is_the_tab_that_opens_first() -> None:
    html = _document()
    assert '<button class="tab-btn active" data-tab="plan">' in html
    assert '<div class="tab-panel active" id="tab-plan">' in html


def test_exactly_one_tab_button_and_one_tab_panel_are_active() -> None:
    html = _document()
    assert html.count('class="tab-btn active"') == 1
    assert html.count('class="tab-panel active"') == 1


def _load_series(days: int = 40) -> pd.DataFrame:
    index = pd.date_range("2026-06-01", periods=days, freq="D")
    return pd.DataFrame(
        {"load": 60.0, "ctl": 80.0, "atl": 85.0, "tsb": -5.0}, index=index
    )


def _hrv_series(days: int = 40) -> pd.DataFrame:
    index = pd.date_range("2026-06-01", periods=days, freq="D")
    return pd.DataFrame(
        {"hrv_night": 45.0, "baseline_high": 51.0, "baseline_low": 43.0},
        index=index,
    )


def test_load_chart_rows_do_not_repeat_the_date() -> None:
    """The chart is "x unified", so the date already heads the card.

    A ``%{x|...}`` prefix in each body printed it again on every row, so one
    tooltip read "Sun 28 Jun" five times under a "Jun 28, 2026" header.
    """
    fig = build_figure(_load_series(), _hrv_series())
    for trace in fig.data:
        assert "%{x" not in (trace.hovertemplate or "")


def test_load_chart_header_spells_out_the_date() -> None:
    """Without an explicit format the unified header reads "Jun 28, 2026"."""
    fig = build_figure(_load_series(), _hrv_series())
    assert fig.layout.hovermode == "x unified"
    assert all(t.xhoverformat == "%a %d %b %Y" for t in fig.data)


def test_load_chart_rows_still_name_their_series() -> None:
    """Dropping the date must not leave a bare number on the row."""
    fig = build_figure(_load_series(), _hrv_series())
    labelled = [t.hovertemplate for t in fig.data if t.hovertemplate]
    assert any("Load:" in t for t in labelled)
    assert any("CTL:" in t for t in labelled)
    assert any("ATL:" in t for t in labelled)
    assert any("TSB:" in t for t in labelled)
    assert any("HRV:" in t for t in labelled)
