"""Render the training dashboard to a self-contained HTML file.

Produces a two-panel Plotly figure (training-load model + HRV trend) wrapped in
a lightweight HTML shell with a header of current-state cards and a weekly
summary table. Plotly.js is loaded from a CDN to keep the committed file small.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from html import escape

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs_version
from plotly.subplots import make_subplots

from dashboard import styles, theme, zones
from dashboard.metrics import CTL_WARMUP_DAYS, ReadinessSnapshot
from plan.pace import seconds_to_pace

_COLOR_CTL = theme.COLOR_CTL     # blue   - fitness
_COLOR_ATL = theme.COLOR_ATL     # orange - fatigue
_COLOR_TSB = theme.COLOR_TSB     # green  - form
_COLOR_LOAD = theme.COLOR_LOAD   # grey   - daily load bars
_COLOR_HRV = theme.COLOR_HRV     # violet - nightly HRV
_COLOR_BAND = theme.COLOR_BAND   # HRV baseline band fill

# Colors for the periodization strip and the session status badges.
_PHASE_COLOR = {
    "base": "#0ea5e9", "build": "#2563eb", "peak": "#f97316",
    "taper": "#16a34a", "off": "#94a3b8",
}
# Status and intensity are tinted surfaces rather than saturated marks, so they
# carry a CSS class instead of an inline colour — an inline style cannot answer
# ``prefers-color-scheme``, and these need a different tint per scheme.
_STATUS_CLASS = {
    "done": "s-done", "missed": "s-missed", "upcoming": "s-upcoming", "rest": "s-rest",
}
# Zone accent dot, easiest → hardest. Saturated data marks: identical in both schemes.
_ZONE_DOT = {
    "Recovery": "#639922", "Endurance": "#97C459", "Tempo": "#EF9F27",
    "Threshold": "#D85A30", "VO2max": "#E24B4A", "mixed": "#64748b",
}
_INTENSITY_CLASS = {"hard": "i-hard", "moderate": "i-moderate", "easy": "i-easy"}
# Runna-style phase bands (saturated) and per-segment type tags.
_PHASE_BAND = {
    "warmup": ("Warm-up", "#e0683a"),
    "main": ("Main set", "#5a51c9"),
    "cooldown": ("Cool-down", "#14a08a"),
}
_KIND_TAG = {
    "run": ("RUN", "#1d9e75"),
    "rest": ("REST", "#378add"),
    "station": ("STATION", "#ba7517"),
    "strength": ("STRENGTH", "#534ab7"),
    "note": ("", "#94a3b8"),
}

# Curated, vetted bibliography rendered as the static sources panel. Kept here (not
# model-generated) so a citation can never be hallucinated. (claim, citation, tier, url).
_METHODOLOGY_SOURCES = [
    ("Mostly-easy polarized volume beats threshold-heavy blocks",
     "Rosenblat et al. 2019 — systematic review + meta-analysis of RCTs", "strong",
     "https://pubmed.ncbi.nlm.nih.gov/29863593/"),
    ("Elite distance runners train predominantly at low intensity",
     "Casado et al. 2022 — systematic review (IJSPP)", "strong",
     "https://journals.humankinetics.com/view/journals/ijspp/17/6/article-p820.xml"),
    ("Strength training improves running economy",
     "Llanos-Lagos et al. 2024 — meta-analysis (Sports Medicine)", "strong",
     "https://pubmed.ncbi.nlm.nih.gov/38165636/"),
    ("Concurrent strength + endurance is largely compatible (interference is narrow)",
     "Concurrent training & hypertrophy 2022 — systematic review + meta-analysis", "strong",
     "https://pmc.ncbi.nlm.nih.gov/articles/PMC9474354/"),
    ("A ~2-week taper with volume cut 41-60% maximizes performance",
     "Bosquet et al. 2007 — meta-analysis (Med Sci Sports Exerc)", "strong",
     "https://pubmed.ncbi.nlm.nih.gov/17762369/"),
    ("The ACWR injury 'sweet spot' is statistically contested — build gradually, do not spike",
     "Impellizzeri et al. 2020 — conceptual critique (IJSPP)", "contested",
     "https://journals.humankinetics.com/view/journals/ijspp/15/6/article-p907.xml"),
    ("Hyrox demands aerobic + anaerobic power + economy under fatigue",
     "Acute responses & determinants in Hyrox 2025 (Frontiers) — limited literature", "emerging",
     "https://pmc.ncbi.nlm.nih.gov/articles/PMC11994925/"),
]
_TIER_CLASS = {"strong": "t-strong", "contested": "t-contested", "emerging": "t-emerging"}

# The page's behaviour, kept out of the document f-string so the braces need no
# doubling. ``__CHART_THEME__`` is substituted by :func:`_page_script`.
_PAGE_SCRIPT = """
  document.querySelectorAll('.tab-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      document.querySelectorAll('.tab-btn').forEach(function (b) { b.classList.remove('active'); });
      document.querySelectorAll('.tab-panel').forEach(function (p) { p.classList.remove('active'); });
      btn.classList.add('active');
      document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
      window.dispatchEvent(new Event('resize'));  // let Plotly size the hidden chart
    });
  });
  document.querySelectorAll('.gran-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var chart = document.getElementById('volume-chart');
      if (!chart) { return; }
      var order = ['week', 'month', 'year'];
      var visible = [];
      order.forEach(function (g) {
        var on = g === btn.dataset.gran;
        visible.push(on, on);  // one bar trace and one line trace per granularity
      });
      Plotly.restyle(chart, {visible: visible});
      Plotly.relayout(chart, {'yaxis.autorange': true, 'yaxis2.autorange': true});
      document.querySelectorAll('.gran-btn').forEach(function (b) {
        b.classList.toggle('active', b === btn);
      });
    });
  });
  document.querySelectorAll('.sess-row').forEach(function (row) {
    row.addEventListener('click', function () {
      row.classList.toggle('open');
      document.getElementById(row.dataset.sess).classList.toggle('open');
    });
  });
  document.querySelectorAll('.phase-cell').forEach(function (cell) {
    cell.addEventListener('click', function () {
      var wk = cell.dataset.week;
      document.querySelectorAll('.phase-cell').forEach(function (c) {
        var on = c.dataset.week === wk;
        c.classList.toggle('selected', on);
        c.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
      document.querySelectorAll('[data-week-panel]').forEach(function (p) {
        p.classList.toggle('active', p.dataset.weekPanel === wk);
      });
    });
  });

  // Plotly bakes its colours into the document at build time, so the figures are
  // recoloured here to match the scheme the browser actually resolved — and again
  // whenever the OS flips it. Axis keys are read off each figure rather than
  // assumed, so a subplot gains no phantom axes.
  var CHART_THEME = __CHART_THEME__;
  var darkQuery = window.matchMedia('(prefers-color-scheme: dark)');
  var AXIS_KEY = /^[xy]axis[0-9]*$/;

  function applyChartTheme() {
    var t = CHART_THEME[darkQuery.matches ? 'dark' : 'light'];
    document.querySelectorAll('.js-plotly-plot').forEach(function (gd) {
      if (!gd.layout) { return; }
      var update = {};
      Object.keys(t.figure).forEach(function (k) { update[k] = t.figure[k]; });
      Object.keys(gd.layout).forEach(function (key) {
        if (!AXIS_KEY.test(key)) { return; }
        Object.keys(t.axis).forEach(function (prop) {
          update[key + '.' + prop] = t.axis[prop];
        });
        if (gd.layout[key].rangeslider) {
          update[key + '.rangeslider.bgcolor'] = 'rgba(0,0,0,0)';
          update[key + '.rangeslider.bordercolor'] = t.axis.linecolor;
        }
      });
      Plotly.relayout(gd, update);
    });
  }

  applyChartTheme();
  darkQuery.addEventListener('change', applyChartTheme);

  // Retire the entrance animation once it has played, so switching tabs shows
  // its data immediately instead of replaying a stagger.
  window.setTimeout(function () { document.body.classList.remove('intro'); }, 900);
"""


def _page_script() -> str:
    """Return the page's JavaScript with the chart palettes substituted in.

    Returns
    -------
    str
        Script body for the document's single inline ``<script>`` element.
    """
    return _PAGE_SCRIPT.replace("__CHART_THEME__", theme.chart_theme_js())


def _methodology_sources_html() -> str:
    """Render the static, vetted sources list (claim, citation link, evidence tier)."""
    rows = []
    for claim, cite, tier, url in _METHODOLOGY_SOURCES:
        tier_cls = _TIER_CLASS.get(tier, "t-emerging")
        rows.append(
            f"<div class='src'><div class='src-main'><div class='src-claim'>{escape(claim)}</div>"
            f"<a class='src-cite' href='{escape(url)}' target='_blank' rel='noopener'>{escape(cite)}</a></div>"
            f"<span class='tier {tier_cls}'>{tier}</span></div>"
        )
    return f"<div class='src-list'>{''.join(rows)}</div>"


@dataclass(frozen=True)
class PlanWeekView:
    """One week of the block: its header row plus its scored sessions.

    Parameters
    ----------
    header : dict
        The ``training_plan_weeks`` row (phase, weeks_to_race, rationale,
        methodology, ...).
    sessions : pandas.DataFrame
        That week's planned sessions, with a ``status`` column.
    """

    header: dict
    sessions: pd.DataFrame


@dataclass(frozen=True)
class PlanView:
    """View model for the training-plan section.

    Every week of the block is rendered in full and toggled client-side, so any
    week can be opened from the block strip. The page is a static file with no
    server, so the alternative — fetching a week on demand — is not available.

    Parameters
    ----------
    weeks : list of PlanWeekView
        Every week of the current block, in chronological order.
    zones : pandas.DataFrame
        Lactate-anchored training zones (shared across the block).
    selected_week_start : str
        ISO Monday of the week shown on load — normally the week in progress.
    """

    weeks: list[PlanWeekView] = field(default_factory=list)
    zones: pd.DataFrame = field(default_factory=pd.DataFrame)
    selected_week_start: str = ""


def build_figure(load_series: pd.DataFrame, hrv_series: pd.DataFrame) -> go.Figure:
    """Build the two-panel training/recovery figure.

    Parameters
    ----------
    load_series : pandas.DataFrame
        Output of :func:`dashboard.metrics.build_load_series`.
    hrv_series : pandas.DataFrame
        Output of :func:`dashboard.metrics.build_hrv_series`.

    Returns
    -------
    plotly.graph_objects.Figure
        Figure with a load panel (row 1) and an HRV panel (row 2).
    """
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.09,
        row_heights=[0.62, 0.38],
        specs=[[{"secondary_y": True}], [{"secondary_y": False}]],
        subplot_titles=("Training load: fitness, fatigue & form", "HRV vs baseline"),
    )

    # --- Row 1: daily load bars + CTL/ATL lines (primary), TSB (secondary) ---
    fig.add_trace(
        go.Bar(
            x=load_series.index,
            y=load_series["load"],
            name="Daily load",
            marker_color=_COLOR_LOAD,
            opacity=0.7,
            hovertemplate="%{x|%a %d %b}<br>Load: %{y:.0f}<extra></extra>",
        ),
        row=1,
        col=1,
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=load_series.index,
            y=load_series["ctl"],
            name="CTL (fitness)",
            line=dict(color=_COLOR_CTL, width=2.5),
            hovertemplate="%{x|%a %d %b}<br>CTL: %{y:.1f}<extra></extra>",
        ),
        row=1,
        col=1,
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=load_series.index,
            y=load_series["atl"],
            name="ATL (fatigue)",
            line=dict(color=_COLOR_ATL, width=1.8),
            hovertemplate="%{x|%a %d %b}<br>ATL: %{y:.1f}<extra></extra>",
        ),
        row=1,
        col=1,
        secondary_y=False,
    )
    # TSB is unreliable during the CTL warm-up (CTL seeds from zero), so mask
    # that window to NaN: the line simply starts once the value is meaningful,
    # which also keeps the secondary axis scaled to the usable range.
    tsb_display = load_series["tsb"].copy()
    if len(tsb_display) > CTL_WARMUP_DAYS:
        tsb_display.iloc[:CTL_WARMUP_DAYS] = float("nan")
    fig.add_trace(
        go.Scatter(
            x=load_series.index,
            y=tsb_display,
            name="TSB (form)",
            line=dict(color=_COLOR_TSB, width=1.6, dash="dot"),
            connectgaps=False,
            hovertemplate="%{x|%a %d %b}<br>TSB: %{y:.1f}<extra></extra>",
        ),
        row=1,
        col=1,
        secondary_y=True,
    )

    # Shade the CTL warm-up window where TSB is unreliable.
    if len(load_series) > 0:
        warmup_end = load_series.index[min(CTL_WARMUP_DAYS, len(load_series) - 1)]
        fig.add_vrect(
            x0=load_series.index[0],
            x1=warmup_end,
            fillcolor="rgba(148, 163, 184, 0.12)",
            line_width=0,
            row=1,
            col=1,
            annotation_text="warm-up (TSB unreliable)",
            annotation_position="top left",
            annotation_font_size=10,
        )

    # Zero reference for TSB on the secondary axis.
    fig.add_hline(y=0, line=dict(color="#94a3b8", width=1, dash="dash"),
                  row=1, col=1, secondary_y=True)

    # --- Row 2: HRV nightly + baseline band ---
    if not hrv_series.empty:
        fig.add_trace(
            go.Scatter(
                x=hrv_series.index,
                y=hrv_series["baseline_high"],
                name="Baseline high",
                line=dict(width=0),
                showlegend=False,
                hoverinfo="skip",
            ),
            row=2,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=hrv_series.index,
                y=hrv_series["baseline_low"],
                name="Baseline band",
                fill="tonexty",
                fillcolor=_COLOR_BAND,
                line=dict(width=0),
                hoverinfo="skip",
            ),
            row=2,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=hrv_series.index,
                y=hrv_series["hrv_night"],
                name="HRV (last night)",
                mode="lines+markers",
                line=dict(color=_COLOR_HRV, width=2),
                marker=dict(size=5),
                hovertemplate="%{x|%a %d %b}<br>HRV: %{y:.0f} ms<extra></extra>",
            ),
            row=2,
            col=1,
        )

    fig.update_yaxes(title_text="Load / CTL / ATL", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="TSB", row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="HRV (ms)", row=2, col=1)
    fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.05), row=2, col=1)

    fig.update_layout(
        **theme.chart_layout(
            height=760,
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.075, xanchor="left", x=0),
            margin=dict(l=60, r=30, t=96, b=30),
            barmode="overlay",
        )
    )
    return fig


def _snapshot_cards(snapshot: ReadinessSnapshot) -> str:
    """Render the header cards (CTL/ATL/TSB/HRV) as an HTML fragment."""
    hrv_text = (
        f"{snapshot.hrv_night:.0f} ms" if snapshot.hrv_night is not None else "n/a"
    )
    hrv_status = snapshot.hrv_status or "n/a"
    cards = [
        ("Fitness (CTL)", f"{snapshot.ctl:.1f}", "42-day load average"),
        ("Fatigue (ATL)", f"{snapshot.atl:.1f}", "7-day load average"),
        ("Form (TSB)", f"{snapshot.tsb:+.1f}", snapshot.tsb_label),
        ("HRV last night", hrv_text, f"status: {hrv_status}"),
    ]
    items = "".join(
        f"""
        <div class="card">
            <div class="card-label">{label}</div>
            <div class="card-value">{value}</div>
            <div class="card-sub">{sub}</div>
        </div>"""
        for label, value, sub in cards
    )
    return f'<div class="cards">{items}</div>'


def _weekly_table(weekly: pd.DataFrame) -> str:
    """Render the weekly summary DataFrame as an HTML table fragment."""
    if weekly.empty:
        return "<p>No weekly data yet.</p>"

    header = (
        "<tr><th>Week of</th><th>Total load</th><th>Training days</th>"
        "<th>Form (TSB)</th><th>HRV status</th></tr>"
    )
    body = "".join(
        f"<tr><td>{r.week_start}</td><td>{r.total_load:.0f}</td>"
        f"<td>{r.training_days}</td><td>{r.end_tsb:+.1f}</td>"
        f"<td>{r.end_hrv_status or '-'}</td></tr>"
        for r in weekly.itertuples()
    )
    return f"<table class='weekly'>{header}{body}</table>"


def _clean_int(value) -> int | None:
    """Coerce a possibly-NaN/None numeric to ``int`` or ``None``."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return int(value)


def _block_overview(weeks: list[PlanWeekView], selected_week_start: str) -> str:
    """Render the block as a strip of buttons, one per week.

    Each cell is one persisted plan week (date, phase, weeks-to-race). Clicking a
    cell switches the week shown below it; the selected week is outlined. Driven
    by the stored block rather than recomputed, so it reflects exactly what was
    generated — including a block that flows across a race.
    """
    if not weeks:
        return ""
    cells = []
    for wv in weeks:
        wk = wv.header
        week_start = date.fromisoformat(wk["week_start"])
        phase_name = wk.get("phase") or ""
        color = _PHASE_COLOR.get(phase_name, "#94a3b8")
        is_selected = wk["week_start"] == selected_week_start
        cls = "phase-cell selected" if is_selected else "phase-cell"
        wtr = wk.get("weeks_to_race")
        sub = f"{wtr} wk to race" if wtr not in (None, 0) else escape(str(wk.get("target_race") or ""))
        cells.append(
            f'<button type="button" class="{cls}" data-week="{escape(wk["week_start"])}" '
            f'aria-pressed="{"true" if is_selected else "false"}">'
            f'<div class="phase-dot" style="background:{color}"></div>'
            f'<div class="phase-wk">{week_start.strftime("%d %b")}</div>'
            f'<div class="phase-name">{escape(phase_name)}</div>'
            f'<div class="phase-sub">{sub}</div></button>'
        )
    return f'<div class="phase-strip">{"".join(cells)}</div>'


def _zones_table(zones: pd.DataFrame) -> str:
    """Render the lactate-anchored zone reference as an HTML table."""
    if zones.empty:
        return ""
    rows = []
    for z in zones.sort_values("zone_index").itertuples():
        hr_low, hr_high = _clean_int(z.hr_low), _clean_int(z.hr_high)
        hr = f"{hr_low or '–'}–{hr_high or '–'} bpm"
        pace = (
            f"{seconds_to_pace(_clean_int(z.pace_low_s_per_km))}–"
            f"{seconds_to_pace(_clean_int(z.pace_high_s_per_km))} /km"
        )
        rows.append(
            f"<tr><td>Z{z.zone_index} {escape(z.zone_name)}</td>"
            f"<td>{hr}</td><td>{pace}</td></tr>"
        )
    header = "<tr><th>Zone</th><th>Heart rate</th><th>Pace</th></tr>"
    return f"<table class='weekly'>{header}{''.join(rows)}</table>"


def _session_steps_html(presc: dict) -> str:
    """Render a session body as Runna-style banded segment rows.

    Typed segments (with ``metric``) render as phase bands + run/rest/station rows.
    Legacy ``{label, detail}`` steps and empty steps fall back to simple rows so
    older stored weeks still display.
    """
    steps = [s for s in (presc.get("steps") or []) if isinstance(s, dict)]
    typed = [s for s in steps if s.get("metric")]

    if not typed:
        if steps:  # legacy {label, detail}
            return "".join(
                f"<div class='sess-step'><span class='sk'>{escape(str(s.get('label', '')))}</span>"
                f"<span class='sv'>{escape(str(s.get('detail', '')))}</span></div>"
                for s in steps
            )
        detail = escape(str(presc.get("detail", "") or ""))
        return f"<div class='sess-step'><span class='sk'>Session</span><span class='sv'>{detail}</span></div>"

    out: list[str] = []
    current_phase = "__start__"
    num = 0
    for s in typed:
        phase = s.get("phase")
        if phase != current_phase:
            current_phase = phase
            if phase in _PHASE_BAND:
                label, color = _PHASE_BAND[phase]
                out.append(f"<div class='seg-band' style='background:{color}'>{escape(label)}</div>")
        num += 1
        tag_text, tag_color = _KIND_TAG.get(s.get("kind", "note"), ("", "#94a3b8"))
        metric = escape(str(s.get("metric", "") or ""))
        load = s.get("load")
        load_html = f" <span class='seg-load'>@ {escape(str(load))}</span>" if load else ""
        target = s.get("target")
        target_html = f"<div class='seg-target'>{escape(str(target))}</div>" if target else ""
        tag_html = f"<span class='seg-tag' style='color:{tag_color}'>{tag_text}</span>" if tag_text else ""
        out.append(
            f"<div class='seg-row'><span class='seg-num'>{num}</span>"
            f"<div class='seg-main'><div class='seg-metric'><b>{metric}</b>{load_html}</div>"
            f"{target_html}</div>{tag_html}</div>"
        )
    return f"<div class='seg-list'>{''.join(out)}</div>"


def _plan_list(sessions: pd.DataFrame, week_key: str) -> str:
    """Render the week's sessions as an expandable list of structured cards.

    Each row is scannable (zone dot, title, day/zone/distance, intensity); clicking
    it expands the structured breakdown (warm-up / main set / cool-down or rounds)
    plus the session purpose. Falls back to the free-text prescription when a
    session has no structured ``steps``.

    Parameters
    ----------
    sessions : pandas.DataFrame
        The week's planned sessions.
    week_key : str
        The week's ISO Monday, used to namespace the collapsible element ids.
        Every week of the block is in the DOM at once, so a bare index would
        collide and expanding one week's session would toggle another's.
    """
    if sessions.empty:
        return "<p>No sessions for this week.</p>"

    items = []
    for i, r in enumerate(sessions.sort_values("session_date").itertuples()):
        day = pd.to_datetime(r.session_date).strftime("%a %d %b")
        presc = r.prescription if isinstance(r.prescription, dict) else {}
        dist, dur = presc.get("distance_m"), presc.get("duration_min")

        meta = [day]
        if r.zone:
            meta.append(escape(str(r.zone)))
        if dist:
            meta.append(f"{dist / 1000:.1f} km")
        if dur:
            meta.append(f"{dur} min")

        focus = getattr(r, "hyrox_focus", None)
        focus_html = f"<span class='focus'>{escape(str(focus))}</span>" if focus else ""
        dot = _ZONE_DOT.get(r.zone, "#94a3b8")
        intensity_cls = _INTENSITY_CLASS.get(r.intensity, "i-none")
        status = getattr(r, "status", "upcoming")
        status_cls = _STATUS_CLASS.get(status, "s-rest")

        why = str(presc.get("why", "") or "")
        why_html = (
            f"<div class='sess-why'><span class='why-label'>Why this, not more</span>"
            f"{escape(why)}</div>" if why else ""
        )

        sess_id = f"psess-{week_key}-{i}"
        items.append(
            f"<div class='sess'>"
            f"<div class='sess-row' data-sess='{sess_id}'>"
            f"<span class='zdot' style='background:{dot}'></span>"
            f"<div class='sess-main'>"
            f"<div class='sess-title'>{escape(str(r.title or ''))}{focus_html}</div>"
            f"<div class='sess-meta'>{' · '.join(meta)}</div></div>"
            f"<span class='ibadge {intensity_cls}'>{escape(str(r.intensity or ''))}</span>"
            f"<span class='sdot {status_cls}' title='{status}'></span>"
            f"<span class='chev'>&#9662;</span>"
            f"</div>"
            f"<div class='sess-body' id='{sess_id}'>{_session_steps_html(presc)}"
            f"<div class='sess-purpose'>{escape(str(r.purpose or ''))}</div>{why_html}</div>"
            f"</div>"
        )
    return f"<div class='sess-list'>{''.join(items)}</div>"


def _week_cards(header: dict, week_index: int, block_len: int) -> str:
    """Render the four summary cards for one week of the block."""
    race_iso = header.get("race_date")
    race_date = date.fromisoformat(race_iso) if race_iso else None
    # Measured from today, not from the selected week — "until race day" is a real
    # countdown and must not change just because a different week is being viewed.
    countdown = (
        (f"{(race_date - date.today()).days}d", "until race day")
        if race_date is not None else ("—", "no race scheduled")
    )
    cards = [
        (
            "Target race",
            (header.get("target_race") or "none").upper(),
            race_date.strftime("%d %b %Y") if race_date else "—",
        ),
        ("Countdown", countdown[0], countdown[1]),
        (
            "Phase",
            (header.get("phase") or "").title(),
            f"{header.get('weeks_to_race', 0)} weeks to race",
        ),
        ("Block", f"Week {week_index} of {block_len}", "current training block"),
    ]
    return "".join(
        f'<div class="card"><div class="card-label">{label}</div>'
        f'<div class="card-value">{value}</div><div class="card-sub">{sub}</div></div>'
        for label, value, sub in cards
    )


def _plan_section(plan: PlanView) -> str:
    """Render the full training-plan section (cards, strip, week panels, zones).

    Every week of the block is emitted; only the selected one carries ``active``.
    Switching weeks is a class swap in the browser, since the page is a static
    file with nothing to fetch from.
    """
    if plan is None or not plan.weeks:
        return (
            "<h2>Training plan</h2><div class='panel'><p>No plan generated yet — "
            "run <code>python -m plan.context</code>, write the block, then "
            "<code>python -m plan.persist</code>.</p></div>"
        )

    weeks = plan.weeks
    selected = plan.selected_week_start or weeks[0].header["week_start"]

    card_blocks: list[str] = []
    week_panels: list[str] = []
    methodology_blocks: list[str] = []

    for i, wv in enumerate(weeks):
        header = wv.header
        key = header["week_start"]
        active = " active" if key == selected else ""
        week_start = date.fromisoformat(key)

        card_blocks.append(
            f'<div class="cards wk-cards{active}" data-week-panel="{escape(key)}">'
            f"{_week_cards(header, i + 1, len(weeks))}</div>"
        )

        rationale = escape(str(header.get("rationale") or ""))
        week_panels.append(
            f'<div class="panel wk-pane{active}" data-week-panel="{escape(key)}">'
            f'<div class="section-label">Week of {week_start.strftime("%d %b %Y")}</div>'
            f'<p class="plan-hint">Click a session to see the full breakdown.</p>'
            f"{_plan_list(wv.sessions, key)}"
            f'<p class="rationale"><b>Coach\'s note:</b> {rationale}</p></div>'
        )

        methodology = escape(str(header.get("methodology") or ""))
        if methodology:
            methodology_blocks.append(
                f'<p class="methodology wk-pane{active}" data-week-panel="{escape(key)}">'
                f"{methodology}</p>"
            )

    lt1_caveat = ""
    if not plan.zones.empty and _clean_int(plan.zones.iloc[0].get("lt1_hr")) is None:
        lt1_caveat = (
            " LT1 was not captured by the lab test, so the Recovery/Endurance "
            "boundary is approximate."
        )

    model = escape(str(weeks[0].header.get("model") or ""))
    methodology_html = "".join(methodology_blocks)

    return f"""<h2>Training plan</h2>
  {"".join(card_blocks)}
  <div class="panel">
    <div class="section-label">This block</div>
    <p class="plan-hint">Click a week to see its sessions.</p>
    {_block_overview(weeks, selected)}
  </div>
  {"".join(week_panels)}
  <div class="panel">
    <div class="section-label">Methodology &amp; sources</div>
    {methodology_html}
    {_methodology_sources_html()}
    <p class="src-note">Evidence tiers: strong = meta-analysis / RCT review · contested =
    methodologically debated · emerging = limited or practice-derived.</p>
  </div>
  <div class="panel">
    <div class="section-label">Lactate-anchored zones</div>
    {_zones_table(plan.zones)}
    <p class="zone-note">Anchored on LT2 from the {escape(str(plan.zones.iloc[0]['source_test_date']))
      if not plan.zones.empty else 'n/a'} step test.{lt1_caveat} Generated by {model}.</p>
  </div>"""


def render_html(
    fig: go.Figure,
    snapshot: ReadinessSnapshot,
    weekly: pd.DataFrame,
    zones_fig: go.Figure,
    pace_fig: go.Figure,
    plan: PlanView | None = None,
    metrics_html: str = "",
) -> str:
    """Assemble the full HTML document.

    Parameters
    ----------
    fig : plotly.graph_objects.Figure
        The two-panel figure from :func:`build_figure`.
    snapshot : ReadinessSnapshot
        Current-state snapshot for the header cards.
    weekly : pandas.DataFrame
        Weekly summary from :func:`dashboard.metrics.weekly_summary`.
    plan : PlanView or None, optional
        Training-plan view model; when ``None`` the section is omitted.
    zones_fig : plotly.graph_objects.Figure
        The HR-zone comparison band chart from
        :func:`dashboard.zones.build_zone_comparison_figure`.
    pace_fig : plotly.graph_objects.Figure
        The pace-zone comparison band chart from
        :func:`dashboard.zones.build_pace_comparison_figure`.
    metrics_html : str, optional
        Pre-rendered metrics-tab fragment from
        :func:`dashboard.metrics_tab.metrics_section_html`; when empty the tab
        shows a placeholder.

    Returns
    -------
    str
        A complete, self-contained HTML document.
    """
    chart_html = fig.to_html(full_html=False, include_plotlyjs=False)
    zones_chart_html = zones_fig.to_html(full_html=False, include_plotlyjs=False)
    pace_chart_html = pace_fig.to_html(full_html=False, include_plotlyjs=False)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    as_of = snapshot.date.strftime("%A, %d %B %Y")
    plan_html = _plan_section(plan) if plan is not None else ""
    metrics_section = metrics_html or (
        "<h2>Metrics</h2><div class='panel'><p>No metrics available yet.</p></div>"
    )
    stylesheet = styles.stylesheet()
    page_script = _page_script()
    fonts_href = theme.GOOGLE_FONTS_HREF

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>Training Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{fonts_href}">
<script src="https://cdn.plot.ly/plotly-{get_plotlyjs_version()}.min.js" charset="utf-8"></script>
<style>{stylesheet}</style>
</head>
<body class="intro">
<div class="wrap">
  <header class="masthead">
    <h1>Training Dashboard</h1>
    <div class="as-of">As of {as_of}</div>
  </header>

  <div class="tabs">
    <button class="tab-btn active" data-tab="plan">Training plan</button>
    <button class="tab-btn" data-tab="metrics">Metrics</button>
    <button class="tab-btn" data-tab="training">Training load</button>
    <button class="tab-btn" data-tab="zones">Zones</button>
  </div>

  <div class="tab-panel active" id="tab-plan">
    {plan_html}
  </div>

  <div class="tab-panel" id="tab-metrics">
    {metrics_section}
  </div>

  <div class="tab-panel" id="tab-training">
    {_snapshot_cards(snapshot)}
    <div class="panel">{chart_html}</div>
    <h2>Weekly summary</h2>
    <div class="panel">{_weekly_table(weekly)}</div>
  </div>

  <div class="tab-panel" id="tab-zones">
    <h2>Heart-rate zones: lab vs Garmin</h2>
    <div class="callout">{zones.example_hr_callout(165)}</div>
    <div class="panel">{zones_chart_html}</div>
    <div class="panel">{zones.zone_table_html()}</div>
    <p class="note">Your <strong>Lab</strong> zones are anchored on the measured
    anaerobic threshold (LT2 ≈ {zones.LAB_LT2_HR} bpm) from the 2026-06-19 lactate
    test. <strong>Garmin</strong> anchors on an assumed maximum heart rate (~200),
    not threshold — so its hard zones sit well above your real ones. Garmin even
    stores a threshold HR of 175 but uses %max-HR for the zones. Net effect: a
    heart rate the lab calls threshold/VO2max still reads as Z3-Z4 on Garmin.</p>

    <h2 style="margin-top:28px">Pace zones</h2>
    <div class="callout">{zones.example_pace_callout("4:30")}</div>
    <div class="panel">{pace_chart_html}</div>
    <div class="panel">{zones.pace_table_html()}</div>
    <p class="note">Lab pace zones come from the same test (threshold pace
    ≈ {zones.format_pace(zones.LAB_LT2_PACE_S)}/km). There is nothing to compare
    them against: <strong>Garmin</strong> does not publish running pace zones for
    this athlete.</p>
  </div>

  <footer>Generated {generated} · Garmin training load + HRV · TSB bands follow
  TrainingPeaks conventions. CTL warm-up window shaded; treat early TSB with caution.</footer>
</div>
<script>{page_script}</script>
</body>
</html>"""
