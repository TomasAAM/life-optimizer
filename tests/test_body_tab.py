"""Tests for the body-composition tab's figures and fragment.

The hover assertions carry over the 2026-09-08 finding: a multi-series time
series under ``hovermode="closest"`` answers with the nearest *point* rather
than the reading being pointed at, and unified hover forbids ``%{x}`` in a
template body and ``<extra></extra>`` entirely. Both figures here are
multi-series time series, so both are subject to it -- and a wrong hover is
invisible in a screenshot, which is why it is pinned rather than eyeballed.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from dashboard import body_metrics as bm
from dashboard import body_tab as bt
from plan import config


_TODAY = date(2026, 9, 9)


def _raw(rows: list[tuple[str, float, float | None]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "measured_at_local": stamp,
                "weight_kg": weight,
                "body_fat_pct": fat,
                "lean_mass_kg": None,
                "bone_mass_kg": None,
                "body_water_kg": None,
                "source": "cn.fitdays.fitdays",
            }
            for stamp, weight, fat in rows
        ]
    )


@pytest.fixture(name="body")
def _body() -> pd.DataFrame:
    """Four weekly fasted-morning weigh-ins on a gentle downward trend."""
    return _raw(
        [
            ("2026-08-18 07:05", 82.4, 19.1),
            ("2026-08-25 07:10", 82.0, 18.9),
            ("2026-09-01 07:02", 81.6, 18.6),
            ("2026-09-08 07:12", 81.3, 18.4),
        ]
    )


@pytest.fixture(name="weigh_ins")
def _weigh_ins(body: pd.DataFrame) -> pd.DataFrame:
    return bm.prepare_weigh_ins(body)


def _hovertemplates(fig) -> list[str]:
    return [t.hovertemplate for t in fig.data if t.hovertemplate]


class TestHoverContract:
    """Both figures are multi-series time series, so both go unified."""

    def test_layout_defaults_to_unified_and_accepts_an_override(self) -> None:
        assert bt._layout()["hovermode"] == "x unified"
        assert bt._layout(hovermode="closest")["hovermode"] == "closest"

    def test_weight_figure_is_unified(self, weigh_ins: pd.DataFrame) -> None:
        fig = bt.build_weight_figure(weigh_ins)
        assert fig.layout.hovermode == "x unified"

    def test_composition_figure_is_unified(self, weigh_ins: pd.DataFrame) -> None:
        fig = bt.build_composition_figure(bm.composition_series(weigh_ins))
        assert fig.layout.hovermode == "x unified"

    @pytest.mark.parametrize("builder", ["weight", "composition"])
    def test_no_template_carries_an_extra_tag(
        self, weigh_ins: pd.DataFrame, builder: str
    ) -> None:
        """Under unified hover the trace name labels the row, so an ``extra``
        block would blank the label it depends on."""
        fig = (
            bt.build_weight_figure(weigh_ins)
            if builder == "weight"
            else bt.build_composition_figure(bm.composition_series(weigh_ins))
        )
        for template in _hovertemplates(fig):
            assert "<extra>" not in template

    @pytest.mark.parametrize("builder", ["weight", "composition"])
    def test_no_template_repeats_the_timestamp(
        self, weigh_ins: pd.DataFrame, builder: str
    ) -> None:
        """The instant already heads the unified card; repeating it per row is
        the defect fixed on the training-load chart on 2026-09-09."""
        fig = (
            bt.build_weight_figure(weigh_ins)
            if builder == "weight"
            else bt.build_composition_figure(bm.composition_series(weigh_ins))
        )
        for template in _hovertemplates(fig):
            assert "%{x" not in template

    def test_every_trace_declares_the_clock_in_its_hover_header(
        self, weigh_ins: pd.DataFrame
    ) -> None:
        """Time of day is what says whether a reading was on protocol, so the
        header must carry it rather than only the date."""
        fig = bt.build_weight_figure(weigh_ins)
        for trace in fig.data:
            assert trace.xhoverformat == bt._HOVER_STAMP


class TestWeightFigure:
    def test_draws_readings_and_a_trend(self, weigh_ins: pd.DataFrame) -> None:
        fig = bt.build_weight_figure(weigh_ins)
        assert len(fig.data) == 2
        assert fig.data[0].mode == "markers"
        assert fig.data[1].mode == "lines"

    def test_the_axis_is_not_zero_based(self, weigh_ins: pd.DataFrame) -> None:
        """A zero-based axis flattens a narrow-band quantity into a flat line."""
        fig = bt.build_weight_figure(weigh_ins)
        assert fig.layout.yaxis.rangemode != "tozero"

    def test_renders_with_no_data(self) -> None:
        fig = bt.build_weight_figure(bm.prepare_weigh_ins(pd.DataFrame()))
        assert fig.data == ()


class TestCompositionFigure:
    def test_draws_a_panel_per_series(self, weigh_ins: pd.DataFrame) -> None:
        fig = bt.build_composition_figure(bm.composition_series(weigh_ins))
        assert len(fig.data) == 2
        assert [t.name for t in fig.data] == ["Fat mass", "Lean mass"]

    def test_panels_are_not_stacked(self, weigh_ins: pd.DataFrame) -> None:
        """Stacked on one zero-based axis, a real 1 kg shift in fat is a sliver
        and both series read as flat."""
        fig = bt.build_composition_figure(bm.composition_series(weigh_ins))
        assert all(t.stackgroup is None for t in fig.data)

    def test_each_series_lands_on_its_own_axis(
        self, weigh_ins: pd.DataFrame
    ) -> None:
        """The bug this pins: the 1x2 grid was built but ``add_trace`` was
        called without ``row``/``col``, so both series shared one axis and the
        fat panel was flattened by lean mass -- the exact defect the small
        multiples exist to avoid. Asserting the axes rather than the layout,
        because the empty ``yaxis2`` a subplot grid creates looks correct on
        its own.
        """
        fig = bt.build_composition_figure(bm.composition_series(weigh_ins))
        assert [t.yaxis for t in fig.data] == ["y", "y2"]
        assert [t.xaxis for t in fig.data] == ["x", "x2"]

    def test_neither_panel_is_zero_based(self, weigh_ins: pd.DataFrame) -> None:
        fig = bt.build_composition_figure(bm.composition_series(weigh_ins))
        assert fig.layout.yaxis.rangemode != "tozero"
        assert fig.layout.yaxis2.rangemode != "tozero"

    def test_both_series_are_dashed_because_the_split_is_derived(
        self, weigh_ins: pd.DataFrame
    ) -> None:
        fig = bt.build_composition_figure(bm.composition_series(weigh_ins))
        assert all(t.line.dash == "dash" for t in fig.data)

    def test_renders_with_no_composition_data(self) -> None:
        fig = bt.build_composition_figure(pd.DataFrame())
        assert fig.data == ()


class TestFragment:
    def test_empty_state_says_how_to_switch_the_feed_on(self) -> None:
        html = bt.body_section_html(pd.DataFrame(), _TODAY)
        assert "BODY_SHEET_CSV_URL" in html
        assert "Health Connect" in html

    def test_renders_cards_charts_and_caveats(self, body: pd.DataFrame) -> None:
        html = bt.body_section_html(body, _TODAY)
        assert "Weight (trend)" in html
        assert "Rate of change" in html
        assert "Relative strength" in html
        assert "plotly" in html.lower()

    def test_states_that_the_split_is_derived(self, body: pd.DataFrame) -> None:
        html = bt.body_section_html(body, _TODAY)
        assert "derived, not measured" in html

    def test_explains_the_metrics_health_connect_drops(
        self, body: pd.DataFrame
    ) -> None:
        html = bt.body_section_html(body, _TODAY)
        assert "visceral fat" in html
        assert "metabolic age" in html

    def test_says_when_no_reading_carries_body_fat(self) -> None:
        html = bt.body_section_html(_raw([("2026-09-08 07:12", 81.3, None)]), _TODAY)
        assert "no fat/lean split" in html

    def test_flags_an_off_protocol_reading(self) -> None:
        html = bt.body_section_html(
            _raw([("2026-09-08 21:40", 82.9, 18.4)]), _TODAY
        )
        assert "off the fasted-morning" in html

    def test_stays_quiet_when_every_reading_is_on_protocol(
        self, body: pd.DataFrame
    ) -> None:
        html = bt.body_section_html(body, _TODAY)
        assert "off the fasted-morning" not in html


class TestConfigCallout:
    def test_warns_when_the_plan_constant_has_drifted(self) -> None:
        drifted = config.ATHLETE_BODYWEIGHT_KG + 7.0
        html = bt.body_section_html(
            _raw([("2026-09-08 07:12", drifted, 18.4)]), _TODAY
        )
        assert "BENCHMARKS.md" in html
        assert "ATHLETE_BODYWEIGHT_KG" in html

    def test_silent_when_the_constant_matches_the_measurement(self) -> None:
        html = bt.body_section_html(
            _raw([("2026-09-08 07:12", config.ATHLETE_BODYWEIGHT_KG, 18.4)]),
            _TODAY,
        )
        assert "ATHLETE_BODYWEIGHT_KG" not in html
