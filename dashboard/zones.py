"""Heart-rate training zones: lab-measured vs platform-estimated.

Compares three sources of HR zones for the same athlete:

* **Lab** — derived from the 2026-06-19 treadmill lactate step test, anchored on
  the measured anaerobic threshold (LT2 ≈ 163 bpm). The only individualised,
  physiologically grounded set.
* **Garmin** — Garmin Connect's zones (``HR_MAX`` method, maxHR = 200), fetched
  from ``/biometric-service/heartRateZones``. Note Garmin stores a lactate
  threshold HR of 175 but does not use it for these zones.
* **Strava** — Strava's zones (``MaxHeartRateFromAge``), from the athlete-zones
  endpoint.

Both platforms anchor on (an assumed) maximum heart rate rather than threshold,
so their hard zones sit well above the lab's. The comparison makes that gap
visible: the same HR maps to very different zones depending on the source.

These are reference values that change only when a new test is done or the
platforms recompute; they are stored here as data. Sourced 2026-06-20.
"""

from __future__ import annotations

from dataclasses import dataclass

import plotly.graph_objects as go

# Common bpm axis for the band chart (covers easy through maximal for this athlete).
_AXIS_MIN = 100
_AXIS_MAX = 200

# Intensity colour ramp, easiest (Z1) to hardest (Z5).
_ZONE_COLORS = ["#16a34a", "#84cc16", "#eab308", "#f97316", "#dc2626"]

# The lab anchor (LT2 consensus) — also drawn as a reference line.
LAB_LT2_HR = 163


@dataclass(frozen=True)
class Zone:
    """One HR zone. ``lo``/``hi`` are bpm bounds; ``None`` means open-ended."""

    label: str
    lo: int | None
    hi: int | None


@dataclass(frozen=True)
class ZoneSystem:
    """A named set of five HR zones from one source."""

    name: str
    source: str
    anchor: str
    zones: list[Zone]


# ── The three systems (ordered easiest-zone-first within each) ──

LAB = ZoneSystem(
    name="Lab (lactate test)",
    source="2026-06-19 lactate step test",
    anchor="LT2 threshold ≈ 163 bpm",
    zones=[
        Zone("Z1 Recovery", None, 139),
        Zone("Z2 Endurance", 139, 147),
        Zone("Z3 Tempo", 147, 155),
        Zone("Z4 Threshold", 155, 163),
        Zone("Z5 VO2max", 163, None),
    ],
)

GARMIN = ZoneSystem(
    name="Garmin",
    source="Garmin Connect (HR_MAX)",
    anchor="max HR = 200 (assumed)",
    zones=[
        Zone("Z1", 104, 120),
        Zone("Z2", 120, 140),
        Zone("Z3", 140, 162),
        Zone("Z4", 162, 180),
        Zone("Z5", 180, None),
    ],
)

STRAVA = ZoneSystem(
    name="Strava",
    source="Strava (max HR from age)",
    anchor="max HR ≈ 190 (from age)",
    zones=[
        Zone("Z1", None, 126),
        Zone("Z2", 126, 157),
        Zone("Z3", 157, 173),
        Zone("Z4", 173, 188),
        Zone("Z5", 188, None),
    ],
)

SYSTEMS = [LAB, GARMIN, STRAVA]


def zone_at_hr(system: ZoneSystem, hr: int) -> str:
    """Return the zone label a given heart rate falls into for one system."""
    for zone in system.zones:
        lo = zone.lo if zone.lo is not None else _AXIS_MIN - 1
        hi = zone.hi if zone.hi is not None else _AXIS_MAX + 1
        if lo <= hr < hi:
            return zone.label
    return "—"


def build_zone_comparison_figure(systems: list[ZoneSystem] = SYSTEMS) -> go.Figure:
    """Build a horizontal band chart: one row per source, zones tiled along a bpm axis.

    Parameters
    ----------
    systems : list[ZoneSystem], optional
        Systems to compare, drawn bottom-to-top in reverse list order so the
        first (Lab) sits on top.

    Returns
    -------
    plotly.graph_objects.Figure
    """
    fig = go.Figure()
    order = list(reversed(systems))  # categorical y: last added ends on top

    for system in order:
        for zi, zone in enumerate(system.zones):
            lo = zone.lo if zone.lo is not None else _AXIS_MIN
            hi = zone.hi if zone.hi is not None else _AXIS_MAX
            width = hi - lo
            bound_text = (
                f"{zone.lo}-{zone.hi}" if zone.lo and zone.hi
                else f"<{zone.hi}" if zone.lo is None
                else f"{zone.lo}+"
            )
            fig.add_trace(
                go.Bar(
                    y=[system.name],
                    x=[width],
                    base=lo,
                    orientation="h",
                    marker=dict(color=_ZONE_COLORS[zi], line=dict(color="white", width=1.5)),
                    text=bound_text if width >= 10 else "",
                    textposition="inside",
                    insidetextanchor="middle",
                    textfont=dict(size=10, color="white"),
                    showlegend=False,
                    hovertemplate=f"{system.name}<br>{zone.label}: {bound_text} bpm<extra></extra>",
                )
            )

    # Reference line at the lab-measured threshold.
    fig.add_vline(
        x=LAB_LT2_HR,
        line=dict(color="#0f172a", width=2, dash="dash"),
        annotation_text=f"Lab threshold {LAB_LT2_HR}",
        annotation_position="top",
        annotation_font_size=11,
    )

    fig.update_layout(
        barmode="overlay",
        height=300,
        template="plotly_white",
        margin=dict(l=120, r=30, t=40, b=40),
        xaxis=dict(title="Heart rate (bpm)", range=[_AXIS_MIN, _AXIS_MAX]),
        yaxis=dict(categoryorder="array", categoryarray=[s.name for s in order]),
    )
    return fig


def zone_table_html(systems: list[ZoneSystem] = SYSTEMS) -> str:
    """Render a comparison table of zone boundaries across the systems."""
    header = (
        "<tr><th>Source</th><th>Anchor</th>"
        "<th>Z1</th><th>Z2</th><th>Z3</th><th>Z4</th><th>Z5</th></tr>"
    )

    def _fmt(zone: Zone) -> str:
        if zone.lo is None:
            return f"&lt;{zone.hi}"
        if zone.hi is None:
            return f"{zone.lo}+"
        return f"{zone.lo}-{zone.hi}"

    rows = ""
    for system in systems:
        cells = "".join(f"<td>{_fmt(z)}</td>" for z in system.zones)
        rows += (
            f"<tr><td><strong>{system.name}</strong></td>"
            f"<td class='muted'>{system.anchor}</td>{cells}</tr>"
        )
    return f"<table class='zones'>{header}{rows}</table>"


def example_hr_callout(hr: int = 165) -> str:
    """Render a one-line callout showing how one HR maps across all systems."""
    parts = " · ".join(f"{s.name.split()[0]}: <strong>{zone_at_hr(s, hr)}</strong>" for s in SYSTEMS)
    return f"At <strong>{hr} bpm</strong> &rarr; {parts}"


# ── Pace zones ────────────────────────────────────────────────────────────────
# Pace is stored as seconds per km (smaller = faster = harder). Garmin does not
# expose running pace zones (404 from the biometric service) and this athlete's
# Garmin threshold pace is unset, so pace is a Lab-vs-Strava comparison.

# Pace band-chart axis, seconds per km (slow on the left, fast on the right).
_PACE_AXIS_SLOW = 360  # 6:00/km
_PACE_AXIS_FAST = 210  # 3:30/km

# Six-step ramp (Strava has a 6th zone); Lab uses the first five.
_PACE_COLORS = ["#16a34a", "#84cc16", "#eab308", "#f97316", "#dc2626", "#991b1b"]

# The lab threshold pace (LT2), drawn as a reference line.
LAB_LT2_PACE_S = 274  # 4:34/km


def pace_seconds(pace: str) -> int:
    """Convert a ``"m:ss"`` per-km pace to seconds per km."""
    minutes, seconds = pace.split(":")
    return int(minutes) * 60 + int(seconds)


def format_pace(seconds: float) -> str:
    """Format seconds per km as ``"m:ss"``."""
    total = round(seconds)
    return f"{total // 60}:{total % 60:02d}"


@dataclass(frozen=True)
class PaceZone:
    """One pace zone. Bounds are seconds per km; ``None`` means open-ended.

    ``slow_s`` is the slower (larger) bound, ``fast_s`` the faster (smaller) one.
    """

    label: str
    slow_s: int | None
    fast_s: int | None


@dataclass(frozen=True)
class PaceSystem:
    """A named set of running pace zones from one source."""

    name: str
    source: str
    zones: list[PaceZone]


LAB_PACE = PaceSystem(
    name="Lab (lactate test)",
    source="LT2 pace ≈ 4:34/km",
    zones=[
        PaceZone("Z1 Recovery", None, pace_seconds("5:22")),
        PaceZone("Z2 Endurance", pace_seconds("5:22"), pace_seconds("5:04")),
        PaceZone("Z3 Tempo", pace_seconds("5:04"), pace_seconds("4:48")),
        PaceZone("Z4 Threshold", pace_seconds("4:48"), pace_seconds("4:34")),
        PaceZone("Z5 VO2max", pace_seconds("4:34"), None),
    ],
)

STRAVA_PACE = PaceSystem(
    name="Strava",
    source="from estimated 5 km (19:29)",
    zones=[
        PaceZone("Z1", None, pace_seconds("5:28")),
        PaceZone("Z2", pace_seconds("5:28"), pace_seconds("4:42")),
        PaceZone("Z3", pace_seconds("4:42"), pace_seconds("4:13")),
        PaceZone("Z4", pace_seconds("4:13"), pace_seconds("3:57")),
        PaceZone("Z5", pace_seconds("3:57"), pace_seconds("3:43")),
        PaceZone("Z6", pace_seconds("3:43"), None),
    ],
)

PACE_SYSTEMS = [LAB_PACE, STRAVA_PACE]


def pace_zone_at(system: PaceSystem, pace: str) -> str:
    """Return the zone label a given pace falls into for one system."""
    secs = pace_seconds(pace)
    for zone in system.zones:
        slow = zone.slow_s if zone.slow_s is not None else _PACE_AXIS_SLOW + 1
        fast = zone.fast_s if zone.fast_s is not None else _PACE_AXIS_FAST - 1
        if fast < secs <= slow:
            return zone.label
    return "—"


def build_pace_comparison_figure(systems: list[PaceSystem] = PACE_SYSTEMS) -> go.Figure:
    """Build a horizontal pace band chart (slow left, fast right)."""
    fig = go.Figure()
    order = list(reversed(systems))  # first system (Lab) ends on top

    for system in order:
        for zi, zone in enumerate(system.zones):
            slow = zone.slow_s if zone.slow_s is not None else _PACE_AXIS_SLOW
            fast = zone.fast_s if zone.fast_s is not None else _PACE_AXIS_FAST
            width = slow - fast
            bound_text = (
                f"{format_pace(zone.slow_s)}-{format_pace(zone.fast_s)}"
                if zone.slow_s and zone.fast_s
                else f"&gt;{format_pace(zone.fast_s)}" if zone.slow_s is None
                else f"&lt;{format_pace(zone.slow_s)}"
            )
            fig.add_trace(
                go.Bar(
                    y=[system.name],
                    x=[width],
                    base=fast,
                    orientation="h",
                    marker=dict(color=_PACE_COLORS[zi], line=dict(color="white", width=1.5)),
                    text=bound_text if width >= 18 else "",
                    textposition="inside",
                    insidetextanchor="middle",
                    textfont=dict(size=10, color="white"),
                    showlegend=False,
                    hovertemplate=f"{system.name}<br>{zone.label}: {bound_text}/km<extra></extra>",
                )
            )

    fig.add_vline(
        x=LAB_LT2_PACE_S,
        line=dict(color="#0f172a", width=2, dash="dash"),
        annotation_text=f"Lab threshold {format_pace(LAB_LT2_PACE_S)}",
        annotation_position="top",
        annotation_font_size=11,
    )

    tickvals = list(range(_PACE_AXIS_FAST, _PACE_AXIS_SLOW + 1, 30))
    fig.update_layout(
        barmode="overlay",
        height=240,
        template="plotly_white",
        margin=dict(l=120, r=30, t=40, b=40),
        xaxis=dict(
            title="Pace (min/km)",
            range=[_PACE_AXIS_SLOW, _PACE_AXIS_FAST],  # descending → faster on the right
            tickvals=tickvals,
            ticktext=[format_pace(v) for v in tickvals],
        ),
        yaxis=dict(categoryorder="array", categoryarray=[s.name for s in order]),
    )
    return fig


def pace_table_html(systems: list[PaceSystem] = PACE_SYSTEMS) -> str:
    """Render a comparison table of pace-zone boundaries."""
    max_zones = max(len(s.zones) for s in systems)
    head_cells = "".join(f"<th>Z{i + 1}</th>" for i in range(max_zones))
    header = f"<tr><th>Source</th><th>Anchor</th>{head_cells}</tr>"

    def _fmt(zone: PaceZone) -> str:
        if zone.slow_s is None:
            return f"&gt;{format_pace(zone.fast_s)}"
        if zone.fast_s is None:
            return f"&lt;{format_pace(zone.slow_s)}"
        return f"{format_pace(zone.slow_s)}-{format_pace(zone.fast_s)}"

    rows = ""
    for system in systems:
        cells = "".join(f"<td>{_fmt(z)}</td>" for z in system.zones)
        cells += "<td></td>" * (max_zones - len(system.zones))
        rows += (
            f"<tr><td><strong>{system.name}</strong></td>"
            f"<td class='muted'>{system.source}</td>{cells}</tr>"
        )
    rows += (
        "<tr><td><strong>Garmin</strong></td>"
        "<td class='muted'>not set / not exposed by API</td>"
        f"<td colspan='{max_zones}' class='muted'>Garmin does not publish running "
        "pace zones for this athlete</td></tr>"
    )
    return f"<table class='zones'>{header}{rows}</table>"


def example_pace_callout(pace: str = "4:30") -> str:
    """Render a one-line callout showing how one pace maps across systems."""
    parts = " · ".join(
        f"{s.name.split()[0]}: <strong>{pace_zone_at(s, pace)}</strong>" for s in PACE_SYSTEMS
    )
    return f"At <strong>{pace}/km</strong> &rarr; {parts}"
