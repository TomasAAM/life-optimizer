"""Tests for the volume, consistency and performance aggregations.

These pin the judgment calls that change the numbers on the metrics tab: what
counts as a run, which clock pace is measured on, how a corrupt distance is
handled, and how a period in progress is compared against the one before it.
Getting any of them silently wrong would still produce a plausible-looking
chart, which is exactly why they are tested rather than eyeballed.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from dashboard import activity_metrics as am


_DEFAULT_PACE_MIN_PER_KM = 5.0


def _activity(
    day: str,
    activity_type: str = "running",
    km: float = 10.0,
    minutes: float | None = None,
    avg_hr: float | None = 140.0,
    moving_minutes: float | None = None,
    name: str = "Run",
) -> dict:
    """Build one ``garmin_activities`` row.

    The duration defaults to a plausible 5:00/km for whatever distance is
    given, so varying the distance alone never trips the implausible-pace
    guard and quietly drops the row from an assertion.
    """
    if minutes is None:
        minutes = km * _DEFAULT_PACE_MIN_PER_KM
    seconds = minutes * 60.0
    moving = seconds if moving_minutes is None else moving_minutes * 60.0
    return {
        "start_time_local": f"{day}T07:00:00",
        "activity_name": name,
        "activity_type": activity_type,
        "training_load": 50.0,
        "is_multisport": False,
        "distance_m": km * 1000.0,
        "duration_s": seconds,
        "moving_duration_s": moving,
        "elevation_gain_m": None,
        "avg_hr": avg_hr,
        "max_hr": None if avg_hr is None else avg_hr + 20,
    }


def _activities(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _zones() -> pd.DataFrame:
    """The lactate zone table, shaped like the real one (open first/last bound)."""
    return pd.DataFrame(
        [
            {"zone_index": 1, "zone_name": "Recovery", "hr_low": None, "hr_high": 139.0},
            {"zone_index": 2, "zone_name": "Endurance", "hr_low": 139.0, "hr_high": 147.0},
            {"zone_index": 3, "zone_name": "Tempo", "hr_low": 147.0, "hr_high": 155.0},
            {"zone_index": 4, "zone_name": "Threshold", "hr_low": 155.0, "hr_high": 163.0},
            {"zone_index": 5, "zone_name": "VO2max", "hr_low": 163.0, "hr_high": None},
        ]
    )


# --- what counts as a run -------------------------------------------------


def test_only_running_and_treadmill_count_as_runs() -> None:
    runs = am.prepare_runs(
        _activities(
            [
                _activity("2026-08-03"),
                _activity("2026-08-04", activity_type="treadmill_running"),
                _activity("2026-08-05", activity_type="multi_sport"),
                _activity("2026-08-06", activity_type="strength_training"),
                _activity("2026-08-07", activity_type="hiit"),
            ]
        )
    )
    assert len(runs) == 2
    assert runs["is_treadmill"].tolist() == [False, True]


def test_pace_uses_moving_time_but_falls_back_to_elapsed_when_it_is_zero() -> None:
    runs = am.prepare_runs(
        _activities(
            [
                _activity("2026-08-03", km=10.0, minutes=60.0, moving_minutes=50.0),
                _activity("2026-08-04", km=10.0, minutes=50.0, moving_minutes=0.0),
            ]
        )
    )
    # 50 minutes over 10 km either way: moving time in the first, elapsed in
    # the second because the recorded moving time is unusable.
    assert runs["pace_s_km"].round(1).tolist() == [300.0, 300.0]


def test_empty_input_yields_an_empty_frame_with_the_expected_columns() -> None:
    runs = am.prepare_runs(pd.DataFrame())
    assert runs.empty
    assert "pace_s_km" in runs.columns and "implausible" in runs.columns


# --- corrupt distances ----------------------------------------------------


def test_a_corrupt_distance_is_flagged_not_dropped() -> None:
    runs = am.prepare_runs(
        _activities(
            [
                _activity("2026-08-03"),
                # 13.7 km in 19.5 minutes: a treadmill distance glitch.
                _activity("2026-08-04", km=13.7, minutes=19.5, name="Tempo"),
            ]
        )
    )
    assert len(runs) == 2
    assert runs["implausible"].tolist() == [False, True]
    assert len(am.valid_runs(runs)) == 1


def test_a_zero_distance_run_is_implausible_rather_than_infinite() -> None:
    runs = am.prepare_runs(_activities([_activity("2026-08-03", km=0.0)]))
    assert bool(runs.loc[0, "implausible"]) is True


def test_headline_excludes_corrupt_runs_but_reports_how_many() -> None:
    runs = am.prepare_runs(
        _activities(
            [
                _activity("2026-09-01", km=10.0),
                _activity("2026-09-02", km=13.7, minutes=19.5),
            ]
        )
    )
    headline = am.volume_headline(runs, date(2026, 9, 2))
    assert headline.km_week == 10.0
    assert headline.excluded_runs == 1
    assert headline.runs_total == 1


# --- volume aggregation ---------------------------------------------------


def test_a_week_without_running_is_a_zero_not_a_missing_row() -> None:
    runs = am.prepare_runs(
        _activities([_activity("2026-08-03"), _activity("2026-08-17")])
    )
    weekly = am.volume_by_period(runs, "week")
    assert weekly["period_start"].dt.date.tolist() == [
        date(2026, 8, 3), date(2026, 8, 10), date(2026, 8, 17)
    ]
    assert weekly["km"].tolist() == [10.0, 0.0, 10.0]
    assert weekly["runs"].tolist() == [1, 0, 1]


def test_volume_extends_to_the_current_period_even_with_no_runs_in_it() -> None:
    runs = am.prepare_runs(_activities([_activity("2026-08-03")]))
    weekly = am.volume_by_period(runs, "week", through=date(2026, 8, 19))
    assert weekly["period_start"].dt.date.tolist()[-1] == date(2026, 8, 17)
    assert weekly["km"].tolist()[-1] == 0.0


def test_weeks_start_on_monday() -> None:
    # 2026-08-09 is a Sunday; it belongs to the week starting Monday the 3rd.
    runs = am.prepare_runs(_activities([_activity("2026-08-09")]))
    weekly = am.volume_by_period(runs, "week")
    assert weekly.loc[0, "period_start"].date() == date(2026, 8, 3)


def test_months_and_years_aggregate_the_same_runs() -> None:
    runs = am.prepare_runs(
        _activities(
            [_activity("2026-03-15"), _activity("2026-04-20"), _activity("2026-04-25")]
        )
    )
    monthly = am.volume_by_period(runs, "month")
    yearly = am.volume_by_period(runs, "year")
    assert monthly["km"].tolist() == [10.0, 20.0]
    assert yearly["km"].tolist() == [30.0]
    assert yearly["runs"].tolist() == [3]


def test_moving_time_is_reported_in_hours() -> None:
    runs = am.prepare_runs(_activities([_activity("2026-08-03", minutes=90.0)]))
    assert am.volume_by_period(runs, "week").loc[0, "hours"] == 1.5


# --- like-for-like period comparisons -------------------------------------


def test_the_prior_week_is_measured_over_the_same_elapsed_days() -> None:
    # Wednesday 2 September. The prior window is Mon-Wed of the week before,
    # so the previous Friday's long run must not inflate the comparison.
    runs = am.prepare_runs(
        _activities(
            [
                _activity("2026-08-31", km=5.0),   # this week, Monday
                _activity("2026-08-24", km=8.0),   # last week, Monday
                _activity("2026-08-28", km=20.0),  # last week, Friday - outside
            ]
        )
    )
    headline = am.volume_headline(runs, date(2026, 9, 2))
    assert headline.km_week == 5.0
    assert headline.km_week_prior == 8.0
    assert headline.week_delta == -3.0


def test_the_prior_month_window_clamps_to_a_shorter_month() -> None:
    # 31 March has no counterpart in February; the window stops at the 28th.
    runs = am.prepare_runs(
        _activities([_activity("2026-02-28", km=7.0), _activity("2026-03-05", km=4.0)])
    )
    headline = am.volume_headline(runs, date(2026, 3, 31))
    assert headline.km_month == 4.0
    assert headline.km_month_prior == 7.0


def test_year_to_date_ignores_a_prior_year() -> None:
    runs = am.prepare_runs(
        _activities([_activity("2025-12-30", km=9.0), _activity("2026-01-05", km=4.0)])
    )
    headline = am.volume_headline(runs, date(2026, 9, 2))
    assert headline.km_year == 4.0
    assert headline.km_total == 13.0


# --- consistency ----------------------------------------------------------


def test_a_streak_counts_every_discipline_not_just_running() -> None:
    activities = _activities(
        [
            _activity("2026-08-31", activity_type="strength_training"),
            _activity("2026-09-01", activity_type="hiit"),
            _activity("2026-09-02"),
        ]
    )
    runs = am.prepare_runs(activities)
    assert am.consistency(activities, runs, date(2026, 9, 2)).current_streak == 3


def test_a_streak_is_not_broken_by_a_today_that_has_not_happened_yet() -> None:
    activities = _activities([_activity("2026-08-31"), _activity("2026-09-01")])
    runs = am.prepare_runs(activities)
    summary = am.consistency(activities, runs, date(2026, 9, 2))
    assert summary.current_streak == 2
    assert summary.days_since_last_run == 1


def test_a_two_day_gap_does_break_the_streak() -> None:
    activities = _activities([_activity("2026-08-30"), _activity("2026-08-31")])
    runs = am.prepare_runs(activities)
    assert am.consistency(activities, runs, date(2026, 9, 2)).current_streak == 0


def test_longest_streak_survives_later_gaps() -> None:
    activities = _activities(
        [_activity(d) for d in ("2026-08-01", "2026-08-02", "2026-08-03", "2026-08-20")]
    )
    runs = am.prepare_runs(activities)
    summary = am.consistency(activities, runs, date(2026, 9, 2))
    assert summary.longest_streak == 3
    assert summary.current_streak == 0


def test_training_days_counts_distinct_days_inside_the_28_day_window() -> None:
    activities = _activities(
        [
            _activity("2026-09-01"),
            _activity("2026-09-01", activity_type="strength_training"),
            _activity("2026-07-01"),  # outside the window
        ]
    )
    runs = am.prepare_runs(activities)
    summary = am.consistency(activities, runs, date(2026, 9, 2))
    assert summary.training_days_28 == 1
    assert summary.rest_days_28 == 27


# --- calendar -------------------------------------------------------------


def test_the_calendar_fills_rest_days_with_zero_through_today() -> None:
    runs = am.prepare_runs(_activities([_activity("2026-08-31", km=12.0)]))
    calendar = am.daily_distance(runs, date(2026, 9, 2))
    assert len(calendar) == 3
    assert calendar["km"].tolist() == [12.0, 0.0, 0.0]
    assert calendar["weekday"].tolist() == [0, 1, 2]


# --- zone assignment ------------------------------------------------------


def test_zone_bounds_are_lower_inclusive_and_upper_exclusive() -> None:
    runs = am.prepare_runs(
        _activities(
            [_activity(f"2026-08-{d:02d}", avg_hr=hr) for d, hr in
             enumerate([138, 139, 147, 155, 163], start=3)]
        )
    )
    zones = am.assign_zones(runs, _zones())
    assert zones.tolist() == [
        "Recovery", "Endurance", "Tempo", "Threshold", "VO2max"
    ]


def test_the_open_ended_zones_absorb_the_extremes() -> None:
    runs = am.prepare_runs(
        _activities(
            [_activity("2026-08-03", avg_hr=90.0), _activity("2026-08-04", avg_hr=200.0)]
        )
    )
    assert am.assign_zones(runs, _zones()).tolist() == ["Recovery", "VO2max"]


def test_a_run_without_a_heart_rate_gets_no_zone() -> None:
    runs = am.prepare_runs(_activities([_activity("2026-08-03", avg_hr=None)]))
    assert pd.isna(am.assign_zones(runs, _zones()).iloc[0])


def test_zones_are_absent_when_no_zone_table_exists() -> None:
    runs = am.prepare_runs(_activities([_activity("2026-08-03")]))
    assert am.assign_zones(runs, pd.DataFrame()).isna().all()


# --- performance trend ----------------------------------------------------


def test_the_easy_pace_trend_ignores_hard_runs_and_the_treadmill() -> None:
    runs = am.prepare_runs(
        _activities(
            [
                _activity("2026-08-03", km=10.0, minutes=50.0, avg_hr=140.0),
                _activity("2026-08-05", km=10.0, minutes=40.0, avg_hr=160.0),
                _activity(
                    "2026-08-07", activity_type="treadmill_running",
                    km=10.0, minutes=45.0, avg_hr=140.0,
                ),
            ]
        )
    )
    trend = am.pace_trend(runs, _zones())
    assert len(trend) == 3  # every run is plotted...

    monthly = am.monthly_easy_pace(trend)
    assert len(monthly) == 1
    assert monthly.loc[0, "runs"] == 1  # ...but only the easy outdoor one is averaged
    assert monthly.loc[0, "pace_s_km"] == 300.0


def test_efficiency_rises_when_the_same_heart_rate_buys_more_speed() -> None:
    runs = am.prepare_runs(
        _activities(
            [
                _activity("2026-07-10", km=10.0, minutes=60.0, avg_hr=140.0),
                _activity("2026-08-10", km=10.0, minutes=50.0, avg_hr=140.0),
            ]
        )
    )
    efficiency = am.aerobic_efficiency(am.pace_trend(runs, _zones()))
    assert len(efficiency) == 2
    assert efficiency.loc[1, "efficiency"] > efficiency.loc[0, "efficiency"]


def test_the_trend_drops_corrupt_runs() -> None:
    runs = am.prepare_runs(
        _activities(
            [_activity("2026-08-03"), _activity("2026-08-04", km=13.7, minutes=19.5)]
        )
    )
    assert len(am.pace_trend(runs, _zones())) == 1


def test_performance_series_are_empty_when_there_is_nothing_to_plot() -> None:
    empty = am.prepare_runs(pd.DataFrame())
    trend = am.pace_trend(empty, _zones())
    assert trend.empty
    assert am.monthly_easy_pace(trend).empty
    assert am.aerobic_efficiency(trend).empty
    assert am.volume_by_period(empty, "week").empty
    assert am.daily_distance(empty, date(2026, 9, 2)).empty
