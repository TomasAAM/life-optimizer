"""Tests for the training-plan rendering, in particular week switching.

The dashboard is a static HTML file, so every week of the block is rendered at
build time and toggled in the browser. These tests pin the invariants that makes
that safe: one strip button and one panel per week, exactly one week active, and
element ids that stay unique across weeks.
"""

from __future__ import annotations

import re

import pandas as pd

from dashboard.render import PlanView, PlanWeekView, _plan_section


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
