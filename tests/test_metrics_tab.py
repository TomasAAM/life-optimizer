"""Tests for the metrics tab's figures, focused on hover behaviour.

Hover is the only way a reader gets an exact number off these charts, and a
wrong hover is invisible in a screenshot -- the chart still looks right. The
bug these pin: every figure was built with ``hovermode="closest"``, so on the
volume chart, which carries distance bars and a moving-time line on two y-axes,
Plotly answered with whichever *point* was nearest in pixels rather than the
series being pointed at. Roughly a quarter of pointer positions over a bar
returned the time line instead, and some returned nothing at all.

The time series therefore use ``"x unified"`` (one card per period, both series
in it) while the per-run scatter and the calendar keep ``"closest"``, where an
individual marker or cell really is the thing being pointed at.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from dashboard import activity_metrics as am
from dashboard import metrics_tab as mt

from tests.test_activity_metrics import _activities, _activity, _zones


_TODAY = date(2026, 6, 30)


@pytest.fixture(name="runs")
def _runs() -> pd.DataFrame:
    """A few months of outdoor runs, enough to fill every granularity."""
    rows = [
        _activity("2026-04-06", km=10.0, avg_hr=135.0),
        _activity("2026-04-09", km=8.0, avg_hr=150.0),
        _activity("2026-05-11", km=12.0, avg_hr=142.0),
        _activity("2026-05-14", km=15.0, avg_hr=158.0),
        _activity("2026-06-15", km=9.0, avg_hr=137.0),
        _activity("2026-06-18", km=21.0, avg_hr=165.0),
    ]
    return am.prepare_runs(_activities(rows))


@pytest.fixture(name="trend")
def _trend(runs: pd.DataFrame) -> pd.DataFrame:
    return am.pace_trend(runs, _zones())


def test_layout_defaults_to_closest_and_accepts_an_override() -> None:
    assert mt._layout()["hovermode"] == "closest"
    assert mt._layout(hovermode="x unified")["hovermode"] == "x unified"


class TestHovermodePerFigure:
    """Each figure declares the mode that suits what it is pointed at."""

    def test_volume_is_unified(self, runs: pd.DataFrame) -> None:
        fig = mt.build_volume_figure(runs, _TODAY)
        assert fig.layout.hovermode == "x unified"

    def test_cumulative_is_unified(self, runs: pd.DataFrame) -> None:
        fig = mt.build_cumulative_figure(runs, _TODAY)
        assert fig.layout.hovermode == "x unified"

    def test_efficiency_is_unified(self, trend: pd.DataFrame) -> None:
        fig = mt.build_efficiency_figure(am.aerobic_efficiency(trend))
        assert fig.layout.hovermode == "x unified"

    def test_calendar_stays_closest(self, runs: pd.DataFrame) -> None:
        """A heatmap cell is a single day; unified would span the whole week."""
        assert mt.build_calendar_figure(runs, _TODAY).layout.hovermode == "closest"

    def test_pace_scatter_stays_closest(self, trend: pd.DataFrame) -> None:
        """Each marker is one run, so the nearest marker is the right answer."""
        fig = mt.build_pace_figure(trend, am.monthly_easy_pace(trend))
        assert fig.layout.hovermode == "closest"


class TestUnifiedHoverTemplates:
    """Under unified hover the card header carries the x value already."""

    @pytest.mark.parametrize(
        "figure_name", ["volume", "cumulative", "efficiency"]
    )
    def test_no_trace_repeats_the_x_value(
        self, figure_name: str, runs: pd.DataFrame, trend: pd.DataFrame
    ) -> None:
        """A ``%{x}`` in the body prints the date once per row under the header."""
        figures = {
            "volume": lambda: mt.build_volume_figure(runs, _TODAY),
            "cumulative": lambda: mt.build_cumulative_figure(runs, _TODAY),
            "efficiency": lambda: mt.build_efficiency_figure(
                am.aerobic_efficiency(trend)
            ),
        }
        for trace in figures[figure_name]().data:
            assert "%{x" not in (trace.hovertemplate or "")

    @pytest.mark.parametrize(
        "figure_name", ["volume", "cumulative", "efficiency"]
    )
    def test_no_trace_suppresses_its_name(
        self, figure_name: str, runs: pd.DataFrame, trend: pd.DataFrame
    ) -> None:
        """``<extra></extra>`` would strip the label that identifies each row."""
        figures = {
            "volume": lambda: mt.build_volume_figure(runs, _TODAY),
            "cumulative": lambda: mt.build_cumulative_figure(runs, _TODAY),
            "efficiency": lambda: mt.build_efficiency_figure(
                am.aerobic_efficiency(trend)
            ),
        }
        for trace in figures[figure_name]().data:
            assert "<extra>" not in (trace.hovertemplate or "")

    def test_volume_header_format_matches_each_granularity(
        self, runs: pd.DataFrame
    ) -> None:
        """A month bar must not head its card with the month's first day."""
        fig = mt.build_volume_figure(runs, _TODAY)
        expected = [
            mt._HOVER_DATE_FORMAT[g] for g in am.GRANULARITIES for _ in range(2)
        ]
        assert [t.xhoverformat for t in fig.data] == expected

    def test_volume_still_reports_distance_time_and_run_count(
        self, runs: pd.DataFrame
    ) -> None:
        """The mode changed; the facts on the card must not have been lost."""
        bar, line = mt.build_volume_figure(runs, _TODAY).data[:2]
        assert "km" in bar.hovertemplate and "runs" in bar.hovertemplate
        assert "%{customdata[0]}" in bar.hovertemplate  # the run count
        assert "h" in line.hovertemplate


class TestTraceOrderContract:
    """The granularity buttons index traces positionally; order is a contract."""

    def test_six_traces_in_week_month_year_pairs(self, runs: pd.DataFrame) -> None:
        fig = mt.build_volume_figure(runs, _TODAY)
        assert [t.name for t in fig.data] == [
            "Weekly distance", "Weekly moving time",
            "Monthly distance", "Monthly moving time",
            "Yearly distance", "Yearly moving time",
        ]

    def test_only_the_weekly_pair_starts_visible(self, runs: pd.DataFrame) -> None:
        fig = mt.build_volume_figure(runs, _TODAY)
        assert [bool(t.visible) for t in fig.data] == [
            True, True, False, False, False, False
        ]


class TestCalendarPaddingCells:
    """The pivot pads the first and last weeks; those cells are not rest days."""

    def test_hover_is_off_for_gaps(self, runs: pd.DataFrame) -> None:
        """Without this, a padded cell hovers as a blank date and "0.0 km"."""
        fig = mt.build_calendar_figure(runs, _TODAY)
        assert fig.data[0].hoverongaps is False

    def test_padding_cells_are_gaps_not_zeroes(self, runs: pd.DataFrame) -> None:
        """A real rest day is 0.0 and must stay hoverable; padding is NaN."""
        fig = mt.build_calendar_figure(runs, _TODAY)
        z = pd.DataFrame(fig.data[0].z)
        assert z.isna().to_numpy().any(), "expected padded days outside the log"
        assert (z.fillna(-1).to_numpy() == 0).any(), "expected real rest days"


class TestPaceTooltipCarriesTheMarkerEncoding:
    """Marker colour is the zone and the hollow fill is treadmill."""

    def test_every_zone_trace_names_its_zone(self, trend: pd.DataFrame) -> None:
        fig = mt.build_pace_figure(trend, am.monthly_easy_pace(trend))
        for trace in fig.data:
            if trace.name == "Easy-run median":
                continue
            assert trace.name in trace.hovertemplate

    def test_surface_travels_in_customdata(self, trend: pd.DataFrame) -> None:
        """Treadmill varies run to run, so it cannot ride on the trace name."""
        fig = mt.build_pace_figure(trend, am.monthly_easy_pace(trend))
        run_traces = [t for t in fig.data if t.name != "Easy-run median"]
        assert run_traces
        for trace in run_traces:
            assert "%{customdata[3]}" in trace.hovertemplate
            surfaces = {row[3] for row in trace.customdata}
            assert surfaces <= {"outdoor", "treadmill"}

    def test_distance_pace_and_heart_rate_survive(self, trend: pd.DataFrame) -> None:
        fig = mt.build_pace_figure(trend, am.monthly_easy_pace(trend))
        template = fig.data[0].hovertemplate
        assert "%{customdata[1]:.1f} km" in template
        assert "%{text}/km" in template
        assert "%{customdata[2]:.0f} bpm" in template
