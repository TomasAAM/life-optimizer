"""Render the training dashboard to a self-contained HTML file.

Produces a two-panel Plotly figure (training-load model + HRV trend) wrapped in
a lightweight HTML shell with a header of current-state cards and a weekly
summary table. Plotly.js is loaded from a CDN to keep the committed file small.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html import escape

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dashboard import zones
from dashboard.metrics import CTL_WARMUP_DAYS, ReadinessSnapshot
from plan import phase as plan_phase
from plan.pace import seconds_to_pace

_COLOR_CTL = "#2563eb"   # blue  - fitness
_COLOR_ATL = "#f97316"   # orange - fatigue
_COLOR_TSB = "#16a34a"   # green - form
_COLOR_LOAD = "#cbd5e1"  # grey  - daily load bars
_COLOR_HRV = "#7c3aed"   # violet - nightly HRV
_COLOR_BAND = "rgba(124, 58, 237, 0.15)"  # HRV baseline band fill

# Colors for the periodization strip and the session status badges.
_PHASE_COLOR = {
    "base": "#0ea5e9", "build": "#2563eb", "peak": "#f97316",
    "taper": "#16a34a", "off": "#94a3b8",
}
_STATUS_COLOR = {
    "done": "#16a34a", "missed": "#dc2626", "upcoming": "#94a3b8", "rest": "#cbd5e1",
}
# Zone accent dot (easiest → hardest) and intensity pill (bg, text).
_ZONE_DOT = {
    "Recovery": "#639922", "Endurance": "#97C459", "Tempo": "#EF9F27",
    "Threshold": "#D85A30", "VO2max": "#E24B4A", "mixed": "#64748b",
}
_INTENSITY_BADGE = {
    "hard": ("#fef2f2", "#dc2626"),
    "moderate": ("#fffbeb", "#b45309"),
    "easy": ("#f0fdf4", "#16a34a"),
}
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
_TIER_BADGE = {
    "strong": ("#f0fdf4", "#16a34a"),
    "contested": ("#fffbeb", "#b45309"),
    "emerging": ("#f1f5f9", "#475569"),
}


def _methodology_sources_html() -> str:
    """Render the static, vetted sources list (claim, citation link, evidence tier)."""
    rows = []
    for claim, cite, tier, url in _METHODOLOGY_SOURCES:
        bg, fg = _TIER_BADGE.get(tier, ("#f1f5f9", "#475569"))
        rows.append(
            f"<div class='src'><div class='src-main'><div class='src-claim'>{escape(claim)}</div>"
            f"<a class='src-cite' href='{escape(url)}' target='_blank' rel='noopener'>{escape(cite)}</a></div>"
            f"<span class='tier' style='background:{bg};color:{fg}'>{tier}</span></div>"
        )
    return f"<div class='src-list'>{''.join(rows)}</div>"


@dataclass(frozen=True)
class PlanView:
    """View model for the training-plan section.

    Parameters
    ----------
    week : dict or None
        Latest ``training_plan_weeks`` row, or ``None`` when no plan exists yet.
    sessions : pandas.DataFrame
        Planned sessions for that week, with a ``status`` column.
    zones : pandas.DataFrame
        Lactate-anchored training zones.
    """

    week: dict | None
    sessions: pd.DataFrame
    zones: pd.DataFrame


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
        height=760,
        template="plotly_white",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.04, xanchor="left", x=0),
        margin=dict(l=60, r=30, t=70, b=30),
        barmode="overlay",
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


def _phase_strip(race_date: date, current_week_start: date) -> str:
    """Render a colored week-by-week periodization strip up to the race."""
    cells = []
    week = current_week_start
    guard = 0
    while week <= race_date and guard < 40:
        phase_name, _ = plan_phase.phase_for_week(week, race_date)
        color = _PHASE_COLOR.get(phase_name, "#94a3b8")
        border = "2px solid #0f172a" if week == current_week_start else "1px solid #e2e8f0"
        cells.append(
            f'<div class="phase-cell" style="border:{border}">'
            f'<div class="phase-dot" style="background:{color}"></div>'
            f'<div class="phase-wk">{week.strftime("%d %b")}</div>'
            f'<div class="phase-name">{phase_name}</div></div>'
        )
        week += timedelta(days=7)
        guard += 1
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


def _plan_list(sessions: pd.DataFrame) -> str:
    """Render the week's sessions as an expandable list of structured cards.

    Each row is scannable (zone dot, title, day/zone/distance, intensity); clicking
    it expands the structured breakdown (warm-up / main set / cool-down or rounds)
    plus the session purpose. Falls back to the free-text prescription when a
    session has no structured ``steps``.
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
        bg, fg = _INTENSITY_BADGE.get(r.intensity, ("#f1f5f9", "#475569"))
        status = getattr(r, "status", "upcoming")
        status_color = _STATUS_COLOR.get(status, "#cbd5e1")

        why = str(presc.get("why", "") or "")
        why_html = (
            f"<div class='sess-why'><span class='why-label'>Why this, not more</span>"
            f"{escape(why)}</div>" if why else ""
        )

        items.append(
            f"<div class='sess'>"
            f"<div class='sess-row' data-sess='{i}'>"
            f"<span class='zdot' style='background:{dot}'></span>"
            f"<div class='sess-main'>"
            f"<div class='sess-title'>{escape(str(r.title or ''))}{focus_html}</div>"
            f"<div class='sess-meta'>{' · '.join(meta)}</div></div>"
            f"<span class='ibadge' style='background:{bg};color:{fg}'>{escape(str(r.intensity or ''))}</span>"
            f"<span class='sdot' style='background:{status_color}' title='{status}'></span>"
            f"<span class='chev'>&#9662;</span>"
            f"</div>"
            f"<div class='sess-body' id='psess{i}'>{_session_steps_html(presc)}"
            f"<div class='sess-purpose'>{escape(str(r.purpose or ''))}</div>{why_html}</div>"
            f"</div>"
        )
    return f"<div class='sess-list'>{''.join(items)}</div>"


def _plan_section(plan: PlanView) -> str:
    """Render the full training-plan section (cards, strip, table, zones)."""
    if plan is None or plan.week is None:
        return (
            "<h2>Training plan</h2><div class='panel'><p>No plan generated yet — "
            "run <code>python -m plan.generate</code>.</p></div>"
        )

    week = plan.week
    race_date = date.fromisoformat(week["race_date"])
    week_start = date.fromisoformat(week["week_start"])
    days_to = (race_date - date.today()).days

    cards = [
        ("Target race", week["target_race"].upper(), race_date.strftime("%d %b %Y")),
        ("Countdown", f"{days_to}d", "until race day"),
        ("Phase", week["phase"].title(), f"{week['weeks_to_race']} weeks to race"),
        (
            "Load target",
            f"{int(week['load_target_low'])}–{int(week['load_target_high'])}",
            "weekly load band",
        ),
    ]
    card_html = "".join(
        f'<div class="card"><div class="card-label">{label}</div>'
        f'<div class="card-value">{value}</div><div class="card-sub">{sub}</div></div>'
        for label, value, sub in cards
    )

    lt1_caveat = ""
    if not plan.zones.empty and _clean_int(plan.zones.iloc[0].get("lt1_hr")) is None:
        lt1_caveat = (
            " LT1 was not captured by the lab test, so the Recovery/Endurance "
            "boundary is approximate."
        )

    rationale = escape(str(week.get("rationale") or ""))
    model = escape(str(week.get("model") or ""))
    methodology = escape(str(week.get("methodology") or ""))
    methodology_html = f'<p class="methodology">{methodology}</p>' if methodology else ""

    return f"""<h2>Training plan</h2>
  <div class="cards">{card_html}</div>
  <div class="panel">
    <div class="section-label">Periodization</div>
    {_phase_strip(race_date, week_start)}
  </div>
  <div class="panel">
    <div class="section-label">Week of {week_start.strftime('%d %b %Y')}</div>
    <p class="plan-hint">Click a session to see the full breakdown.</p>
    {_plan_list(plan.sessions)}
    <p class="rationale"><b>Coach's note:</b> {rationale}</p>
  </div>
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

    Returns
    -------
    str
        A complete, self-contained HTML document.
    """
    chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")
    # plotly.js is already loaded by the chart above; don't ship it twice.
    zones_chart_html = zones_fig.to_html(full_html=False, include_plotlyjs=False)
    pace_chart_html = pace_fig.to_html(full_html=False, include_plotlyjs=False)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    as_of = snapshot.date.strftime("%A, %d %B %Y")
    plan_html = _plan_section(plan) if plan is not None else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Training Dashboard</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
         margin: 0; background: #f8fafc; color: #0f172a; }}
  .wrap {{ max-width: 1100px; margin: 0 auto; padding: 24px 18px 60px; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 2px; }}
  .as-of {{ color: #64748b; font-size: 0.9rem; margin-bottom: 20px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
           gap: 12px; margin-bottom: 24px; }}
  .card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
          padding: 16px 18px; }}
  .card-label {{ font-size: 0.8rem; color: #64748b; }}
  .card-value {{ font-size: 1.8rem; font-weight: 600; margin: 4px 0; }}
  .card-sub {{ font-size: 0.8rem; color: #475569; }}
  .panel {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
           padding: 10px; margin-bottom: 24px; }}
  h2 {{ font-size: 1.1rem; margin: 8px 4px 12px; }}
  table.weekly {{ width: 100%; border-collapse: collapse; font-size: 0.92rem; }}
  table.weekly th, table.weekly td {{ text-align: left; padding: 8px 10px;
          border-bottom: 1px solid #e2e8f0; }}
  table.weekly th {{ color: #64748b; font-weight: 600; }}
  table.weekly tr:first-child td {{ font-weight: 600; }}
  .section-label {{ font-size: 0.8rem; color: #64748b; font-weight: 600;
          text-transform: uppercase; letter-spacing: 0.03em; margin: 4px 6px 10px; }}
  .phase-strip {{ display: flex; gap: 6px; overflow-x: auto; padding: 4px 2px 8px; }}
  .phase-cell {{ flex: 0 0 auto; min-width: 78px; border-radius: 10px; padding: 8px 10px;
          text-align: center; background: #fff; }}
  .phase-dot {{ width: 100%; height: 5px; border-radius: 3px; margin-bottom: 6px; }}
  .phase-wk {{ font-size: 0.78rem; font-weight: 600; }}
  .phase-name {{ font-size: 0.72rem; color: #64748b; text-transform: capitalize; }}
  .plan-hint {{ font-size: 0.78rem; color: #94a3b8; margin: -2px 6px 12px; }}
  .sess-list {{ display: flex; flex-direction: column; gap: 8px; }}
  .sess {{ border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; }}
  .sess-row {{ display: flex; align-items: center; gap: 12px; padding: 12px 14px;
          cursor: pointer; background: #fff; }}
  .sess-row:hover {{ background: #f8fafc; }}
  .zdot {{ width: 10px; height: 10px; border-radius: 50%; flex: none; }}
  .sess-main {{ flex: 1; min-width: 0; }}
  .sess-title {{ font-size: 0.95rem; font-weight: 600; }}
  .sess-meta {{ font-size: 0.8rem; color: #64748b; margin-top: 2px; }}
  .ibadge {{ font-size: 0.72rem; font-weight: 600; border-radius: 6px; padding: 2px 8px;
          text-transform: capitalize; white-space: nowrap; }}
  .sdot {{ width: 8px; height: 8px; border-radius: 50%; flex: none; }}
  .chev {{ color: #94a3b8; font-size: 0.7rem; transition: transform 0.15s; }}
  .sess-row.open .chev {{ transform: rotate(180deg); }}
  .sess-body {{ display: none; padding: 4px 14px 14px 36px; background: #fff;
          border-top: 1px solid #f1f5f9; }}
  .sess-body.open {{ display: block; }}
  .sess-step {{ display: flex; gap: 10px; align-items: baseline; padding: 5px 0; }}
  .sess-step .sk {{ min-width: 84px; font-size: 0.78rem; color: #64748b; }}
  .sess-step .sv {{ font-size: 0.88rem; color: #334155; line-height: 1.5; }}
  .seg-list {{ border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; margin-top: 4px; }}
  .seg-band {{ padding: 6px 12px; font-size: 0.74rem; font-weight: 600; color: #fff;
          letter-spacing: 0.03em; }}
  .seg-row {{ display: flex; align-items: center; gap: 10px; padding: 9px 12px;
          border-top: 1px solid #f1f5f9; }}
  .seg-list > .seg-row:first-child {{ border-top: none; }}
  .seg-num {{ width: 16px; text-align: center; color: #94a3b8; font-size: 0.78rem; flex: none; }}
  .seg-main {{ flex: 1; min-width: 0; }}
  .seg-metric {{ font-size: 0.9rem; color: #0f172a; }}
  .seg-metric b {{ font-weight: 600; }}
  .seg-load {{ color: #334155; font-weight: 600; }}
  .seg-target {{ font-size: 0.78rem; color: #64748b; margin-top: 1px; }}
  .seg-tag {{ font-size: 0.66rem; font-weight: 600; letter-spacing: 0.04em; flex: none; }}
  .sess-purpose {{ font-size: 0.8rem; color: #64748b; font-style: italic;
          margin-top: 8px; padding-top: 8px; border-top: 1px solid #f1f5f9; }}
  .sess-why {{ font-size: 0.84rem; color: #334155; margin-top: 8px; padding: 8px 10px;
          background: #f8fafc; border-left: 3px solid #cbd5e1; border-radius: 0; }}
  .why-label {{ display: block; font-size: 0.68rem; font-weight: 600; color: #64748b;
          text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 2px; }}
  .methodology {{ font-size: 0.88rem; color: #334155; line-height: 1.6; margin: 0 4px 14px; }}
  .src-list {{ display: flex; flex-direction: column; gap: 6px; }}
  .src {{ display: flex; align-items: center; gap: 10px; padding: 8px 10px;
          border: 1px solid #e2e8f0; border-radius: 8px; }}
  .src-main {{ flex: 1; min-width: 0; }}
  .src-claim {{ font-size: 0.86rem; color: #334155; }}
  .src-cite {{ font-size: 0.76rem; color: #2563eb; text-decoration: none; }}
  .src-cite:hover {{ text-decoration: underline; }}
  .tier {{ font-size: 0.68rem; font-weight: 600; border-radius: 6px; padding: 2px 8px;
          text-transform: capitalize; white-space: nowrap; }}
  .src-note {{ font-size: 0.76rem; color: #94a3b8; margin: 12px 4px 2px; line-height: 1.5; }}
  .focus {{ font-size: 0.7rem; background: #eef2ff; color: #4338ca; border-radius: 6px;
          padding: 1px 6px; margin-left: 6px; }}
  .badge {{ color: #fff; font-size: 0.72rem; font-weight: 600; border-radius: 6px;
          padding: 2px 8px; text-transform: capitalize; }}
  .rationale {{ font-size: 0.86rem; color: #334155; margin: 14px 4px 4px; }}
  .zone-note {{ font-size: 0.78rem; color: #94a3b8; margin: 10px 4px 2px; }}
  footer {{ color: #94a3b8; font-size: 0.8rem; margin-top: 28px; }}
  /* tabs */
  .tabs {{ display: flex; gap: 4px; border-bottom: 1px solid #e2e8f0; margin-bottom: 20px; }}
  .tab-btn {{ background: none; border: none; padding: 10px 16px; font-size: 0.95rem;
          color: #64748b; cursor: pointer; border-bottom: 2px solid transparent; }}
  .tab-btn:hover {{ color: #0f172a; }}
  .tab-btn.active {{ color: #2563eb; border-bottom-color: #2563eb; font-weight: 600; }}
  .tab-panel {{ display: none; }}
  .tab-panel.active {{ display: block; }}
  /* zone comparison table */
  table.zones {{ width: 100%; border-collapse: collapse; font-size: 0.92rem; }}
  table.zones th, table.zones td {{ text-align: center; padding: 8px 10px;
          border-bottom: 1px solid #e2e8f0; }}
  table.zones th:first-child, table.zones td:first-child {{ text-align: left; }}
  table.zones th {{ color: #64748b; font-weight: 600; }}
  table.zones .muted {{ color: #94a3b8; font-size: 0.85rem; }}
  .callout {{ background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 10px;
          padding: 12px 16px; margin: 0 0 18px; font-size: 0.95rem; color: #1e3a8a; }}
  .note {{ color: #475569; font-size: 0.88rem; line-height: 1.5; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Training Dashboard</h1>
  <div class="as-of">As of {as_of}</div>

  <div class="tabs">
    <button class="tab-btn active" data-tab="training">Training load</button>
    <button class="tab-btn" data-tab="plan">Training plan</button>
    <button class="tab-btn" data-tab="zones">Zones</button>
  </div>

  <div class="tab-panel active" id="tab-training">
    {_snapshot_cards(snapshot)}
    <div class="panel">{chart_html}</div>
    <h2>Weekly summary</h2>
    <div class="panel">{_weekly_table(weekly)}</div>
  </div>

  <div class="tab-panel" id="tab-plan">
    {plan_html}
  </div>

  <div class="tab-panel" id="tab-zones">
    <h2>Heart-rate zones: lab vs platforms</h2>
    <div class="callout">{zones.example_hr_callout(165)}</div>
    <div class="panel">{zones_chart_html}</div>
    <div class="panel">{zones.zone_table_html()}</div>
    <p class="note">Your <strong>Lab</strong> zones are anchored on the measured
    anaerobic threshold (LT2 ≈ {zones.LAB_LT2_HR} bpm) from the 2026-06-19 lactate
    test. <strong>Garmin</strong> and <strong>Strava</strong> anchor on an assumed
    maximum heart rate (~200 and ~190), not threshold — so their hard zones sit
    well above your real ones. Garmin even stores a threshold HR of 175 but uses
    %max-HR for the zones. Net effect: a heart rate the lab calls threshold/VO2max
    still reads as Z3-Z4 on the platforms.</p>

    <h2 style="margin-top:28px">Pace zones: lab vs Strava</h2>
    <div class="callout">{zones.example_pace_callout("4:30")}</div>
    <div class="panel">{pace_chart_html}</div>
    <div class="panel">{zones.pace_table_html()}</div>
    <p class="note">Lab pace zones come from the same test (threshold pace
    ≈ {zones.format_pace(zones.LAB_LT2_PACE_S)}/km). <strong>Strava</strong> derives
    its pace zones from an <em>estimated</em> 5 km time (19:29), which runs
    optimistic, so its zones sit faster than the measured ones.
    <strong>Garmin</strong> does not publish running pace zones for this athlete.</p>
  </div>

  <footer>Generated {generated} · Garmin training load + HRV · TSB bands follow
  TrainingPeaks conventions. CTL warm-up window shaded; treat early TSB with caution.</footer>
</div>
<script>
  document.querySelectorAll('.tab-btn').forEach(function (btn) {{
    btn.addEventListener('click', function () {{
      document.querySelectorAll('.tab-btn').forEach(function (b) {{ b.classList.remove('active'); }});
      document.querySelectorAll('.tab-panel').forEach(function (p) {{ p.classList.remove('active'); }});
      btn.classList.add('active');
      document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
      window.dispatchEvent(new Event('resize'));  // let Plotly size the hidden chart
    }});
  }});
  document.querySelectorAll('.sess-row').forEach(function (row) {{
    row.addEventListener('click', function () {{
      row.classList.toggle('open');
      document.getElementById('psess' + row.dataset.sess).classList.toggle('open');
    }});
  }});
</script>
</body>
</html>"""
