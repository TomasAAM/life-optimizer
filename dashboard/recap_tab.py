"""The Recap tab: each month as a set of Instagram-story cards.

Every card is a fixed 360 x 640 CSS-pixel frame -- exactly 9:16 -- so a PNG
exported at a pixel ratio of 3 is a 1080 x 1920 story with nothing cropped.
The viewer scales the stage around the cards with a CSS transform rather than
resizing the cards themselves, which keeps the exported image identical on a
phone and on a laptop.

The cards are styled as a printed race poster: paper, black ink and one signal
orange, set in a condensed grotesque. They carry their own fixed palette rather
than the page's light and dark tokens, because an image meant to leave the
dashboard has to look the same whichever scheme the browser was in. How each
number is derived is explained under the viewer, not printed on the images.

Three things html-to-image does not carry into the exported image, each of
which the markup below works around: stylesheet rules on SVG ``<text>``, CSS
counters, and rules whose colour comes from a page-level custom property.

The page is static, so every month is rendered at build time and switched
client-side, the same way the plan tab's week strip works.
"""

from __future__ import annotations

from html import escape

from dashboard import recap_metrics as rm
from plan.pace import seconds_to_pace

# Pinned rather than "latest" so a release can never change the export
# silently. ``htmlToImage`` is the global the UMD build defines.
HTML_TO_IMAGE_SRC = "https://cdn.jsdelivr.net/npm/html-to-image@1.11.13/dist/html-to-image.js"

# Archivo's width axis gives the condensed poster numerals and the normal-width
# text from one family.
RECAP_FONTS_HREF = (
    "https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,300..900&display=swap"
)

CARD_WIDTH_PX = 360
CARD_HEIGHT_PX = 640
EXPORT_WIDTH_PX = 1080

PAPER = "#ECE6DA"
INK = "#16130F"
SIGNAL = "#FF4D00"

KIND_LABEL = {
    rm.KIND_RUN: ("run", "runs"),
    rm.KIND_GYM: ("gym", "gym"),
    rm.KIND_HYROX: ("Hyrox", "Hyrox"),
    rm.KIND_OTHER: ("other", "other"),
}

_GRAIN = (
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' "
    "height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' "
    "baseFrequency='.85' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' "
    "height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")"
)


def _change(now: float, before: float, prev_name: str, unit: str = "%",
            decimals: int = 0) -> str:
    """Plain-text change against the comparison span, e.g. ``"+3% on Aug"``.

    Parameters
    ----------
    now, before : float
        This month's value and the comparison span's.
    prev_name : str
        Short name of the previous month.
    unit : str, optional
        ``"%"`` for a relative change, anything else for an absolute one with
        that unit appended.
    decimals : int, optional
        Decimals shown for an absolute change.

    Returns
    -------
    str
        The change, or an empty string when there is no baseline.

    Examples
    --------
    >>> _change(204, 198, "Aug")
    '+3% on Aug'
    >>> _change(7, 8, "Aug", unit="", decimals=0)
    '−1 on Aug'
    """
    if unit == "%":
        if before <= 0:
            return ""
        change = 100.0 * (now - before) / before
        text = f"{abs(change):.0f}%"
        shown = round(change)
    else:
        change = now - before
        text = f"{abs(change):.{decimals}f}{unit}"
        shown = round(change, decimals)
    if shown == 0:
        return f"same as {prev_name}"
    sign = "+" if change > 0 else "−"
    return f"{sign}{text} on {prev_name}"


def _fmt_km(km: float) -> str:
    """Kilometres with one decimal under 100 and none above."""
    return f"{km:.0f}" if km >= 100 else f"{km:.1f}"


def _prev(recap: rm.MonthRecap) -> str:
    """Short name of the month before the recapped one."""
    return rm.previous_month(recap.month).strftime("%b")


# The title is set at 66 px, at which nine condensed capitals ("SEPTEMBER")
# fill the card's width; longer titles scale down so they never run off it.
_TITLE_PX = 66
_TITLE_FITS = 9


def _title_fit(title: str) -> str:
    """Inline font size for a title longer than the card's width allows."""
    if len(title) <= _TITLE_FITS:
        return ""
    return f" style='font-size:{_TITLE_PX * _TITLE_FITS / len(title):.0f}px'"


def _card(recap: rm.MonthRecap, card_id: str, title: str, body: str) -> str:
    """Wrap a card body in the shared 9:16 poster frame.

    The page number is left as a ``__PAGE__`` placeholder and filled in by
    :func:`story_cards`, which is the only place that knows how many cards the
    month ends up with.
    """
    when = f"{recap.month:%m} / {recap.month:%Y}" + (" · so far" if recap.in_progress else "")
    return (
        f"<article class='story-card' data-card='{card_id}' "
        f"data-file='recap-{recap.key}-{card_id}.png' aria-label='{escape(title)}'>"
        f"<div class='p-grain'></div>"
        f"<div class='p-top'><span>Training log</span><span>{when}</span>"
        f"<span>__PAGE__</span></div>"
        f"<h1 class='p-title'{_title_fit(title)}>{escape(title)}</h1>"
        f"<div class='p-body'>{body}</div></article>"
    )


def _cell(mark: rm.DayMark, through) -> str:
    """One calendar square. Every kind of session gets its own treatment."""
    day = f"<b>{mark.day.day}</b>"
    if mark.day > through:
        return f"<i class='c future'>{day}</i>"
    kinds = set(mark.kinds)
    if not kinds:
        return f"<i class='c rest'>{day}</i>"

    if rm.KIND_RUN in kinds:
        extras = [k for k in (rm.KIND_GYM, rm.KIND_HYROX) if k in kinds]
        if rm.KIND_OTHER in kinds:
            extras.append(rm.KIND_OTHER)
        band = ""
        if extras:
            short = len(extras) > 1
            band = "<u class='band'>" + "".join(
                f"<span class='t-{k}'>{_tag(k, short)}</span>" for k in extras
            ) + "</u>"
        return (f"<i class='c run{' has-band' if band else ''}'>{day}"
                f"<em>{mark.run_km:.0f}</em>{band}</i>")

    if rm.KIND_HYROX in kinds:
        if rm.KIND_GYM in kinds:
            return (f"<i class='c hyrox has-band'>{day}<s>HYROX</s>"
                    f"<u class='band'><span class='t-gym'>GYM</span></u></i>")
        return f"<i class='c hyrox'>{day}<s>HYROX</s></i>"
    if rm.KIND_GYM in kinds:
        # Labelled on the same band as a run double: text laid straight onto
        # the hatching is unreadable.
        return (f"<i class='c gym'><span class='hatch'></span>{day}"
                f"<u class='band'><span class='t-gym'>GYM</span></u></i>")
    label = escape(mark.others[0].upper()) if mark.others else "OTHER"
    return f"<i class='c other'>{day}<s>{label}</s></i>"


def _tag(kind: str, short: bool) -> str:
    """Band label for a session done on the same day as a run."""
    if kind == rm.KIND_HYROX:
        return "HX" if short else "HYROX"
    if kind == rm.KIND_GYM:
        return "GYM"
    return "+"


def _calendar_html(recap: rm.MonthRecap) -> str:
    """Monday-first month grid with a legend that doubles as the session count."""
    lead = "".join("<i class='c pad'></i>" for _ in range(recap.month.weekday()))
    cells = "".join(_cell(m, recap.through) for m in recap.calendar)
    rows = -(-(recap.month.weekday() + len(recap.calendar)) // 7)
    dow = "".join(f"<span>{d}</span>" for d in ("M", "T", "W", "T", "F", "S", "S"))
    legend = "".join(
        f"<span><i class='sw sw-{k}'></i>{recap.kind_counts.get(k, 0)} "
        f"{KIND_LABEL[k][0 if recap.kind_counts.get(k, 0) == 1 else 1]}</span>"
        for k in rm.KIND_ORDER
    )
    cls = "cal rows-6" if rows > 5 else "cal"
    return (f"<div class='dow'>{dow}</div><div class='{cls}'>{lead}{cells}</div>"
            f"<div class='legend'>{legend}</div>")


def _row(items: list[tuple[str, str]]) -> str:
    """A ruled row of figures, each with a small caption underneath."""
    cols = "".join(f"<div><strong>{v}</strong>{escape(c)}</div>" for v, c in items)
    return f"<div class='p-row cols-{len(items)}'>{cols}</div>"


def _cover_card(recap: rm.MonthRecap) -> str:
    """Card 1: the month at a glance, and every day of it."""
    run = recap.running
    change = _change(run.km, run.prev_km, _prev(recap))
    body = (
        f"<div class='big'><strong>{_fmt_km(run.km)}</strong>"
        f"<span>km<br>run</span></div>"
        + (f"<p class='sub'>{change}</p>" if change else "")
        + _row([(f"{recap.hours:.0f}h", "trained"),
                (f"{recap.active_days}", f"of {recap.through.day} days"),
                (f"{recap.sessions}", "sessions")])
        + _calendar_html(recap)
    )
    return _card(recap, "cover", f"{recap.month:%B}", body)


# SVG text is styled with presentation attributes, not stylesheet classes:
# html-to-image does not carry class rules onto SVG text.
_SVG_FONT = "font-family=\"Archivo, sans-serif\" text-anchor='middle'"


def _week_bars_svg(weeks: tuple[rm.WeekBar, ...]) -> str:
    """Weekly run km as ink bars, with the planned km of the same days in orange."""
    if not weeks:
        return ""
    width, height, top, bottom = 320, 150, 14, 20
    peak = max([w.km for w in weeks] + [w.planned_km or 0 for w in weeks] + [1.0])
    slot = width / len(weeks)
    bar_w = min(44.0, slot * 0.66)
    scale = (height - top - bottom) / peak
    base = height - bottom
    parts = [f"<svg class='bars' viewBox='0 0 {width} {height}' role='img' "
             f"aria-label='Run km per week'>"]
    for i, week in enumerate(weeks):
        cx = slot * (i + 0.5)
        h = max(week.km * scale, 0)
        parts.append(f"<rect x='{cx - bar_w / 2:.1f}' y='{base - h:.1f}' width='{bar_w:.1f}' "
                     f"height='{h:.1f}' fill='{INK}'/>")
        if week.planned_km:
            py = base - week.planned_km * scale
            parts.append(f"<rect x='{cx - bar_w / 2 - 3:.1f}' y='{py - 1.5:.1f}' "
                         f"width='{bar_w + 6:.1f}' height='3' fill='{SIGNAL}'/>")
        # Inside the foot of the bar, where the planned line can never cross it.
        inside = h > 22
        ty = base - 7 if inside else base - h - 5
        fill = PAPER if inside else INK
        parts.append(f"<text x='{cx:.1f}' y='{ty:.1f}' {_SVG_FONT} font-size='14' "
                     f"font-weight='800' fill='{fill}'>{week.km:.0f}</text>")
        days = (f"{week.first_day.day}" if week.first_day == week.last_day
                else f"{week.first_day.day}–{week.last_day.day}")
        parts.append(f"<text x='{cx:.1f}' y='{height - 5}' {_SVG_FONT} font-size='10' "
                     f"font-weight='500' fill='{INK}'>{days}</text>")
    parts.append("</svg>")
    return "".join(parts)


def _intensity_html(band_km: dict[str, float]) -> str:
    """One bar split by intensity: ink easy, orange tempo, hatched threshold."""
    total = sum(band_km.values())
    if total <= 0:
        return ""
    cls = {"Easy": "b-easy", "Tempo": "b-tempo", "Threshold+": "b-hard"}
    segs = "".join(
        f"<span class='{cls[b]}' style='width:{100 * km / total:.1f}%'></span>"
        for b, km in band_km.items() if km > 0
    )
    keys = "".join(
        f"<span><i class='sw {cls[b]}'></i>{b} {100 * km / total:.0f}%</span>"
        for b, km in band_km.items()
    )
    return f"<div class='stack'>{segs}</div><div class='legend'>{keys}</div>"


def _line(label: str, value: str) -> str:
    """A ruled label/value line."""
    return f"<div class='p-line'><span>{escape(label)}</span><strong>{value}</strong></div>"


def _running_card(recap: rm.MonthRecap) -> str:
    """Card 2: volume, the shape of the weeks, intensity and easy pace."""
    run = recap.running
    surface = ("all outdoors" if run.treadmill_km == 0
               else f"{_fmt_km(run.treadmill_km)} on the treadmill")
    change = _change(run.km, run.prev_km, _prev(recap))
    sub = " · ".join(x for x in (f"{run.runs} runs", f"{run.hours:.1f} h", surface, change) if x)
    lines = ""
    if run.longest_km:
        lines += _line("Longest run", f"{run.longest_km:.1f} km · "
                       f"{escape(run.longest_label.split(' · ')[-1])}")
    if run.easy_pace_s is not None:
        before = (f" <em>{_prev(recap)} {seconds_to_pace(run.prev_easy_pace_s)}</em>"
                  if run.prev_easy_pace_s is not None else "")
        lines += _line("Easy pace", f"{seconds_to_pace(run.easy_pace_s)}/km{before}")
    body = (
        f"<div class='big'><strong>{_fmt_km(run.km)}</strong><span>km</span></div>"
        f"<p class='sub'>{sub}</p>"
        f"<h3>Week by week <em>— orange is the plan</em></h3>{_week_bars_svg(run.weeks)}"
        f"<h3>Intensity <em>— by average heart rate</em></h3>{_intensity_html(run.band_km)}"
        f"<div class='p-lines'>{lines}</div>"
    )
    return _card(recap, "running", "Running", body)


def _strength_card(recap: rm.MonthRecap) -> str:
    """Card 3: sessions, work and the heaviest named lifts."""
    st = recap.strength
    if st is None:
        return ""
    lifts = "".join(
        f"<li><div><span class='lift'>{escape(l.label)}</span>"
        + ("<i class='pr'>PR</i>" if l.is_pr else "")
        + f"<small>{l.day:%d %b}</small></div>"
        + f"<strong>{l.weight_kg:g}<span>kg</span>"
        + (f" × {l.reps:g}" if l.reps else "") + "</strong></li>"
        for l in st.lifts
    )
    diff = st.sessions - st.prev_sessions
    change = (f"same as {_prev(recap)}" if diff == 0
              else f"{abs(diff)} {'more' if diff > 0 else 'fewer'} than {_prev(recap)}")
    body = (
        f"<div class='big'><strong>{st.sessions}</strong><span>gym<br>sessions</span></div>"
        + (f"<p class='sub'>{change}</p>" if change else "")
        + _row([(f"{st.tonnage_kg / 1000:.1f}t", "moved"),
                (str(st.working_sets), "working sets"),
                (f"{st.hours:.1f}h", "under the bar")])
        + (f"<h3>Heaviest sets</h3><ul class='lifts'>{lifts}</ul>" if lifts else "")
    )
    return _card(recap, "strength", "Strength", body)


def _hrv_bar(body: rm.BodyRecap, prev_name: str) -> str:
    """HRV baseline band (hatched) with this month's mean in orange."""
    if body.hrv_avg is None:
        return ""
    points = [body.hrv_avg] + [v for v in (body.prev_hrv_avg, body.baseline_low,
                                           body.baseline_high) if v is not None]
    lo, hi = min(points) - 8, max(points) + 8

    def x(v: float) -> float:
        return 100.0 * (v - lo) / (hi - lo)

    band = ""
    if body.baseline_low is not None and body.baseline_high is not None:
        band = (f"<span class='hrv-band' style='left:{x(body.baseline_low):.1f}%;"
                f"width:{x(body.baseline_high) - x(body.baseline_low):.1f}%'></span>")
    prev = (f"<span class='hrv-mark prev' style='left:{x(body.prev_hrv_avg):.1f}%'></span>"
            if body.prev_hrv_avg is not None else "")
    return (f"<div class='hrv'>{band}{prev}<span class='hrv-mark' "
            f"style='left:{x(body.hrv_avg):.1f}%'></span></div>")


def _body_card(recap: rm.MonthRecap) -> str:
    """Card 4: weight trend, HRV and training load."""
    body = recap.body
    prev = _prev(recap)
    parts = []
    if body.trend_end_kg is not None and body.trend_start_kg is not None:
        change = _change(body.trend_end_kg, body.trend_start_kg, "the start", " kg", 1)
        parts.append(
            f"<div class='block'><h3>Weight</h3><div class='pair'>"
            f"<span>{body.trend_start_kg:.1f}</span><i>→</i>"
            f"<strong>{body.trend_end_kg:.1f}</strong><span>kg</span></div>"
            f"<p class='sub'>{change.replace(' on the start', '')} · "
            f"{body.weigh_ins} weigh-ins, weekly average</p></div>"
        )
    if body.hrv_avg is not None:
        base = (f" · baseline {body.baseline_low:.0f}–{body.baseline_high:.0f} (hatched)"
                if body.baseline_low is not None else "")
        was = f"{prev} {body.prev_hrv_avg:.0f} (black line)" if body.prev_hrv_avg is not None else ""
        parts.append(
            f"<div class='block'><h3>Overnight HRV</h3><div class='pair'>"
            f"<strong>{body.hrv_avg:.0f}</strong><span>ms</span></div>"
            f"{_hrv_bar(body, prev)}<p class='sub'>{was}{base}</p></div>"
        )
    parts.append(
        f"<div class='block'><h3>Training load</h3><div class='pair'>"
        f"<strong>{body.load:,.0f}</strong></div>"
        f"<p class='sub'>{prev} {body.prev_load:,.0f} · "
        f"{_change(body.load, body.prev_load, prev)}</p></div>"
    )
    return _card(recap, "body", "Body", "".join(parts))


def _closing_card(recap: rm.MonthRecap) -> str:
    """Card 5: the month in a few lines, and the race countdown."""
    # Numbered in the markup: CSS counters do not survive the image export.
    lines = "".join(
        f"<li><span class='n'>{i}</span><span>{escape(t)}</span></li>"
        for i, t in enumerate(recap.takeaways, start=1)
    ) or "<li><span class='n'>–</span><span>A quiet month.</span></li>"
    races = recap.races
    raced = "".join(
        f"<p class='raced'>Raced {escape(r.name.title())}, {r.date:%d %b}.</p>"
        for r in races.raced
    )
    countdown = ""
    if races.next_race is not None:
        countdown = (
            f"<div class='count'><strong>{races.days_to_next}</strong>"
            f"<span>days to {escape(races.next_race.name.title())}<br>"
            f"{races.next_race.date:%d %B}</span></div>"
        )
    return _card(recap, "closing", "In short",
                 f"<ol class='notes'>{lines}</ol>{raced}{countdown}")


def story_cards(recap: rm.MonthRecap) -> list[str]:
    """Render the month's cards, skipping those with nothing to show.

    Parameters
    ----------
    recap : MonthRecap
        Output of :func:`dashboard.recap_metrics.build_month_recap`.

    Returns
    -------
    list of str
        One ``<article>`` per card, cover first and the closing card last,
        each numbered ``n/total``.
    """
    cards = [_cover_card(recap)]
    if recap.running.km > 0:
        cards.append(_running_card(recap))
    if recap.strength is not None:
        cards.append(_strength_card(recap))
    body = recap.body
    if body.weigh_ins or body.hrv_avg is not None or body.load:
        cards.append(_body_card(recap))
    cards.append(_closing_card(recap))
    total = len(cards)
    return [c.replace("__PAGE__", f"{i:02d}/{total:02d}", 1) for i, c in enumerate(cards, 1)]


def _story_html(recap: rm.MonthRecap, active: bool) -> str:
    """One month's story: progress segments, the scaled stage and tap zones."""
    cards = story_cards(recap)
    segments = "".join("<span class='seg'><i></i></span>" for _ in cards)
    return (
        f"<section class='story{' active' if active else ''}' data-recap-month='{recap.key}' "
        f"aria-label='{escape(recap.title)} recap'>"
        f"<div class='story-progress'>{segments}</div>"
        f"<div class='story-frame'><div class='story-stage'>{''.join(cards)}</div>"
        f"<button class='story-tap prev' aria-label='Previous card'></button>"
        f"<button class='story-tap next' aria-label='Next card'></button></div></section>"
    )


_NOTES = (
    "Changes compare with the previous month. A month still in progress is "
    "compared with the same number of days of the month before.",
    "Running km counts outdoor and treadmill runs. Runs with an impossible pace "
    "(a bad GPS distance) are left out.",
    "Intensity puts each whole run in one zone by its average heart rate. That "
    "is a rough proxy, not time in zone.",
    "Easy pace is the median of outdoor easy runs only; belt pace is set by the "
    "machine.",
    "The orange line on the weekly bars is the run km the plan set for the same "
    "days.",
    "On the calendar, a run day that also had gym or Hyrox carries a band at the "
    "bottom of its square.",
    "Lifts are named only where Garmin identified the movement with certainty. "
    "A PR is heavier than any earlier month; a first entry is not a PR.",
    "Weight is a 7-day trailing mean entering and leaving the month, because "
    "daily readings swing with water.",
    "The closing lines come from fixed rules over the other cards.",
)


def recap_section_html(recaps: list[rm.MonthRecap], selected_key: str) -> str:
    """Render the Recap tab.

    Parameters
    ----------
    recaps : list of MonthRecap
        Every month to offer, newest first.
    selected_key : str
        ``YYYY-MM`` of the month shown on load.

    Returns
    -------
    str
        The tab's HTML fragment, or an empty string with no months.
    """
    if not recaps:
        return ""
    chips = "".join(
        f"<button class='recap-chip{' active' if r.key == selected_key else ''}' "
        f"data-recap='{r.key}' aria-pressed='{'true' if r.key == selected_key else 'false'}'>"
        f"{r.month:%b %Y}{' · so far' if r.in_progress else ''}</button>"
        for r in recaps
    )
    stories = "".join(_story_html(r, r.key == selected_key) for r in recaps)
    notes = "".join(f"<li>{escape(n)}</li>" for n in _NOTES)
    return (
        "<h2>Monthly recap</h2>"
        "<p class='note recap-intro'>Tap the right side for the next card and the left for "
        "the previous one; hold to pause. <strong>Share</strong> sends the card on screen "
        "as a 1080 × 1920 image, or downloads it where your browser cannot share.</p>"
        f"<div class='recap-chips' role='group' aria-label='Month'>{chips}</div>"
        "<div class='recap-viewer'>"
        "<button class='recap-close' aria-label='Close full screen'>×</button>"
        f"{stories}"
        "<div class='recap-actions'>"
        "<button class='recap-btn' data-act='prev' aria-label='Previous card'>‹</button>"
        "<button class='recap-btn' data-act='play' aria-label='Pause'>Pause</button>"
        "<button class='recap-btn' data-act='next' aria-label='Next card'>›</button>"
        "<button class='recap-btn primary' data-act='share'>Share card</button>"
        "<button class='recap-btn' data-act='save-all'>Save all</button>"
        "<button class='recap-btn' data-act='full'>Full screen</button>"
        "</div><div class='recap-toast' role='status' aria-live='polite'></div></div>"
        f"<details class='recap-notes'><summary>How these numbers are made</summary>"
        f"<ul>{notes}</ul></details>"
    )


RECAP_CSS = """
/* ---------- recap: viewer chrome (follows the page theme) ---------- */
.recap-intro { margin: 0 0 12px; }
.recap-chips { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 6px;
  margin-bottom: 14px; scrollbar-width: none; }
.recap-chips::-webkit-scrollbar { display: none; }
.recap-chip { flex: none; border: 1px solid var(--border); background: var(--surface);
  color: var(--muted); border-radius: 999px; padding: 6px 13px; font: inherit;
  font-size: 13px; cursor: pointer; }
.recap-chip.active { background: var(--accent); color: var(--accent-contrast);
  border-color: var(--accent); }
.recap-viewer { display: flex; flex-direction: column; align-items: center; gap: 12px;
  position: relative; }
.story { display: none; flex-direction: column; align-items: center; gap: 8px; }
.story.active { display: flex; }
.story-progress { display: flex; gap: 4px; width: var(--story-w, 360px); }
.story-progress .seg { flex: 1; height: 3px; border-radius: 2px;
  background: color-mix(in srgb, var(--text) 18%, transparent); overflow: hidden; }
.story-progress .seg i { display: block; height: 100%; width: 0; background: var(--text); }
.story-progress .seg.seen i { width: 100%; }
.story-frame { position: relative; width: var(--story-w, 360px);
  height: var(--story-h, 640px); overflow: hidden;
  box-shadow: 0 18px 50px -24px rgba(0,0,0,.5); touch-action: manipulation;
  user-select: none; -webkit-user-select: none; }
.story-stage { position: absolute; top: 0; left: 0; width: 360px; height: 640px;
  transform-origin: top left; transform: scale(var(--story-s, 1)); }
.story-tap { position: absolute; top: 0; bottom: 0; border: 0; background: transparent;
  padding: 0; cursor: pointer; -webkit-tap-highlight-color: transparent; }
.story-tap.prev { left: 0; width: 33%; }
.story-tap.next { right: 0; width: 67%; }
.story-tap:focus-visible { outline: 2px solid var(--ring); outline-offset: -4px; }
.recap-actions { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; }
.recap-btn { border: 1px solid var(--border); background: var(--surface); color: var(--text);
  border-radius: 10px; padding: 8px 13px; font: inherit; font-size: 14px; cursor: pointer;
  min-width: 42px; }
.recap-btn:hover { border-color: var(--border-strong); }
.recap-btn.primary { background: var(--accent); color: var(--accent-contrast);
  border-color: var(--accent); }
.recap-btn[disabled] { opacity: .55; cursor: progress; }
.recap-toast { min-height: 20px; font-size: 13px; color: var(--muted); text-align: center; }
.recap-notes { max-width: 560px; margin: 18px auto 0; color: var(--muted); font-size: 14px; }
.recap-notes summary { cursor: pointer; color: var(--text); }
.recap-notes ul { margin: 8px 0 0; padding-left: 18px; }
.recap-notes li { margin: 4px 0; }
.recap-close { display: none; }
.recap-viewer.immersive { position: fixed; inset: 0; z-index: 1000; background: #000;
  justify-content: center; padding: 10px 0; gap: 10px; }
.recap-viewer.immersive .story-progress .seg { background: rgba(255,255,255,.25); }
.recap-viewer.immersive .story-progress .seg i { background: #fff; }
.recap-viewer.immersive .recap-btn { background: rgba(255,255,255,.1); color: #fff;
  border-color: rgba(255,255,255,.18); }
.recap-viewer.immersive .recap-btn.primary { background: #fff; color: #000; }
.recap-viewer.immersive .recap-toast { color: rgba(255,255,255,.7); }
.recap-viewer.immersive .recap-close { display: block; position: absolute; top: 8px;
  right: 12px; z-index: 2; background: transparent; border: 0; color: #fff;
  font-size: 30px; line-height: 1; cursor: pointer; padding: 4px 8px; }
.recap-viewer.immersive [data-act='full'] { display: none; }
body.recap-locked { overflow: hidden; }

/* ---------- recap: the poster cards (fixed palette, exported as-is) ---------- */
.story-card { position: absolute; inset: 0; width: 360px; height: 640px; overflow: hidden;
  display: flex; flex-direction: column; padding: 18px 20px 16px; color: __INK__;
  background: __PAPER__; font-family: 'Archivo', 'Arial Narrow', sans-serif;
  font-size: 12px; line-height: 1.3; opacity: 0; pointer-events: none;
  transition: opacity .18s ease; }
.story-card.on { opacity: 1; }
.p-grain { position: absolute; inset: 0; background-image: __GRAIN__; opacity: .06;
  pointer-events: none; }
.p-top, .p-title, .p-body { position: relative; }
.p-top { display: flex; justify-content: space-between; font-size: 11px; font-weight: 600;
  border-bottom: 2px solid __INK__; padding-bottom: 6px; white-space: nowrap; }
.p-title { margin: 12px 0 0; font-family: inherit; font-stretch: 62%; font-weight: 900;
  font-size: 66px; line-height: .86; letter-spacing: -.01em; text-transform: uppercase;
  color: __INK__; white-space: nowrap; }
.p-body { flex: 1; display: flex; flex-direction: column; min-height: 0; }
.big { display: flex; align-items: flex-end; gap: 8px; margin-top: 6px; }
.big strong { font-stretch: 62%; font-weight: 900; font-size: 128px; line-height: .8;
  letter-spacing: -.03em; color: __SIGNAL__; }
.big span { font-weight: 800; font-size: 17px; line-height: 1.05; padding-bottom: 5px; }
.sub { margin: 8px 0 0; font-size: 12.5px; font-weight: 500; }
.p-row { display: grid; border-top: 1px solid __INK__; border-bottom: 1px solid __INK__;
  margin-top: 12px; }
.p-row.cols-3 { grid-template-columns: repeat(3, 1fr); }
.p-row div { padding: 6px 0 5px; font-size: 11px; font-weight: 500; }
.p-row div + div { border-left: 1px solid __INK__; padding-left: 9px; }
.p-row strong { display: block; font-stretch: 75%; font-weight: 800; font-size: 28px;
  line-height: 1; }
.p-body h3 { margin: 14px 0 6px; font-size: 13px; font-weight: 800; }
.p-body h3 em { font-style: normal; font-weight: 500; }
.dow, .cal { display: grid; grid-template-columns: repeat(7, 1fr); gap: 3px; }
.dow { margin-top: 12px; font-size: 9px; font-weight: 700; }
.dow span { padding-left: 3px; }
.cal { margin-top: 3px; }
.c { position: relative; aspect-ratio: 1; font-style: normal; display: block;
  box-sizing: border-box; overflow: hidden; }
.cal.rows-6 .c { aspect-ratio: 1.25; }
.c b { position: absolute; top: 2px; left: 4px; font-size: 9px; font-weight: 700; }
.c em { position: absolute; right: 4px; bottom: 0; font-style: normal; font-stretch: 62%;
  font-weight: 900; font-size: 22px; line-height: 1; }
.c s { position: absolute; left: 4px; right: 3px; bottom: 3px; text-decoration: none;
  font-size: 8px; font-weight: 800; letter-spacing: .02em; white-space: nowrap;
  overflow: hidden; }
.c.run { background: __INK__; color: __PAPER__; }
.c.run.has-band em { bottom: 11px; font-size: 19px; }
.c.hyrox { background: __SIGNAL__; color: __INK__; }
.c.gym { border: 1.5px solid __INK__; }
.c.gym .hatch { position: absolute; left: 0; right: 0; top: 14px; bottom: 10px;
  background: repeating-linear-gradient(135deg, __INK__ 0 1.6px, transparent 1.6px 5px); }
.c.gym b { top: 1px; left: 3px; }
.c.hyrox.has-band s { bottom: 13px; }
.c.other { border: 1.5px solid __INK__; }
.c.rest { color: rgba(22,19,15,.45); }
.c.future { border: 1px dashed rgba(22,19,15,.35); color: rgba(22,19,15,.45); }
.band { position: absolute; left: 0; right: 0; bottom: 0; height: 11px; display: flex;
  text-decoration: none; }
.band span { flex: 1; font-size: 7.5px; font-weight: 800; line-height: 11px;
  text-align: center; letter-spacing: .02em; }
.band .t-gym { background: __PAPER__; color: __INK__; border: 1px solid __INK__;
  box-sizing: border-box; line-height: 9px; }
.band .t-hyrox { background: __SIGNAL__; color: __INK__; }
.band .t-other { background: __PAPER__; color: __INK__; }
.legend { display: flex; flex-wrap: wrap; gap: 4px 12px; margin-top: 8px; font-size: 11px;
  font-weight: 600; }
.legend span { display: inline-flex; align-items: center; gap: 5px; }
.sw { display: inline-block; width: 10px; height: 10px; box-sizing: border-box; }
.sw-run { background: __INK__; }
.sw-gym { background: repeating-linear-gradient(135deg, __INK__ 0 1.2px, transparent 1.2px 3.5px);
  border: 1px solid __INK__; }
.sw-hyrox { background: __SIGNAL__; }
.sw-other { border: 1.5px solid __INK__; }
.bars { width: 100%; height: auto; display: block; }
.stack { display: flex; height: 16px; border: 1.5px solid __INK__; }
.stack span { display: block; height: 100%; }
.b-easy { background: __INK__; }
.b-tempo { background: __SIGNAL__; }
.b-hard { background: repeating-linear-gradient(135deg, __INK__ 0 1.6px, transparent 1.6px 4.5px); }
.legend .b-hard { border: 1px solid __INK__; }
.p-lines { margin-top: auto; }
.p-line { display: flex; justify-content: space-between; align-items: baseline;
  border-top: 1px solid __INK__; padding: 6px 0 5px; font-size: 12.5px; font-weight: 500; }
.p-line strong { font-weight: 800; font-size: 14px; }
.p-line em { font-style: normal; font-weight: 500; opacity: .6; margin-left: 4px; }
.lifts { list-style: none; margin: 0; padding: 0; }
.lifts li { display: flex; justify-content: space-between; align-items: center;
  border-top: 1px solid __INK__; padding: 7px 0; }
.lifts li:last-child { border-bottom: 1px solid __INK__; }
.lift { font-size: 14px; font-weight: 700; }
.lifts small { display: block; font-size: 11px; font-weight: 500; margin-top: 1px; }
.lifts strong { font-stretch: 70%; font-weight: 900; font-size: 30px; line-height: 1; }
.lifts strong span { font-size: 13px; font-stretch: 100%; font-weight: 700; margin: 0 2px; }
.pr { font-style: normal; font-size: 9.5px; font-weight: 900; background: __SIGNAL__;
  color: __INK__; padding: 1px 4px; margin-left: 6px; vertical-align: 2px; }
.block { border-top: 1px solid __INK__; padding-top: 2px; margin-top: 12px; }
.block h3 { margin-top: 6px; }
.pair { display: flex; align-items: baseline; gap: 8px; }
.pair strong { font-stretch: 62%; font-weight: 900; font-size: 64px; line-height: .9;
  color: __SIGNAL__; }
.pair span { font-stretch: 62%; font-weight: 800; font-size: 30px; }
.pair span:last-child { font-size: 16px; font-stretch: 100%; }
.pair i { font-style: normal; font-size: 22px; font-weight: 700; }
.hrv { position: relative; height: 12px; margin-top: 10px; border: 1.5px solid __INK__; }
.hrv-band { position: absolute; top: 0; bottom: 0;
  background: repeating-linear-gradient(135deg, __INK__ 0 1.2px, transparent 1.2px 4px); }
.hrv-mark { position: absolute; top: -6px; bottom: -6px; width: 5px; margin-left: -2.5px;
  background: __SIGNAL__; }
.hrv-mark.prev { width: 3px; margin-left: -1.5px; background: __INK__; }
.notes { list-style: none; margin: 14px 0 0; padding: 0; }
.notes li { display: grid; grid-template-columns: 30px 1fr; border-top: 1px solid __INK__;
  padding: 9px 0; font-size: 16px; font-weight: 600; line-height: 1.25; }
.notes .n { font-stretch: 62%; font-weight: 900; font-size: 26px; line-height: .9;
  color: __SIGNAL__; }
.raced { font-weight: 700; margin: 6px 0 0; }
.count { margin-top: auto; display: flex; align-items: flex-end; gap: 10px;
  border-top: 2px solid __INK__; padding-top: 8px; }
.count strong { font-stretch: 62%; font-weight: 900; font-size: 120px; line-height: .8;
  color: __SIGNAL__; letter-spacing: -.03em; }
.count span { font-size: 17px; font-weight: 800; line-height: 1.1; padding-bottom: 4px; }
""".replace("__PAPER__", PAPER).replace("__INK__", INK).replace(
    "__SIGNAL__", SIGNAL).replace("__GRAIN__", _GRAIN)


# Viewer behaviour. Kept as a plain string so the braces need no doubling;
# ``__EXPORT_RATIO__`` and ``__PAPER__`` are substituted by :func:`recap_script`.
_RECAP_SCRIPT = """
(function () {
  var viewer = document.querySelector('.recap-viewer');
  if (!viewer) { return; }
  var CARD_W = 360, CARD_H = 640, EXPORT_RATIO = __EXPORT_RATIO__, DWELL_MS = 6000;
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var state = { story: null, index: 0, elapsed: 0, playing: !reduceMotion, last: 0,
                held: false, downAt: 0 };
  var blobCache = new WeakMap();
  var toast = viewer.querySelector('.recap-toast');
  var playBtn = viewer.querySelector("[data-act='play']");

  function cards() { return state.story ? state.story.querySelectorAll('.story-card') : []; }
  function segs() { return state.story ? state.story.querySelectorAll('.story-progress .seg') : []; }
  function tabVisible() {
    var panel = document.getElementById('tab-recap');
    return panel && panel.classList.contains('active') && !document.hidden;
  }
  function say(text) { toast.textContent = text || ''; }

  function fit() {
    var immersive = viewer.classList.contains('immersive');
    var availW = immersive ? window.innerWidth - 16 : viewer.clientWidth;
    var availH = immersive ? window.innerHeight - 110 : Math.max(420, window.innerHeight - 200);
    var s = Math.min(availW / CARD_W, availH / CARD_H, immersive ? 3 : 1.25);
    s = Math.max(s, 0.5);
    viewer.style.setProperty('--story-s', s.toFixed(4));
    viewer.style.setProperty('--story-w', (CARD_W * s).toFixed(1) + 'px');
    viewer.style.setProperty('--story-h', (CARD_H * s).toFixed(1) + 'px');
  }

  function show(index) {
    var list = cards();
    if (!list.length) { return; }
    state.index = Math.max(0, Math.min(index, list.length - 1));
    state.elapsed = 0;
    list.forEach(function (c, i) { c.classList.toggle('on', i === state.index); });
    segs().forEach(function (s, i) {
      s.classList.toggle('seen', i < state.index);
      s.querySelector('i').style.width = i < state.index ? '100%' : '0';
    });
    say('');
  }

  function step(delta) {
    var list = cards();
    if (delta > 0 && state.index >= list.length - 1) { setPlaying(false); return; }
    show(state.index + delta);
  }

  function setPlaying(on) {
    state.playing = on;
    playBtn.textContent = on ? 'Pause' : 'Play';
    playBtn.setAttribute('aria-label', on ? 'Pause' : 'Play');
    if (on && state.index >= cards().length - 1 && state.elapsed >= DWELL_MS) { show(0); }
  }

  function tick() {
    var now = performance.now();
    var dt = state.last ? now - state.last : 0;
    state.last = now;
    if (state.playing && !state.held && tabVisible() && state.story) {
      state.elapsed += dt;
      var seg = segs()[state.index];
      if (seg) { seg.querySelector('i').style.width = Math.min(100, 100 * state.elapsed / DWELL_MS) + '%'; }
      if (state.elapsed >= DWELL_MS) {
        if (state.index >= cards().length - 1) { setPlaying(false); } else { show(state.index + 1); }
      }
    }
  }

  function openMonth(key) {
    viewer.querySelectorAll('.story').forEach(function (s) {
      var on = s.dataset.recapMonth === key;
      s.classList.toggle('active', on);
      if (on) { state.story = s; }
    });
    document.querySelectorAll('.recap-chip').forEach(function (c) {
      var on = c.dataset.recap === key;
      c.classList.toggle('active', on);
      c.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    show(0);
  }

  function cardBlob(card) {
    if (blobCache.has(card)) { return Promise.resolve(blobCache.get(card)); }
    if (!window.htmlToImage) { return Promise.reject(new Error('export library not loaded')); }
    return document.fonts.ready.then(function () {
      return window.htmlToImage.toBlob(card, {
        width: CARD_W, height: CARD_H, pixelRatio: EXPORT_RATIO,
        backgroundColor: '__PAPER__', style: { opacity: '1', transition: 'none' }
      });
    }).then(function (blob) { blobCache.set(card, blob); return blob; });
  }

  function download(blob, name) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    window.setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
  }

  function shareCurrent(btn) {
    var card = cards()[state.index];
    if (!card) { return; }
    var wasCached = blobCache.has(card);
    setPlaying(false);
    btn.disabled = true;
    say(wasCached ? '' : 'Rendering image…');
    cardBlob(card).then(function (blob) {
      var file = new File([blob], card.dataset.file, { type: 'image/png' });
      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        return navigator.share({ files: [file] }).then(function () { say(''); }, function (err) {
          if (err && err.name === 'AbortError') { say(''); return; }
          // iOS drops the tap's permission while the image renders; the blob is
          // cached now, so a second tap shares instantly.
          say(wasCached ? 'Sharing failed, so the image was downloaded instead.' : 'Image ready: tap Share again.');
          if (wasCached) { download(blob, card.dataset.file); }
        });
      }
      download(blob, card.dataset.file);
      say('Saved ' + card.dataset.file);
    }).catch(function (err) {
      say('Could not render the image (' + err.message + ').');
    }).then(function () { btn.disabled = false; });
  }

  function saveAll(btn) {
    var list = Array.prototype.slice.call(cards());
    var original = state.index;
    setPlaying(false);
    btn.disabled = true;
    var chain = Promise.resolve();
    list.forEach(function (card, i) {
      chain = chain.then(function () {
        say('Rendering ' + (i + 1) + ' of ' + list.length + '…');
        return cardBlob(card).then(function (blob) { download(blob, card.dataset.file); });
      });
    });
    chain.then(function () { say('Saved ' + list.length + ' images.'); }, function (err) {
      say('Could not render the images (' + err.message + ').');
    }).then(function () { btn.disabled = false; show(original); });
  }

  function setImmersive(on) {
    viewer.classList.toggle('immersive', on);
    document.body.classList.toggle('recap-locked', on);
    fit();
  }

  viewer.querySelectorAll('.story-frame').forEach(function (frame) {
    frame.addEventListener('pointerdown', function () {
      state.held = true; state.downAt = performance.now();
    });
    ['pointerup', 'pointercancel', 'pointerleave'].forEach(function (type) {
      frame.addEventListener(type, function () { state.held = false; });
    });
  });
  viewer.querySelectorAll('.story-tap').forEach(function (tap) {
    tap.addEventListener('click', function () {
      // A long press pauses the story, Instagram-style; only a short tap navigates.
      if (performance.now() - state.downAt > 350) { return; }
      step(tap.classList.contains('next') ? 1 : -1);
    });
  });
  viewer.querySelectorAll('.recap-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var act = btn.dataset.act;
      if (act === 'prev') { step(-1); }
      else if (act === 'next') { step(1); }
      else if (act === 'play') { setPlaying(!state.playing); }
      else if (act === 'share') { shareCurrent(btn); }
      else if (act === 'save-all') { saveAll(btn); }
      else if (act === 'full') { setImmersive(true); }
    });
  });
  viewer.querySelector('.recap-close').addEventListener('click', function () { setImmersive(false); });
  document.querySelectorAll('.recap-chip').forEach(function (chip) {
    chip.addEventListener('click', function () { openMonth(chip.dataset.recap); });
  });
  document.addEventListener('keydown', function (e) {
    if (!tabVisible()) { return; }
    if (e.key === 'ArrowRight') { step(1); }
    else if (e.key === 'ArrowLeft') { step(-1); }
    else if (e.key === 'Escape') { setImmersive(false); }
  });
  document.querySelectorAll('.tab-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (btn.dataset.tab === 'recap') { fit(); show(state.index); }
    });
  });
  window.addEventListener('resize', fit);

  var initial = viewer.querySelector('.story.active');
  if (initial) { openMonth(initial.dataset.recapMonth); }
  setPlaying(state.playing);
  fit();
  // A short interval rather than animation frames: frames stall whenever the
  // page is not being painted, which would freeze the story mid-card.
  window.setInterval(tick, 50);
})();
"""


def recap_script() -> str:
    """Return the viewer's JavaScript with the export ratio substituted in.

    Returns
    -------
    str
        Script body appended to the page's inline ``<script>``.
    """
    return (_RECAP_SCRIPT.replace("__EXPORT_RATIO__", str(EXPORT_WIDTH_PX // CARD_WIDTH_PX))
            .replace("__PAPER__", PAPER))
