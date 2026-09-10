"""Tests for the strength tab's figures and fragment.

The hover assertions carry over the 2026-09-08 finding: a multi-series time
series under ``hovermode="closest"`` answers with the nearest *point* rather
than the series being pointed at, and unified hover forbids ``%{x}`` in a
template body and ``<extra></extra>`` entirely. Both figures here are
multi-series time series -- the volume chart is the exact bars-plus-line shape
that fix was found on -- and a wrong hover is invisible in a screenshot, which
is why it is pinned rather than eyeballed.

The fragment tests pin the second class of defect: a section that is built but
never interpolated into the returned page, which renders as silence rather than
as an error.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from dashboard import strength_metrics as sm
from dashboard import strength_tab as st

_TODAY = date(2026, 9, 9)


@pytest.fixture(name="activities")
def _activities() -> pd.DataFrame:
    return pd.DataFrame([
        {"activity_id": aid, "start_time_local": stamp,
         "activity_type": "strength_training", "activity_name": "Fuerza"}
        for aid, stamp in (
            (1, "2026-07-01T06:30:00"),
            (2, "2026-08-04T06:30:00"),
            (3, "2026-09-08T07:31:10"),
        )
    ])


@pytest.fixture(name="exercises")
def _exercises(activities: pd.DataFrame) -> pd.DataFrame:
    raw = pd.DataFrame([
        {"activity_id": aid, "category": "DEADLIFT", "sub_category": "BARBELL_DEADLIFT",
         "sets": 4, "reps": 12, "volume_kg": 1470.0, "max_weight_kg": weight,
         "active_duration_s": 120.0}
        for aid, weight in ((1, 120.0), (2, 130.0), (3, 140.0))
    ] + [
        {"activity_id": 3, "category": "UNKNOWN", "sub_category": "",
         "sets": 2, "reps": 20, "volume_kg": 300.0, "max_weight_kg": 30.0,
         "active_duration_s": 60.0},
    ])
    return sm.prepare_exercises(raw, activities)


@pytest.fixture(name="sets")
def _sets(activities: pd.DataFrame) -> pd.DataFrame:
    raw = pd.DataFrame([
        {"activity_id": aid, "set_index": 0, "set_type": "ACTIVE",
         "start_time": "2026-09-08T10:31:10+00:00", "duration_s": 30.0, "reps": 3,
         "weight_kg": weight, "category": "DEADLIFT",
         "exercise_name": "BARBELL_DEADLIFT", "probability_pct": 100.0}
        for aid, weight in ((1, 120.0), (2, 130.0), (3, 140.0))
    ])
    return sm.prepare_sets(raw, activities)


def _hovertemplates(fig) -> list[str]:
    return [t.hovertemplate for t in fig.data if t.hovertemplate]


class TestHoverContract:
    """Every figure here is the case unified hover exists for."""

    def test_the_shared_layout_defaults_to_unified(self) -> None:
        assert st._layout()["hovermode"] == "x unified"
        assert st._layout(hovermode="closest")["hovermode"] == "closest"

    def test_the_progression_chart_hovers_unified(
        self, sets: pd.DataFrame
    ) -> None:
        progression = sm.top_sets(sets)
        fig = st.build_progression_figure(progression, sm.trending_lifts(progression))
        assert fig.layout.hovermode == "x unified"

    def test_the_volume_chart_hovers_unified(self, exercises: pd.DataFrame) -> None:
        """Bars on one axis and a line on another is exactly the chart the
        2026-09-08 fix was found on: under ``closest`` it answers with whichever
        mark is nearest rather than with the series being pointed at."""
        fig = st.build_volume_figure(sm.weekly_volume(exercises))
        assert fig.layout.hovermode == "x unified"

    def test_no_template_carries_an_extra_tag(
        self, exercises: pd.DataFrame, sets: pd.DataFrame
    ) -> None:
        """Under unified hover the trace name labels the row, so an ``extra``
        tag blanks the label the row depends on."""
        progression = sm.top_sets(sets)
        figures = (
            st.build_progression_figure(progression, sm.trending_lifts(progression)),
            st.build_volume_figure(sm.weekly_volume(exercises)),
        )
        for fig in figures:
            for template in _hovertemplates(fig):
                assert "<extra>" not in template

    def test_no_template_repeats_the_date_in_its_body(
        self, exercises: pd.DataFrame, sets: pd.DataFrame
    ) -> None:
        """The unified card already heads every row with the date; a ``%{x}``
        in the body printed it again on each one."""
        progression = sm.top_sets(sets)
        figures = (
            st.build_progression_figure(progression, sm.trending_lifts(progression)),
            st.build_volume_figure(sm.weekly_volume(exercises)),
        )
        for fig in figures:
            for template in _hovertemplates(fig):
                assert "%{x" not in template

    def test_every_trace_declares_the_day_in_its_hover_header(
        self, exercises: pd.DataFrame
    ) -> None:
        fig = st.build_volume_figure(sm.weekly_volume(exercises))
        for trace in fig.data:
            assert trace.xhoverformat == st._HOVER_DAY

    def test_the_progression_hover_carries_the_reps(
        self, sets: pd.DataFrame
    ) -> None:
        """130 x 3 and 130 x 5 are different sessions, so a card of kilograms
        alone does not settle whether a lift moved."""
        progression = sm.top_sets(sets)
        fig = st.build_progression_figure(progression, sm.trending_lifts(progression))
        assert all("customdata[0]" in t for t in _hovertemplates(fig))


class TestVolumeFigure:
    """The stack has to stack, and the legend has to clear the title."""

    def test_bars_are_stacked(self, exercises: pd.DataFrame) -> None:
        fig = st.build_volume_figure(sm.weekly_volume(exercises))
        assert fig.layout.barmode == "stack"

    def test_the_legend_sits_below_the_plot(self, exercises: pd.DataFrame) -> None:
        """Seven patterns plus the set-count line wrap onto two rows and run
        straight through the title, and the title is what says the bars are
        tonnage rather than sets."""
        fig = st.build_volume_figure(sm.weekly_volume(exercises))
        assert fig.layout.legend.y < 0

    def test_an_empty_frame_still_yields_a_figure(self) -> None:
        fig = st.build_volume_figure(sm.weekly_volume(pd.DataFrame()))
        assert fig.data == ()


class TestFragment:
    """Every section that was built has to reach the page."""

    def test_all_sections_are_rendered(
        self, exercises: pd.DataFrame, sets: pd.DataFrame
    ) -> None:
        html = st.strength_section_html(exercises, sets, _TODAY)
        for heading in (
            "Load progression", "Prescribed vs lifted", "Volume", "Latest session"
        ):
            assert heading in html

    def test_a_stale_config_load_raises_a_callout(
        self, exercises: pd.DataFrame, sets: pd.DataFrame
    ) -> None:
        """The deadlift fixture lifts 140 kg against a 130 kg config."""
        html = st.strength_section_html(exercises, sets, _TODAY)
        assert "class='callout'" in html
        assert "ATHLETE_LOADS" in html

    def test_the_volume_note_names_the_day_the_loads_start(
        self, exercises: pd.DataFrame, sets: pd.DataFrame
    ) -> None:
        """Stating it is what stops the missing months reading as detraining."""
        html = st.strength_section_html(exercises, sets, _TODAY)
        assert "01 July 2026" in html

    def test_the_guess_count_is_stated_rather_than_charted(
        self, activities: pd.DataFrame, exercises: pd.DataFrame
    ) -> None:
        raw = pd.DataFrame([
            {"activity_id": 3, "set_index": i, "set_type": "ACTIVE",
             "start_time": "2026-09-08T10:31:10+00:00", "duration_s": 30.0,
             "reps": 3, "weight_kg": 120.0, "category": "SHRUG",
             "exercise_name": None, "probability_pct": 45.3}
            for i in range(3)
        ])
        html = st.strength_section_html(exercises, sm.prepare_sets(raw, activities), _TODAY)
        assert "3 of 3 working sets" in html

    def test_an_empty_log_explains_how_to_fill_it(self) -> None:
        html = st.strength_section_html(pd.DataFrame(), pd.DataFrame(), _TODAY)
        assert "backfill_exercise_sets" in html
