"""Training-load and HRV metrics.

Implements the Banister / TrainingPeaks impulse-response model on top of
Garmin's per-activity training load:

* CTL (Chronic Training Load, "fitness") - an exponentially weighted moving
  average of daily load with a 42-day time constant. Slow-moving.
* ATL (Acute Training Load, "fatigue") - the same with a 7-day time constant.
  Fast-moving.
* TSB (Training Stress Balance, "form") = CTL - ATL. Positive means fresh,
  negative means carrying fatigue.

The EWMAs are seeded from zero (an untrained baseline), so the first ~42 days
of CTL are an artificially low warm-up ramp and TSB in that window should not
be trusted. ``CTL_WARMUP_DAYS`` exposes that span so the chart can shade it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

CTL_TIME_CONSTANT = 42
ATL_TIME_CONSTANT = 7
CTL_WARMUP_DAYS = 42


@dataclass(frozen=True)
class ReadinessSnapshot:
    """Latest-state summary shown in the dashboard header.

    Parameters
    ----------
    date : pandas.Timestamp
        Most recent day in the load series.
    ctl : float
        Current fitness (CTL).
    atl : float
        Current fatigue (ATL).
    tsb : float
        Current form (TSB = CTL - ATL).
    tsb_label : str
        Human-readable interpretation of the TSB band.
    hrv_night : float or None
        Most recent nightly HRV average, if available.
    hrv_status : str or None
        Most recent Garmin HRV status (e.g. BALANCED, LOW), if available.
    """

    date: pd.Timestamp
    ctl: float
    atl: float
    tsb: float
    tsb_label: str
    hrv_night: float | None
    hrv_status: str | None


def _ewma_from_zero(loads: np.ndarray, time_constant: int) -> np.ndarray:
    """Recursive exponentially weighted moving average seeded from zero.

    Uses the sports-science convention ``y_t = y_{t-1}*(1-a) + a*x_t`` with
    ``a = 1 - exp(-1/time_constant)`` and ``y_{-1} = 0``.

    Parameters
    ----------
    loads : numpy.ndarray
        Daily training-load values on a continuous (gap-filled) date index.
    time_constant : int
        Decay time constant in days (42 for CTL, 7 for ATL).

    Returns
    -------
    numpy.ndarray
        The smoothed series, same length as ``loads``.
    """
    alpha = 1.0 - np.exp(-1.0 / time_constant)
    out = np.empty_like(loads, dtype=float)
    prev = 0.0
    for i, x in enumerate(loads):
        prev = prev * (1.0 - alpha) + alpha * float(x)
        out[i] = prev
    return out


def tsb_label(tsb: float) -> str:
    """Map a TSB value to a TrainingPeaks-style interpretation band.

    Parameters
    ----------
    tsb : float
        Training Stress Balance (CTL - ATL).

    Returns
    -------
    str
        One of: "Fresh / tapered", "Balanced", "Productive overload",
        "Overreaching risk".
    """
    if tsb > 5:
        return "Fresh / tapered"
    if tsb >= -10:
        return "Balanced"
    if tsb >= -30:
        return "Productive overload"
    return "Overreaching risk"


def build_load_series(activities: pd.DataFrame) -> pd.DataFrame:
    """Build the daily load series with CTL/ATL/TSB.

    Daily load is the sum of Garmin ``training_load`` over activities on each
    calendar day (local date). Missing days are filled with zero so the EWMAs
    decay correctly across rest days.

    Parameters
    ----------
    activities : pandas.DataFrame
        Output of :func:`dashboard.query.fetch_activities`.

    Returns
    -------
    pandas.DataFrame
        Indexed by date with columns: load, ctl, atl, tsb.
    """
    if activities.empty:
        return pd.DataFrame(columns=["load", "ctl", "atl", "tsb"])

    # Build the daily series without mutating the input frame.
    dates = pd.to_datetime(activities["start_time_local"]).dt.normalize()
    loads = pd.to_numeric(activities["training_load"], errors="coerce").fillna(0.0)
    daily = (
        pd.Series(loads.to_numpy(), index=dates.to_numpy())
        .groupby(level=0)
        .sum()
        .rename("load")
    )
    daily.index = pd.to_datetime(daily.index)

    full_index = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(full_index, fill_value=0.0)

    loads = daily.to_numpy()
    ctl = _ewma_from_zero(loads, CTL_TIME_CONSTANT)
    atl = _ewma_from_zero(loads, ATL_TIME_CONSTANT)
    result = pd.DataFrame(
        {"load": loads, "ctl": ctl, "atl": atl, "tsb": ctl - atl},
        index=daily.index,
    )
    result.index.name = "date"
    return result


def build_hrv_series(hrv: pd.DataFrame) -> pd.DataFrame:
    """Collapse per-reading HRV rows into one summary row per night.

    All readings for a given date share the same nightly/weekly/baseline
    summary values, so we take the first non-null per date.

    Parameters
    ----------
    hrv : pandas.DataFrame
        Output of :func:`dashboard.query.fetch_hrv`.

    Returns
    -------
    pandas.DataFrame
        Indexed by date with columns: hrv_night, weekly_avg, baseline_low,
        baseline_high, status.
    """
    if hrv.empty:
        return pd.DataFrame(
            columns=["hrv_night", "weekly_avg", "baseline_low", "baseline_high", "status"]
        )

    # Construct a fresh frame (avoids chained-assignment on the input copy).
    tmp = pd.DataFrame(
        {
            "date": pd.to_datetime(hrv["date"]).dt.normalize(),
            "hrv_night": pd.to_numeric(hrv["hrv_avg_night"], errors="coerce"),
            "weekly_avg": pd.to_numeric(hrv["hrv_weekly_avg"], errors="coerce"),
            "baseline_low": pd.to_numeric(hrv["hrv_baseline_low"], errors="coerce"),
            "baseline_high": pd.to_numeric(hrv["hrv_baseline_high"], errors="coerce"),
            "status": hrv["hrv_status"],
        }
    )
    return tmp.sort_values("date").groupby("date").first()


def weekly_summary(load_series: pd.DataFrame, hrv_series: pd.DataFrame) -> pd.DataFrame:
    """Aggregate load and HRV into a per-ISO-week table, most recent first.

    Parameters
    ----------
    load_series : pandas.DataFrame
        Output of :func:`build_load_series`.
    hrv_series : pandas.DataFrame
        Output of :func:`build_hrv_series`.

    Returns
    -------
    pandas.DataFrame
        Columns: week_start, total_load, training_days, end_tsb, end_hrv_status.
    """
    if load_series.empty:
        return pd.DataFrame(
            columns=["week_start", "total_load", "training_days", "end_tsb", "end_hrv_status"]
        )

    df = load_series.copy()
    df["week_start"] = df.index.to_period("W-SUN").start_time

    rows = []
    for week_start, group in df.groupby("week_start"):
        last_day = group.index.max()
        hrv_status = None
        if not hrv_series.empty and last_day in hrv_series.index:
            hrv_status = hrv_series.loc[last_day, "status"]
        rows.append(
            {
                "week_start": week_start.date().isoformat(),
                "total_load": round(float(group["load"].sum()), 0),
                "training_days": int((group["load"] > 0).sum()),
                "end_tsb": round(float(group.loc[last_day, "tsb"]), 1),
                "end_hrv_status": hrv_status,
            }
        )

    return pd.DataFrame(rows).iloc[::-1].reset_index(drop=True)


def latest_snapshot(load_series: pd.DataFrame, hrv_series: pd.DataFrame) -> ReadinessSnapshot:
    """Build the current-state snapshot for the dashboard header.

    Parameters
    ----------
    load_series : pandas.DataFrame
        Output of :func:`build_load_series`.
    hrv_series : pandas.DataFrame
        Output of :func:`build_hrv_series`.

    Returns
    -------
    ReadinessSnapshot
        Latest CTL/ATL/TSB plus the most recent HRV night and status.
    """
    last = load_series.iloc[-1]
    last_date = load_series.index[-1]

    hrv_night = None
    hrv_status = None
    if not hrv_series.empty:
        latest_hrv = hrv_series.iloc[-1]
        hrv_night = (
            float(latest_hrv["hrv_night"]) if pd.notna(latest_hrv["hrv_night"]) else None
        )
        hrv_status = latest_hrv["status"] if pd.notna(latest_hrv["status"]) else None

    tsb_value = float(last["tsb"])
    return ReadinessSnapshot(
        date=last_date,
        ctl=round(float(last["ctl"]), 1),
        atl=round(float(last["atl"]), 1),
        tsb=round(tsb_value, 1),
        tsb_label=tsb_label(tsb_value),
        hrv_night=hrv_night,
        hrv_status=hrv_status,
    )
