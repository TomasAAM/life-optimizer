"""Tests for the planned-versus-done panel.

The hover assertions carry over the 2026-09-08 finding: a multi-series chart
under ``closest`` answers with the nearest point rather than the week pointed
at, and unified hover forbids ``%{x}`` in a template body and
``<extra></extra>`` entirely.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from dashboard import adherence_panel as ap
from dashboard import render
from dashboard.adherence import WeekAdherence


def _week(start: date, planned: float, done: float, current: bool = False) -> WeekAdherence:
    return WeekAdherence(
        week_start=start,
        is_current=current,
        planned_km=planned,
        done_km=done,
        key_planned=2,
        key_done=1,
        gym_planned=2,
        gym_done=2,
        misses=(f"{start:%a %d %b} · Easy Aerobic — planned 7.0 km · did nothing (missed)",),
    )


_WEEKS = [
    _week(date(2026, 9, 7), 65.9, 40.9),
    _week(date(2026, 9, 14), 54.0, 44.8),
    _week(date(2026, 9, 21), 21.0, 19.7, current=True),
]


class TestFigure:
    def test_one_bar_pair_per_week(self) -> None:
        fig = ap.build_adherence_figure(_WEEKS)
        assert [t.name for t in fig.data] == ["Planned", "Done"]
        assert len(fig.data[0].x) == 3
        assert fig.layout.barmode == "group"

    def test_the_week_in_progress_is_labelled_to_date(self) -> None:
        fig = ap.build_adherence_figure(_WEEKS)
        assert fig.data[0].x[-1] == "21 Sep (to date)"

    def test_hover_is_unified(self) -> None:
        assert ap.build_adherence_figure(_WEEKS).layout.hovermode == "x unified"

    def test_no_template_carries_forbidden_unified_tokens(self) -> None:
        for trace in ap.build_adherence_figure(_WEEKS).data:
            assert "<extra>" not in trace.hovertemplate
            assert "%{x}" not in trace.hovertemplate


class TestFragment:
    def test_cards_summarise_completed_weeks_only(self) -> None:
        html = ap.adherence_section_html(_WEEKS)
        # 40.9 + 44.8 of 65.9 + 54.0 km: the week in progress is excluded.
        assert "86 of 120 km" in html
        assert "71%" in html

    def test_misses_are_listed_newest_first(self) -> None:
        html = ap.adherence_section_html(_WEEKS)
        assert html.index("Mon 21 Sep") < html.index("Mon 14 Sep") < html.index("Mon 07 Sep")

    def test_no_weeks_renders_nothing(self) -> None:
        assert ap.adherence_section_html([]) == ""

    def test_the_panel_is_interpolated_into_the_plan_tab(self) -> None:
        """A fragment built but never placed renders as silence, not an error."""
        plan = render.PlanView(
            weeks=[render.PlanWeekView(
                header={"week_start": "2026-09-21", "phase": "base", "weeks_to_race": 12,
                        "target_race": "hyrox", "race_date": "2026-12-13"},
                sessions=pd.DataFrame(),
            )],
            selected_week_start="2026-09-21",
            adherence_html=ap.adherence_section_html(_WEEKS),
        )
        assert "Planned vs done" in render._plan_section(plan)
