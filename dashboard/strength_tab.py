"""Render the strength tab: load progression, weekly volume, the latest session.

Consumes the aggregations in :mod:`dashboard.strength_metrics` and emits Plotly
figures plus one self-contained HTML fragment, the same way
:mod:`dashboard.body_tab` supplies the body tab. ``build`` wires the fragment
into the page, so :mod:`dashboard.render` never has to know this module exists.

Three presentation rules follow from what this data actually is:

* **Nothing is named on a guess.** Every lift on the progression chart comes
  from a settled identification. The guessed sets are not drawn as a fainter
  version of the same thing -- they are counted in the totals and stated in
  words, because a dashed line through a mislabelled 120 kg "shrug" would read
  as a lift that does not exist.
* **The charts start where the loads do.** No weight was recorded before
  2026-07-01, so a panel spanning the whole log would draw four months of zero
  tonnage and read as detraining rather than as an absence of data.
* **Movement pattern is a stack, not a filter.** The question a volume chart
  answers here is whether the programme is balanced, so every pattern is shown
  together and none is dropped -- including the ``Other`` bucket that holds the
  work Garmin could not attribute.
"""

from __future__ import annotations

from datetime import date
from html import escape

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dashboard import strength_metrics as sm
from dashboard import theme

_COLOR_NEUTRAL = "#94a3b8"
_COLOR_GOOD = "#16a34a"
_COLOR_WARN = "#b45309"

# One colour per movement pattern, mid-luminance so the stack holds up on warm
# paper and on near-black alike. ``Other`` is deliberately the grey: it is the
# bucket for work that was recorded but not attributed, and it should read as
# quieter than the patterns that were.
_PATTERN_COLORS = {
    "Squat": "#3D7BE0",
    "Hinge": "#F08A2E",
    "Push": "#2DA85E",
    "Pull": "#8B62E8",
    "Carry": "#0E7C86",
    "Core": "#D6446F",
    sm.OTHER_PATTERN: "#98A1B0",
}

# Progression lines, assigned in the order :func:`strength_metrics.trending_lifts`
# returns -- heaviest lift first, so the barbell lifts keep the strong colours.
_LIFT_COLORS = ("#3D7BE0", "#F08A2E", "#2DA85E", "#8B62E8", "#D6446F", "#0E7C86")

_COLOR_SETS = "#17150F"

_HOVER_DAY = "%a %d %b %Y"


def _layout(hovermode: str = "x unified", **overrides) -> dict:
    """Return the shared chart layout with this tab's margins applied.

    Defaults to ``"x unified"`` for the reason the 2026-09-08 hover fix
    established: every figure here carries more than one series over a shared
    time axis, which is exactly the case where ``"closest"`` answers with the
    nearest *point* rather than with the series being pointed at.

    Parameters
    ----------
    hovermode : str, optional
        Plotly hover mode.
    **overrides
        Per-figure layout keys, typically ``height`` and ``title``.

    Returns
    -------
    dict
        Keyword arguments for ``Figure.update_layout``.
    """
    margin = overrides.pop("margin", dict(l=58, r=30, t=58, b=40))
    legend = overrides.pop(
        "legend",
        dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
    )
    return theme.chart_layout(
        margin=margin, hovermode=hovermode, legend=legend, **overrides
    )


def build_progression_figure(progression: pd.DataFrame, lifts: list[str]) -> go.Figure:
    """Build the top-set progression chart, one line per lift.

    The top set rather than the mean or the total, because that is what
    progressive overload is read off: a heavy triple plus two back-off sets is
    a heavier session than three sets at the back-off weight, and an average
    says the reverse.

    Parameters
    ----------
    progression : pandas.DataFrame
        Output of :func:`dashboard.strength_metrics.top_sets`.
    lifts : list of str
        Labels to draw, from
        :func:`dashboard.strength_metrics.trending_lifts`.

    Returns
    -------
    plotly.graph_objects.Figure
        One line and marker series per lift.
    """
    fig = go.Figure()

    for index, lift in enumerate(lifts):
        rows = progression[progression["label"] == lift]
        if rows.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=pd.to_datetime(rows["day"]),
                y=rows["weight_kg"],
                name=lift,
                mode="lines+markers",
                line=dict(color=_LIFT_COLORS[index % len(_LIFT_COLORS)], width=2.5),
                marker=dict(size=7),
                # The rep count rides along because a top set is a weight *and*
                # a rep count: 130 x 3 and 130 x 5 are different sessions, and
                # a chart of kilograms alone would call them the same one.
                customdata=rows[["reps", "sets"]],
                xhoverformat=_HOVER_DAY,
                hovertemplate="%{y:g} kg x %{customdata[0]:.0f} · %{customdata[1]:.0f} sets",
            )
        )

    fig.update_layout(**_layout(height=380, title="Top set by lift"))
    # Not zero-based: the working lifts sit between 40 and 140 kg, and a
    # zero-based axis compresses every progression into the top third.
    fig.update_yaxes(title_text="Top set (kg)")
    return fig


def build_volume_figure(weekly: pd.DataFrame) -> go.Figure:
    """Build weekly tonnage stacked by movement pattern, with the set count over it.

    Two things have to be read together and neither substitutes for the other:
    tonnage says how much was moved, set count says how much was done. A week
    of heavy triples and a week of high-rep circuits can carry the same
    tonnage at very different set counts, and reading either alone gets that
    week wrong.

    Parameters
    ----------
    weekly : pandas.DataFrame
        Output of :func:`dashboard.strength_metrics.weekly_volume`.

    Returns
    -------
    plotly.graph_objects.Figure
        Stacked bars on the left axis, the set-count line on the right.
    """
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    if not weekly.empty:
        for pattern in sm.PATTERN_ORDER:
            rows = weekly[weekly["pattern"] == pattern]
            if rows.empty:
                continue
            fig.add_trace(
                go.Bar(
                    x=pd.to_datetime(rows["week_start"]),
                    y=rows["volume_kg"],
                    name=pattern,
                    marker_color=_PATTERN_COLORS.get(pattern, _COLOR_NEUTRAL),
                    xhoverformat=_HOVER_DAY,
                    hovertemplate="%{y:,.0f} kg",
                ),
                secondary_y=False,
            )

        totals = (
            weekly.groupby("week_start", as_index=False)["sets"].sum().sort_values("week_start")
        )
        fig.add_trace(
            go.Scatter(
                x=pd.to_datetime(totals["week_start"]),
                y=totals["sets"],
                name="Working sets",
                mode="lines+markers",
                line=dict(color=_COLOR_SETS, width=2),
                marker=dict(size=6),
                xhoverformat=_HOVER_DAY,
                hovertemplate="%{y:.0f} sets",
            ),
            secondary_y=True,
        )

    # The legend goes below rather than into the top margin, which is where
    # every other figure on the page puts it. Seven patterns plus the set-count
    # line wrap onto two rows and run straight through the title, and the title
    # is what says the bars are tonnage rather than sets.
    fig.update_layout(
        **_layout(
            height=420,
            title="Weekly volume by movement pattern",
            margin=dict(l=58, r=58, t=58, b=88),
            legend=dict(orientation="h", yanchor="top", y=-0.16, xanchor="left", x=0),
        )
    )
    fig.update_layout(barmode="stack")
    fig.update_yaxes(title_text="Tonnage (kg)", secondary_y=False, rangemode="tozero")
    fig.update_yaxes(
        title_text="Working sets", secondary_y=True, rangemode="tozero", showgrid=False
    )
    return fig


def _cards(headline: sm.StrengthHeadline) -> str:
    """Render the strength header cards."""
    heaviest = (
        "—" if headline.heaviest_kg is None else f"{headline.heaviest_kg:g} kg"
    )
    heaviest_sub = (
        f"<span style='color:{_COLOR_NEUTRAL}'>nothing settled in the "
        f"last {sm.CURRENT_LOAD_WINDOW_DAYS} days</span>"
        if headline.heaviest_lift is None
        else f"<span style='color:{_COLOR_NEUTRAL}'>"
             f"{escape(headline.heaviest_lift)}, "
             f"{headline.heaviest_on:%d %b}</span>"
    )

    settled_share = (
        0.0 if not headline.active_sets
        else 100.0 * headline.settled_sets / headline.active_sets
    )
    settled_sub = (
        f"<span style='color:{_COLOR_NEUTRAL}'>{headline.settled_sets} of "
        f"{headline.active_sets} working sets</span>"
    )

    cards = [
        ("Sessions (28 d)", f"{headline.sessions_28d}",
         f"<span style='color:{_COLOR_NEUTRAL}'>with sets on record</span>"),
        ("Tonnage (7 d)", f"{headline.tonnage_7d:,.0f}",
         f"<span style='color:{_COLOR_NEUTRAL}'>kg, weight × reps</span>"),
        ("Heaviest lift", heaviest, heaviest_sub),
        ("Identified", f"{settled_share:.0f}%", settled_sub),
        ("Lifted all-time", f"{headline.total_tonnage_kg / 1000.0:,.1f}",
         f"<span style='color:{_COLOR_NEUTRAL}'>tonnes since loads were "
         f"logged</span>"),
    ]
    rendered = "".join(
        f"<div class='card'><div class='card-label'>{escape(label)}</div>"
        f"<div class='card-value'>{escape(value)}</div>"
        f"<div class='card-sub'>{sub}</div></div>"
        for label, value, sub in cards
    )
    return f"<div class='cards'>{rendered}</div>"


def _load_check_table(checks: list[sm.LoadCheck]) -> str:
    """Render the prescribed working loads against what was actually lifted."""
    if not checks:
        return ""

    rows = []
    for check in checks:
        if check.measured_kg is None:
            measured = "<td colspan='2' class='num'>—</td>"
            verdict = (
                f"<span style='color:{_COLOR_NEUTRAL}'>not lifted in the "
                f"last {sm.CURRENT_LOAD_WINDOW_DAYS} days</span>"
            )
        else:
            measured = (
                f"<td class='num'>{check.measured_kg:g} kg</td>"
                f"<td>{escape(check.measured_lift or '')}, "
                f"{check.measured_on:%d %b}</td>"
            )
            gap = check.gap_kg or 0.0
            if not check.is_stale:
                verdict = f"<span style='color:{_COLOR_GOOD}'>config matches</span>"
            elif gap > 0:
                verdict = (
                    f"<span style='color:{_COLOR_WARN}'>lifting {gap:+g} kg "
                    f"over config — raise it</span>"
                )
            else:
                verdict = (
                    f"<span style='color:{_COLOR_NEUTRAL}'>{gap:+g} kg under "
                    f"config</span>"
                )
        rows.append(
            f"<tr><td>{escape(check.label)}</td>"
            f"<td class='num'>{check.config_kg:g} kg</td>"
            f"{measured}<td>{verdict}</td></tr>"
        )

    header = (
        "<tr><th>Lift</th><th class='num'>Config</th>"
        "<th class='num'>Heaviest settled</th><th>From</th><th></th></tr>"
    )
    return f"<table class='weekly'>{header}{''.join(rows)}</table>"


def _session_table(detail: pd.DataFrame) -> str:
    """Render one session as a table of exercises and the sets behind them."""
    if detail.empty:
        return "<p class='note'>No exercises recorded for this session.</p>"

    rows = []
    for _, row in detail.iterrows():
        volume = "—" if pd.isna(row["volume_kg"]) or not row["volume_kg"] else (
            f"{row['volume_kg']:,.0f} kg"
        )
        flag = (
            "" if row["settled"]
            else f" <span style='color:{_COLOR_NEUTRAL}' title='Garmin guessed "
                 f"this movement'>?</span>"
        )
        rows.append(
            f"<tr><td>{escape(str(row['label']))}{flag}</td>"
            f"<td>{escape(str(row['pattern']))}</td>"
            f"<td>{escape(str(row['set_detail']))}</td>"
            f"<td class='num'>{volume}</td></tr>"
        )

    header = (
        "<tr><th>Exercise</th><th>Pattern</th><th>Sets</th>"
        "<th class='num'>Volume</th></tr>"
    )
    return f"<table class='weekly'>{header}{''.join(rows)}</table>"


def _empty_html() -> str:
    """Render the tab before the exercise tables have anything in them."""
    return (
        "<h2>Strength</h2>"
        "<div class='panel'><p>No exercise data on record yet.</p>"
        "<p class='note'>This tab reads <code>garmin_activity_exercises</code> "
        "and <code>garmin_exercise_sets</code>. The first rides along in the "
        "activity payload and fills itself on the next ingest; the second needs "
        "one Garmin call per session, so the history is loaded once with "
        "<code>python -m scripts.backfill_exercise_sets</code>.</p></div>"
    )


def strength_section_html(
    exercises: pd.DataFrame, sets: pd.DataFrame, today: date
) -> str:
    """Render the whole strength tab: cards, charts, load checks and caveats.

    Parameters
    ----------
    exercises : pandas.DataFrame
        Output of :func:`dashboard.strength_metrics.prepare_exercises`.
    sets : pandas.DataFrame
        Output of :func:`dashboard.strength_metrics.prepare_sets`.
    today : datetime.date
        The day the dashboard is being built for.

    Returns
    -------
    str
        An HTML fragment for the strength tab panel.
    """
    if exercises.empty:
        return _empty_html()

    headline = sm.headline(exercises, sets, today)
    progression = sm.top_sets(sets)
    lifts = sm.trending_lifts(progression)
    weight_era = sm.first_weighted_day(sets)
    weekly = sm.weekly_volume(exercises, since=weight_era)
    checks = sm.load_checks(sets, today)

    latest_id = exercises.iloc[-1]["activity_id"]
    latest_day = exercises.iloc[-1]["day"]
    detail = sm.session_detail(exercises, sets, latest_id)

    volume_chart = build_volume_figure(weekly).to_html(
        full_html=False, include_plotlyjs=False
    )

    guessed = headline.active_sets - headline.settled_sets
    era_text = "" if weight_era is None else f"{weight_era:%d %B %Y}"

    chart_block = (
        "<p class='note'>No lift yet has settled top sets on "
        f"{sm.MIN_SESSIONS_FOR_TREND} separate days, so there is nothing to "
        "draw a progression through.</p>"
        if not lifts
        else f"""<div class="panel">{
            build_progression_figure(progression, lifts).to_html(
                full_html=False, include_plotlyjs=False)
        }</div>
  <p class="note">The heaviest working set of each session, which is what
  progressive overload is actually read off — a heavy triple followed by two
  back-off sets is a heavier session than three sets at the back-off weight,
  and an average would say the opposite. Hover for the reps behind the top set
  and how many sets of that lift the session held; <strong>130 × 3 and 130 × 5
  are not the same session</strong>, so the weight alone does not settle
  whether a lift moved.</p>"""
    )
    # The guess count is stated whether or not there is a chart. It matters
    # most in the case where there is none: a page that just says "nothing to
    # draw" does not explain that the sets exist and Garmin only guessed at
    # what they were.
    progression_block = f"""{chart_block}
  <p class="src-note">Only lifts Garmin identified with certainty appear, and
  only on days it was certain. {guessed} of {headline.active_sets} working sets
  on record carry a guess instead — three candidate movements with the best one
  below 100% — and none of them is drawn here, not even faintly. The guesses go
  visibly wrong exactly where they are heavy: a 120 kg &ldquo;shrug&rdquo; at
  45% confidence and a 110 kg &ldquo;bench dip&rdquo; at 46% are compound lifts
  wearing a label the watch picked from a shortlist. Naming a movement in
  Garmin Connect settles it, and it appears here from the next ingest.</p>"""

    checks_block = ""
    if checks:
        stale = [c for c in checks if c.is_stale and (c.gap_kg or 0) > 0]
        callout = ""
        if stale:
            named = ", ".join(f"{c.label.lower()} ({c.measured_kg:g} kg)" for c in stale)
            callout = (
                f"<div class='callout'>You are lifting more than "
                f"<code>ATHLETE_LOADS</code> says on <strong>{escape(named)}"
                f"</strong>. Every strength prescription in a generated block is "
                f"written against that constant, so until it is raised the next "
                f"block prescribes a load you have already passed.</div>"
            )
        checks_block = f"""<h2 style="margin-top:28px">Prescribed vs lifted</h2>
  {callout}
  <div class="panel">{_load_check_table(checks)}</div>
  <p class="note"><code>plan/config.py</code>'s <code>ATHLETE_LOADS</code> is
  hand-maintained, and it is what every generated strength session is written
  against. A load that has moved on the gym floor but not in the config quietly
  under-writes the next block — the same failure the 2026-09-06 re-anchor found
  on the running side, where every threshold session of a block had been
  ~20 s/km too easy because the constant was stale.</p>
  <p class="src-note">Only the four lifts recorded as an unambiguous total in
  kilograms are checked, the same four the relative-strength cards use: the
  weighted pull-up is recorded as &ldquo;bodyweight +5 kg&rdquo;, and step-ups
  and dumbbell bench press are recorded per hand, so in each case the figure in
  the prescription is not the load that was on the bar. Each row names the
  movement and date behind its measured figure, because Garmin's confidence
  covers the <em>movement</em> it identified, not the <em>weight</em> that was
  entered against it.</p>"""

    return f"""<h2>Strength</h2>
  {_cards(headline)}
  <h2 style="margin-top:28px">Load progression</h2>
  {progression_block}
  {checks_block}

  <h2 style="margin-top:28px">Volume</h2>
  <div class="panel">{volume_chart}</div>
  <p class="note">Tonnage is weight × reps summed over the week, stacked by the
  movement pattern it trained, with the working-set count over the top. The two
  answer different questions and neither stands in for the other: a week of
  heavy triples and a week of high-rep circuits can carry the same tonnage at
  very different set counts. <strong>Read the stack for balance</strong> — a
  build that is all hinge and no pull shows up here as a shape, not as a
  number.</p>
  <p class="src-note">This panel starts on {era_text}, the first day a load was
  recorded at all. The {len(exercises['activity_id'].unique())} sessions on
  record reach back to March, but the earlier ones logged sets and reps without
  weights, and drawing them would put months of zero-tonnage bars on the chart
  that read as detraining rather than as an absence of data. The grey
  <em>Other</em> band is work Garmin recorded but could not attribute to a
  movement — it is counted, because it was trained, and never named.</p>

  <h2 style="margin-top:28px">Latest session — {latest_day:%A, %d %B %Y}</h2>
  <div class="panel">{_session_table(detail)}</div>
  <p class="note">Every exercise of the most recent set-bearing session, with
  the sets behind it. Identical sets are collapsed (<code>3 × 8 @ 110 kg</code>);
  where they differ, each is spelled out, so a working-up sequence stays legible
  as one. A <strong>?</strong> marks an exercise whose sets Garmin did not
  identify with certainty.</p>"""
