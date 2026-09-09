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
    cadence: float | None = 163.0,
    stride_cm: float | None = 105.0,
    vertical_oscillation_cm: float | None = 9.2,
    vertical_ratio_pct: float | None = 8.6,
    ground_contact_ms: float | None = 270.0,
) -> dict:
    """Build one ``garmin_activities`` row.

    The duration defaults to a plausible 5:00/km for whatever distance is
    given, so varying the distance alone never trips the implausible-pace
    guard and quietly drops the row from an assertion. The running-dynamics
    defaults are likewise mid-range for this athlete, so a test that cares
    about one of them can vary it alone.
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
        "avg_cadence": cadence,
        "avg_stride_length_cm": stride_cm,
        "avg_vertical_oscillation_cm": vertical_oscillation_cm,
        "avg_vertical_ratio_pct": vertical_ratio_pct,
        "avg_ground_contact_time_ms": ground_contact_ms,
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


# --- Running dynamics -------------------------------------------------------
#
# The judgment calls pinned here are the ones that would still draw a
# convincing chart if they were wrong: which surface each metric may count,
# that trends see easy runs only, and that a change is called an improvement
# only when the metric has a direction to improve in.


def _easy_run(day: str, **kwargs) -> dict:
    """An easy-zone run -- HR 130 falls in Recovery for :func:`_zones`."""
    return _activity(day, avg_hr=130.0, **kwargs)


def test_prepare_runs_carries_every_running_dynamics_column() -> None:
    runs = am.prepare_runs(_activities([_activity("2026-03-02", cadence=170.0)]))
    for column in am.FORM_COLUMNS:
        assert column in runs.columns
    assert runs["avg_cadence"].iloc[0] == 170.0


def test_prepare_runs_survives_a_frame_predating_the_dynamics_columns() -> None:
    """A frame assembled before the columns existed must not raise."""
    frame = _activities([_activity("2026-03-02")]).drop(columns=list(am.FORM_COLUMNS))
    runs = am.prepare_runs(frame)
    for column in am.FORM_COLUMNS:
        assert column in runs.columns
        assert runs[column].isna().all()


def test_every_metric_is_sampled_on_both_surfaces_separately() -> None:
    """Surface is a dimension now, not a filter -- no metric drops belt runs."""
    trend = am.pace_trend(
        am.prepare_runs(
            _activities(
                [
                    _easy_run("2026-03-02"),
                    _easy_run("2026-03-03", activity_type="treadmill_running"),
                ]
            )
        ),
        _zones(),
    )
    for metric in am.FORM_METRICS:
        assert len(am._metric_sample(trend, metric)) == 2
        assert len(am._metric_sample(trend, metric, am.OUTDOOR_SURFACE)) == 1
        assert len(am._metric_sample(trend, metric, am.TREADMILL_SURFACE)) == 1


def test_monthly_form_metrics_uses_easy_runs_only() -> None:
    """A hard session must not move the series -- every metric tracks pace."""
    trend = am.pace_trend(
        am.prepare_runs(
            _activities(
                [
                    _easy_run("2026-03-02", cadence=160.0),
                    _easy_run("2026-03-09", cadence=164.0),
                    # HR 170 is VO2max: excluded despite the extreme cadence.
                    _activity("2026-03-16", avg_hr=170.0, cadence=200.0),
                ]
            )
        ),
        _zones(),
    )
    cadence = am.monthly_form_metrics(trend).query(
        "metric == 'cadence' and surface == 'outdoor'"
    )
    assert len(cadence) == 1
    assert cadence["value"].iloc[0] == 162.0
    assert cadence["runs"].iloc[0] == 2


def test_monthly_form_metrics_is_long_format_over_every_metric() -> None:
    trend = am.pace_trend(
        am.prepare_runs(_activities([_easy_run("2026-03-02")])), _zones()
    )
    monthly = am.monthly_form_metrics(trend)
    assert list(monthly.columns) == [
        "metric", "surface", "month_start", "value", "low", "high", "runs"
    ]
    assert set(monthly["metric"]) == {m.key for m in am.FORM_METRICS}
    assert set(monthly["surface"]) == {am.OUTDOOR_SURFACE}


def test_monthly_form_metrics_omits_a_surface_with_no_runs() -> None:
    """Treadmill-only easy running leaves no outdoor series to draw."""
    trend = am.pace_trend(
        am.prepare_runs(
            _activities([_easy_run("2026-03-02", activity_type="treadmill_running")])
        ),
        _zones(),
    )
    monthly = am.monthly_form_metrics(trend)
    assert set(monthly["surface"]) == {am.TREADMILL_SURFACE}
    assert set(monthly["metric"]) == {m.key for m in am.FORM_METRICS}


def test_the_two_surfaces_are_never_pooled_into_one_median() -> None:
    """Pooling would average a belt reading into an outdoor trend."""
    trend = am.pace_trend(
        am.prepare_runs(
            _activities(
                [
                    _easy_run("2026-03-02", cadence=160.0),
                    _easy_run("2026-03-05", cadence=170.0,
                              activity_type="treadmill_running"),
                ]
            )
        ),
        _zones(),
    )
    cadence = am.monthly_form_metrics(trend).query("metric == 'cadence'")
    values = dict(zip(cadence["surface"], cadence["value"]))
    assert values == {am.OUTDOOR_SURFACE: 160.0, am.TREADMILL_SURFACE: 170.0}
    assert 165.0 not in set(cadence["value"])


def test_monthly_form_metrics_on_an_empty_trend() -> None:
    monthly = am.monthly_form_metrics(pd.DataFrame())
    assert monthly.empty
    assert list(monthly.columns) == [
        "metric", "surface", "month_start", "value", "low", "high", "runs"
    ]


def test_form_headline_compares_the_last_28_days_against_the_prior_28() -> None:
    today = date(2026, 3, 29)
    trend = am.pace_trend(
        am.prepare_runs(
            _activities(
                [
                    # Recent window is 02 Mar - 29 Mar, prior is 02 Feb - 01 Mar.
                    _easy_run("2026-01-15", cadence=150.0),   # before both
                    _easy_run("2026-02-20", cadence=160.0),   # prior window
                    _easy_run("2026-03-20", cadence=166.0),   # recent window
                ]
            )
        ),
        _zones(),
    )
    cadence = next(h for h in am.form_headline(trend, today) if h.metric.key == "cadence")
    assert cadence.value == 166.0
    assert cadence.prior == 160.0
    assert cadence.runs == 1
    assert cadence.delta == 6.0


def test_form_headline_always_reports_every_metric() -> None:
    headlines = am.form_headline(pd.DataFrame(), date(2026, 3, 29))
    assert [h.metric.key for h in headlines] == [m.key for m in am.FORM_METRICS]
    assert all(h.value is None and h.delta is None for h in headlines)


def test_improvement_follows_each_metrics_own_direction() -> None:
    """Falling vertical ratio is progress; falling cadence is not."""
    by_key = {m.key: m for m in am.FORM_METRICS}
    lower_better = am.FormHeadline(by_key["vertical_ratio"], 8.0, 8.5, runs=3)
    higher_better = am.FormHeadline(by_key["cadence"], 160.0, 165.0, runs=3)
    assert lower_better.improved is True
    assert higher_better.improved is False


def test_stride_length_has_no_direction_to_improve_in() -> None:
    """It restates pace, so neither way is progress and neither gets a colour."""
    stride = next(m for m in am.FORM_METRICS if m.key == "stride_length")
    assert stride.lower_is_better is None
    assert am.FormHeadline(stride, 120.0, 100.0, runs=3).improved is None


def test_a_change_too_small_to_survive_rounding_is_not_an_improvement() -> None:
    cadence = next(m for m in am.FORM_METRICS if m.key == "cadence")
    assert am.FormHeadline(cadence, 163.02, 163.0, runs=3).improved is None


def test_exactly_the_two_computed_metrics_are_flagged_as_derived() -> None:
    """The fact the page leans on when it tells the reader what to trust."""
    derived = {m.key for m in am.FORM_METRICS if not m.measured}
    assert derived == {"stride_length", "vertical_ratio"}


def test_form_runs_returns_one_row_per_easy_run_per_metric() -> None:
    """The detail behind the medians, on the same easy-run/surface footing."""
    trend = am.pace_trend(
        am.prepare_runs(
            _activities(
                [
                    _easy_run("2026-03-02", cadence=160.0),
                    _easy_run("2026-03-09", cadence=166.0),
                    _easy_run("2026-03-12", cadence=164.0,
                              activity_type="treadmill_running"),
                    _activity("2026-03-16", avg_hr=170.0),  # VO2max, excluded
                ]
            )
        ),
        _zones(),
    )
    runs = am.form_runs(trend)
    assert list(runs.columns) == [
        "metric", "surface", "date", "activity_name", "value"
    ]
    cadence = runs.query("metric == 'cadence'")
    assert len(cadence) == 3
    outdoor = cadence.query("surface == 'outdoor'")
    assert sorted(outdoor["value"]) == [160.0, 166.0]


def test_form_runs_and_the_monthly_median_see_the_same_sample() -> None:
    """A marker that is not in the median would be a lie about the line."""
    trend = am.pace_trend(
        am.prepare_runs(
            _activities(
                [
                    _easy_run("2026-03-02", cadence=160.0),
                    _easy_run("2026-03-09", cadence=166.0),
                    _easy_run("2026-03-20", cadence=164.0,
                              activity_type="treadmill_running"),
                ]
            )
        ),
        _zones(),
    )
    runs = am.form_runs(trend)
    monthly = am.monthly_form_metrics(trend)
    counted = (
        runs.groupby(["metric", "surface"]).size().rename("n").reset_index()
    )
    summed = (
        monthly.groupby(["metric", "surface"])["runs"].sum().rename("n").reset_index()
    )
    pd.testing.assert_frame_equal(counted, summed)
    # And the outdoor March median really is the median of its two markers.
    march = monthly.query("metric == 'cadence' and surface == 'outdoor'")
    assert march["value"].iloc[0] == 163.0


def test_form_runs_on_an_empty_trend() -> None:
    runs = am.form_runs(pd.DataFrame())
    assert runs.empty
    assert list(runs.columns) == [
        "metric", "surface", "date", "activity_name", "value"
    ]


def test_monthly_form_metrics_reports_the_spread_behind_each_median() -> None:
    """A tight month and a scattered one must not read as the same point."""
    trend = am.pace_trend(
        am.prepare_runs(
            _activities(
                [
                    _easy_run("2026-03-02", cadence=155.0),
                    _easy_run("2026-03-09", cadence=163.0),
                    _easy_run("2026-03-16", cadence=171.0),
                ]
            )
        ),
        _zones(),
    )
    march = am.monthly_form_metrics(trend).query(
        "metric == 'cadence' and surface == 'outdoor'"
    )
    assert march["value"].iloc[0] == 163.0
    assert march["low"].iloc[0] == 155.0
    assert march["high"].iloc[0] == 171.0
    assert march["runs"].iloc[0] == 3
