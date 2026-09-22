"""Tests for the bodyweight and body-composition aggregations.

The rules pinned here are the ones that decide what the tab is allowed to
claim: that the fat/lean split is derived from weight rather than read from a
second record, that a rate of change is refused when too little data stands
behind it, and that relative strength is computed only from loads recorded as
an unambiguous total.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from dashboard import body_metrics as bm
from plan import config


_TODAY = date(2026, 9, 9)


def _row(stamp: str, weight: float, fat: float | None = None) -> dict:
    """One raw ``body_composition`` row."""
    return {
        "measured_at_local": stamp,
        "weight_kg": weight,
        "body_fat_pct": fat,
        "lean_mass_kg": None,
        "bone_mass_kg": None,
        "body_water_kg": None,
        "source": "cn.fitdays.fitdays",
    }


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _ramp(days: int, start_kg: float, kg_per_week: float) -> pd.DataFrame:
    """A weigh-in every other day on an exact linear trend."""
    rows = []
    for offset in range(0, days + 1, 2):
        stamp = date(2026, 9, 9) - timedelta(days=days - offset)
        weight = start_kg + kg_per_week * (offset / 7.0)
        rows.append(_row(f"{stamp.isoformat()} 07:00", round(weight, 3), 18.0))
    return bm.prepare_weigh_ins(_frame(rows))


class TestPrepareWeighIns:
    def test_empty_in_empty_out(self) -> None:
        assert bm.prepare_weigh_ins(pd.DataFrame()).empty

    def test_fat_and_lean_sum_to_the_weight(self) -> None:
        """Both are derived from weight, so they must reconcile exactly -- a
        reported lean mass comes from a separate record and need not."""
        out = bm.prepare_weigh_ins(_frame([_row("2026-09-08 07:12", 80.0, 20.0)]))
        assert out["fat_mass_kg"].iloc[0] == pytest.approx(16.0)
        assert out["lean_mass_kg"].iloc[0] == pytest.approx(64.0)
        total = out["fat_mass_kg"].iloc[0] + out["lean_mass_kg"].iloc[0]
        assert total == pytest.approx(80.0)

    def test_a_reading_without_body_fat_keeps_its_weight(self) -> None:
        out = bm.prepare_weigh_ins(_frame([_row("2026-09-08 07:12", 80.0, None)]))
        assert out["weight_kg"].iloc[0] == 80.0
        assert pd.isna(out["fat_mass_kg"].iloc[0])

    def test_morning_readings_are_on_protocol_and_evening_ones_are_not(self) -> None:
        out = bm.prepare_weigh_ins(
            _frame([
                _row("2026-09-08 07:12", 80.0),
                _row("2026-09-09 19:40", 81.5),
            ])
        )
        assert list(out["off_protocol"]) == [False, True]

    def test_the_boundary_hour_counts_as_off_protocol(self) -> None:
        out = bm.prepare_weigh_ins(_frame([_row("2026-09-08 10:00", 80.0)]))
        assert bool(out["off_protocol"].iloc[0]) is True

    def test_an_offset_timestamp_keeps_its_wall_clock(self) -> None:
        """The defect this pins: normalising to UTC moved a Santiago 07:12
        fasted-morning weigh-in to 10:12 and flagged it off-protocol, which
        would have mislabelled nearly every correctly taken reading."""
        out = bm.prepare_weigh_ins(
            _frame([_row("2026-09-08T07:12:00-03:00", 81.4, 18.2)])
        )
        assert out["hour"].iloc[0] == 7
        assert bool(out["off_protocol"].iloc[0]) is False

    def test_a_naive_timestamp_is_taken_at_face_value(self) -> None:
        out = bm.prepare_weigh_ins(_frame([_row("2026-09-08 07:12:00", 81.4, 18.2)]))
        assert out["hour"].iloc[0] == 7

    def test_rows_are_sorted_chronologically(self) -> None:
        out = bm.prepare_weigh_ins(
            _frame([
                _row("2026-09-08 07:00", 81.0),
                _row("2026-09-01 07:00", 82.0),
            ])
        )
        assert list(out["weight_kg"]) == [82.0, 81.0]


class TestTrendSeries:
    def test_a_single_reading_is_its_own_trend(self) -> None:
        weigh_ins = bm.prepare_weigh_ins(_frame([_row("2026-09-08 07:00", 80.0)]))
        trend = bm.trend_series(weigh_ins)
        assert trend["trend_kg"].iloc[0] == pytest.approx(80.0)

    def test_the_window_averages_readings_inside_it(self) -> None:
        weigh_ins = bm.prepare_weigh_ins(
            _frame([
                _row("2026-09-01 07:00", 80.0),
                _row("2026-09-08 07:00", 82.0),
            ])
        )
        trend = bm.trend_series(weigh_ins, window_days=14)
        assert trend["trend_kg"].iloc[-1] == pytest.approx(81.0)

    def test_readings_outside_the_window_drop_out(self) -> None:
        weigh_ins = bm.prepare_weigh_ins(
            _frame([
                _row("2026-07-01 07:00", 90.0),
                _row("2026-09-08 07:00", 80.0),
            ])
        )
        trend = bm.trend_series(weigh_ins, window_days=14)
        assert trend["trend_kg"].iloc[-1] == pytest.approx(80.0)


class TestRateOfChange:
    def test_recovers_a_known_slope(self) -> None:
        weigh_ins = _ramp(days=28, start_kg=84.0, kg_per_week=-0.5)
        assert bm.rate_kg_per_week(weigh_ins, _TODAY) == pytest.approx(-0.5, abs=0.01)

    def test_gaining_reads_positive(self) -> None:
        weigh_ins = _ramp(days=28, start_kg=78.0, kg_per_week=0.3)
        assert bm.rate_kg_per_week(weigh_ins, _TODAY) == pytest.approx(0.3, abs=0.01)

    def test_refused_below_three_readings(self) -> None:
        weigh_ins = bm.prepare_weigh_ins(
            _frame([
                _row("2026-09-01 07:00", 82.0),
                _row("2026-09-08 07:00", 80.0),
            ])
        )
        assert bm.rate_kg_per_week(weigh_ins, _TODAY) is None

    def test_refused_when_the_readings_span_under_a_week(self) -> None:
        """Three readings over two days would otherwise report a slope of
        several kilograms a week from pure hydration noise."""
        weigh_ins = bm.prepare_weigh_ins(
            _frame([
                _row("2026-09-07 07:00", 82.0),
                _row("2026-09-08 07:00", 81.0),
                _row("2026-09-09 07:00", 80.0),
            ])
        )
        assert bm.rate_kg_per_week(weigh_ins, _TODAY) is None

    def test_refused_with_no_readings(self) -> None:
        assert bm.rate_kg_per_week(bm.prepare_weigh_ins(pd.DataFrame()), _TODAY) is None


class TestHeadline:
    def test_no_data_yields_an_all_none_headline(self) -> None:
        headline = bm.headline(bm.prepare_weigh_ins(pd.DataFrame()), _TODAY)
        assert headline.readings == 0
        assert headline.trend_weight_kg is None
        assert headline.rate_kg_week is None

    def test_counts_readings_and_protocol_breaches(self) -> None:
        weigh_ins = bm.prepare_weigh_ins(
            _frame([
                _row("2026-09-01 07:00", 82.0, 18.0),
                _row("2026-09-08 21:00", 81.0, 17.8),
            ])
        )
        headline = bm.headline(weigh_ins, _TODAY)
        assert headline.readings == 2
        assert headline.off_protocol == 1

    def test_delta_is_withheld_when_the_series_is_too_short(self) -> None:
        weigh_ins = bm.prepare_weigh_ins(_frame([_row("2026-09-08 07:00", 80.0)]))
        assert bm.headline(weigh_ins, _TODAY).delta_kg is None

    def test_delta_measures_the_trend_not_the_raw_readings(self) -> None:
        weigh_ins = _ramp(days=56, start_kg=84.0, kg_per_week=-0.5)
        headline = bm.headline(weigh_ins, _TODAY)
        assert headline.delta_kg is not None
        assert headline.delta_kg < 0

    def test_latest_reading_is_reported_alongside_the_trend(self) -> None:
        weigh_ins = bm.prepare_weigh_ins(
            _frame([
                _row("2026-09-01 07:00", 80.0, 18.0),
                _row("2026-09-08 07:00", 84.0, 19.0),
            ])
        )
        headline = bm.headline(weigh_ins, _TODAY)
        assert headline.latest_weight_kg == 84.0
        # The trend damps the jump rather than following it.
        assert headline.trend_weight_kg == pytest.approx(82.0)


class TestCompositionSeries:
    def test_keeps_only_readings_with_an_impedance_estimate(self) -> None:
        weigh_ins = bm.prepare_weigh_ins(
            _frame([
                _row("2026-09-01 07:00", 82.0, 18.0),
                _row("2026-09-08 07:00", 81.0, None),
            ])
        )
        assert len(bm.composition_series(weigh_ins)) == 1

    def test_empty_when_nothing_carries_body_fat(self) -> None:
        weigh_ins = bm.prepare_weigh_ins(_frame([_row("2026-09-08 07:00", 81.0)]))
        assert bm.composition_series(weigh_ins).empty


class TestRelativeStrength:
    def test_parses_a_leading_total_load(self) -> None:
        assert bm.parse_load_kg("130 kg for top triples @ RPE 8") == 130.0

    def test_refuses_a_bodyweight_referenced_prescription(self) -> None:
        assert bm.parse_load_kg("bodyweight +5 kg for sets of 4 @ RPE 8") is None

    def test_refuses_a_per_hand_prescription(self) -> None:
        assert bm.parse_load_kg("2x32 kg per hand (70 lb) for 4-6 reps") is None

    def test_ratios_divide_the_recorded_load_by_bodyweight(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Pinned so the test does not move every time the live config is updated.
        monkeypatch.setitem(
            config.ATHLETE_LOADS, "back_squat", "100 kg for triples @ RPE ~8"
        )
        monkeypatch.setitem(
            config.ATHLETE_LOADS, "trap_bar_deadlift", "130 kg for top triples @ RPE 8"
        )
        ratios = {r.lift: r for r in bm.relative_strength(80.0)}
        assert ratios["back_squat"].load_kg == 100.0
        assert ratios["back_squat"].ratio == pytest.approx(1.25)
        assert ratios["trap_bar_deadlift"].ratio == pytest.approx(130.0 / 80.0)

    def test_only_the_unambiguous_lifts_appear(self) -> None:
        lifts = {r.lift for r in bm.relative_strength(80.0)}
        assert lifts == set(bm.RELATIVE_STRENGTH_LIFTS)
        assert "pull_up" not in lifts
        assert "dumbbell_bench_press" not in lifts

    def test_every_listed_lift_still_exists_in_the_plan_config(self) -> None:
        """Guards against a rename in plan.config silently emptying the panel."""
        for lift in bm.RELATIVE_STRENGTH_LIFTS:
            assert lift in config.ATHLETE_LOADS

    def test_no_weight_means_no_ratios(self) -> None:
        assert bm.relative_strength(None) == []
        assert bm.relative_strength(0.0) == []


class TestConfigDisagreement:
    def test_reports_the_gap_against_the_plan_constant(self) -> None:
        gap = bm.config_weight_disagreement(config.ATHLETE_BODYWEIGHT_KG + 7.0)
        assert gap == pytest.approx(7.0)

    def test_none_without_a_measurement(self) -> None:
        assert bm.config_weight_disagreement(None) is None
