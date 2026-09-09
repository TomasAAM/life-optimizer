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


# --- Running form -----------------------------------------------------------


def _form_frames(trend: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The monthly medians and the runs behind them, as the figure takes them."""
    return am.monthly_form_metrics(trend), am.form_runs(trend)


@pytest.fixture(name="form_trend")
def _form_trend() -> pd.DataFrame:
    """Easy runs across three months, outdoor and treadmill, plus one hard one."""
    rows = [
        _activity("2026-04-06", avg_hr=130.0, cadence=160.0),
        # A second outdoor April run, so at least one month's median is taken
        # over more than one run rather than being a run in disguise.
        _activity("2026-04-27", avg_hr=130.0, cadence=168.0),
        _activity("2026-04-20", avg_hr=130.0, cadence=162.0,
                  activity_type="treadmill_running"),
        _activity("2026-05-11", avg_hr=130.0, cadence=163.0),
        _activity("2026-05-25", avg_hr=130.0, cadence=164.0,
                  activity_type="treadmill_running"),
        _activity("2026-06-15", avg_hr=130.0, cadence=166.0),
        _activity("2026-06-18", avg_hr=170.0, cadence=180.0),  # VO2max, excluded
    ]
    return am.pace_trend(am.prepare_runs(_activities(rows)), _zones())


class TestFormGrid:
    """Five metrics over two columns, the odd one widened rather than orphaned."""

    def test_positions_fill_two_columns_in_order(self) -> None:
        assert mt._form_grid_positions() == [(1, 1), (1, 2), (2, 1), (2, 2), (3, 1)]

    def test_a_lone_trailing_panel_spans_the_full_width(self) -> None:
        specs = mt._form_grid_specs(mt._form_grid_positions())
        assert specs[-1][0] == {"colspan": 2}
        assert specs[-1][1] is None

    def test_a_full_row_is_not_widened(self) -> None:
        specs = mt._form_grid_specs(mt._form_grid_positions())
        assert specs[0] == [{}, {}]


class TestFormTrendFigure:
    def test_every_panel_carries_runs_then_a_median_per_surface(
        self, form_trend: pd.DataFrame
    ) -> None:
        fig = mt.build_form_trend_figure(*_form_frames(form_trend))
        assert len(fig.data) == len(am.FORM_METRICS) * len(am.SURFACES) * 2
        assert [t.name for t in fig.data[:4]] == [
            "Outdoor runs", "Treadmill runs", "Outdoor", "Treadmill"
        ]

    def test_the_medians_draw_on_top_of_the_runs(
        self, form_trend: pd.DataFrame
    ) -> None:
        """Later traces paint over earlier ones, so markers must come first."""
        fig = mt.build_form_trend_figure(*_form_frames(form_trend))
        per_panel = len(am.SURFACES) * 2
        for start in range(0, len(fig.data), per_panel):
            panel = fig.data[start:start + per_panel]
            assert [t.mode for t in panel] == [
                "markers", "markers", "lines+markers", "lines+markers"
            ]

    def test_every_easy_run_is_plotted_not_just_the_median(
        self, form_trend: pd.DataFrame
    ) -> None:
        """The whole point of the markers: the spread behind each point."""
        monthly, runs = _form_frames(form_trend)
        fig = mt.build_form_trend_figure(monthly, runs)
        plotted = sum(len(t.x) for t in fig.data if t.mode == "markers")
        assert plotted == len(runs)
        assert plotted > sum(
            len(t.x) for t in fig.data if t.mode == "lines+markers"
        )

    def test_colour_is_the_surface_in_every_panel(
        self, form_trend: pd.DataFrame
    ) -> None:
        """One meaning per channel: the reader learns the key once."""
        fig = mt.build_form_trend_figure(*_form_frames(form_trend))
        for trace in fig.data:
            surface = (
                am.OUTDOOR_SURFACE if trace.name.startswith("Outdoor")
                else am.TREADMILL_SURFACE
            )
            colour = (
                trace.line.color if trace.mode == "lines+markers"
                else trace.marker.color
            )
            assert colour == mt._SURFACE_COLORS[surface]

    def test_runs_are_fainter_and_smaller_than_the_median(
        self, form_trend: pd.DataFrame
    ) -> None:
        """Detail sits behind the summary rather than competing with it."""
        fig = mt.build_form_trend_figure(*_form_frames(form_trend))
        runs, median = fig.data[0], fig.data[2]
        assert runs.marker.opacity < 0.5
        assert runs.marker.size < median.marker.size

    def test_derived_metrics_are_dashed_and_measured_ones_solid(
        self, form_trend: pd.DataFrame
    ) -> None:
        """Dash is the other channel, and it is constant within a panel."""
        fig = mt.build_form_trend_figure(*_form_frames(form_trend))
        medians = iter([t for t in fig.data if t.mode == "lines+markers"])
        for metric in am.FORM_METRICS:
            expected = "solid" if metric.measured else "dash"
            for _ in am.SURFACES:
                assert next(medians).line.dash == expected

    def test_only_the_first_panel_announces_the_surfaces(
        self, form_trend: pd.DataFrame
    ) -> None:
        """Five identical keys would be five times the noise."""
        fig = mt.build_form_trend_figure(*_form_frames(form_trend))
        shown = [t.name for t in fig.data if t.showlegend]
        assert shown == ["Outdoor", "Treadmill"]

    def test_a_runs_trace_shares_its_surfaces_legend_group(
        self, form_trend: pd.DataFrame
    ) -> None:
        """So hiding a surface from the legend hides its runs too."""
        fig = mt.build_form_trend_figure(*_form_frames(form_trend))
        assert fig.data[0].legendgroup == fig.data[2].legendgroup

    def test_it_is_unified_and_keeps_the_unified_hover_rules(
        self, form_trend: pd.DataFrame
    ) -> None:
        """Closest turns this panel into a lottery: both surfaces' medians
        share an x and each is ringed by the runs it summarises."""
        fig = mt.build_form_trend_figure(*_form_frames(form_trend))
        assert fig.layout.hovermode == "x unified"
        for trace in (t for t in fig.data if t.mode == "lines+markers"):
            assert "%{x" not in trace.hovertemplate
            assert "<extra></extra>" not in trace.hovertemplate
            assert trace.xhoverformat == "%B %Y"

    def test_runs_are_not_hoverable_so_a_card_covers_one_granularity(
        self, form_trend: pd.DataFrame
    ) -> None:
        """A run sits on its own date, a median on the first of its month.
        Hoverable, they would share a card headed by only one of the two."""
        fig = mt.build_form_trend_figure(*_form_frames(form_trend))
        for trace in (t for t in fig.data if t.mode == "markers"):
            assert trace.hoverinfo == "skip"

    def test_a_median_hover_reports_its_sample_and_its_spread(
        self, form_trend: pd.DataFrame
    ) -> None:
        """The range is what replaces hovering the individual runs."""
        median = next(t for t in mt.build_form_trend_figure(
            *_form_frames(form_trend)).data if t.mode == "lines+markers")
        assert "median" in median.hovertemplate
        assert "easy runs" in median.hovertemplate
        assert "customdata[1]" in median.hovertemplate
        assert "customdata[2]" in median.hovertemplate

    def test_the_legend_clears_the_first_rows_panel_titles(
        self, form_trend: pd.DataFrame
    ) -> None:
        """Above the plot area is exactly where the panel titles sit."""
        fig = mt.build_form_trend_figure(*_form_frames(form_trend))
        assert fig.layout.legend.y < 0

    def test_it_renders_with_no_data_at_all(self) -> None:
        fig = mt.build_form_trend_figure(pd.DataFrame(), pd.DataFrame())
        assert len(fig.data) == len(am.FORM_METRICS) * len(am.SURFACES) * 2


class TestStrideIsolines:
    def test_the_identity_matches_a_real_recorded_run(self) -> None:
        """9 Sep 2026: 366.4 s/km at 163.6 spm, Garmin reported 100.2 cm."""
        cadence = mt._stride_isoline(100.19, [366.4])[0]
        assert cadence == pytest.approx(163.6, abs=0.5)

    def test_a_longer_stride_needs_a_lower_cadence_at_the_same_pace(self) -> None:
        slow_turnover = mt._stride_isoline(135.0, [300])[0]
        fast_turnover = mt._stride_isoline(90.0, [300])[0]
        assert slow_turnover < fast_turnover


class TestCadencePaceFigure:
    def test_treadmill_runs_are_drawn_hollow_not_dropped(
        self, form_trend: pd.DataFrame
    ) -> None:
        """They belong on the chart, but their implied stride does not hold."""
        fig = mt.build_cadence_pace_figure(form_trend)
        markers = [t for t in fig.data if t.mode == "markers"]
        assert sum(len(t.x) for t in markers) == len(form_trend)
        symbols = [s for t in markers for s in t.marker.symbol]
        assert symbols.count("circle-open") == int(form_trend["is_treadmill"].sum())

    def test_the_hover_names_the_surface(self, form_trend: pd.DataFrame) -> None:
        """Fill encodes it, and fill is invisible to anyone reading the numbers."""
        fig = mt.build_cadence_pace_figure(form_trend)
        markers = [t for t in fig.data if t.mode == "markers"]
        assert all("customdata[2]" in t.hovertemplate for t in markers)
        surfaces = {row[2] for t in markers for row in t.customdata}
        assert surfaces <= {"outdoor", "treadmill"}

    def test_it_stays_closest_because_a_marker_is_the_thing_pointed_at(
        self, form_trend: pd.DataFrame
    ) -> None:
        fig = mt.build_cadence_pace_figure(form_trend)
        assert fig.layout.hovermode == "closest"

    def test_isolines_never_answer_a_hover(self, form_trend: pd.DataFrame) -> None:
        """They are a reference grid, not data; hovering one would be a lie."""
        fig = mt.build_cadence_pace_figure(form_trend)
        guides = [t for t in fig.data if "stride" in (t.name or "")]
        assert len(guides) == len(mt._ISOLINE_STRIDES_CM)
        assert all(t.hoverinfo == "skip" for t in guides)

    def test_the_y_axis_is_clipped_to_the_cadence_actually_run(
        self, form_trend: pd.DataFrame
    ) -> None:
        """Otherwise the isolines fan to 250 spm and flatten every run."""
        fig = mt.build_cadence_pace_figure(form_trend)
        low, high = fig.layout.yaxis.range
        cadence = form_trend["avg_cadence"]
        assert low < cadence.min() and high > cadence.max()
        assert high < 200

    def test_the_legend_sits_below_the_plot(self, form_trend: pd.DataFrame) -> None:
        """Ten traces wrap it over several rows; above, it covers the title."""
        fig = mt.build_cadence_pace_figure(form_trend)
        assert fig.layout.legend.y < 0

    def test_it_renders_with_no_runs(self) -> None:
        assert mt.build_cadence_pace_figure(pd.DataFrame()) is not None


class TestFormCards:
    def test_a_metric_with_no_direction_is_never_coloured(self) -> None:
        """Green would assert a stride change is progress. It is not."""
        stride = next(m for m in am.FORM_METRICS if m.key == "stride_length")
        html = mt._form_delta_html(am.FormHeadline(stride, 120.0, 100.0, runs=3))
        assert "#16a34a" not in html and "#dc2626" not in html

    def test_an_improvement_is_green_and_a_regression_red(self) -> None:
        ratio = next(m for m in am.FORM_METRICS if m.key == "vertical_ratio")
        better = mt._form_delta_html(am.FormHeadline(ratio, 8.0, 8.5, runs=3))
        worse = mt._form_delta_html(am.FormHeadline(ratio, 8.5, 8.0, runs=3))
        assert "#16a34a" in better
        assert "#dc2626" in worse

    def test_a_missing_metric_renders_a_dash_rather_than_a_number(self) -> None:
        headlines = am.form_headline(pd.DataFrame(), _TODAY)
        html = mt._form_cards(headlines)
        assert html.count("—") == len(am.FORM_METRICS)

    def test_the_treadmill_median_is_shown_beside_the_outdoor_one(self) -> None:
        cadence = next(m for m in am.FORM_METRICS if m.key == "cadence")
        html = mt._form_cards(
            [am.FormHeadline(cadence, 163.0, 162.0, runs=4,
                             treadmill_value=161.0, treadmill_runs=2)]
        )
        assert "163.0 spm" in html
        assert "treadmill 161.0 spm" in html
        assert "(2 runs)" in html

    def test_a_card_says_so_when_there_were_no_treadmill_runs(self) -> None:
        cadence = next(m for m in am.FORM_METRICS if m.key == "cadence")
        html = mt._form_cards([am.FormHeadline(cadence, 163.0, 162.0, runs=4)])
        assert "no treadmill runs" in html


def test_layout_allows_the_legend_and_margin_to_be_overridden() -> None:
    assert mt._layout()["legend"]["y"] == 1.01
    assert mt._layout(legend=dict(y=-0.2))["legend"] == {"y": -0.2}
    assert mt._layout(margin=dict(b=104))["margin"] == {"b": 104}


def test_the_section_carries_the_running_form_panels(
    runs: pd.DataFrame, form_trend: pd.DataFrame
) -> None:
    html = mt.metrics_section_html(
        runs, _activities([_activity("2026-06-15")]), _zones(), _TODAY
    )
    assert "Running form" in html
    assert "Running form by month" in html
    assert "Cadence against pace" in html
    # The claims the reader needs in order to know what to trust.
    assert "speed ÷ cadence" in html
    assert "Teal is outdoor, orange is treadmill" in html
    assert "never folded in" in html
