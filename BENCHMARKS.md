# Benchmarks — hybrid endurance (Hyrox + 21k)

Progress-tracking battery for the macrocycle toward **Hyrox #2 (2026-12-13)**, with the
standing 21k as aerobic support. Generation does not read Garmin recovery or
readiness. Benchmarks close the loop the plan can't: they verify the prescription is actually moving
fitness, so the "err high / auto-regulate by feel" approach stays honest against a measured trend.
Companion to [METHODOLOGY.md](METHODOLOGY.md) — every benchmark maps to a limiter or a goal.

**Phase 1 (now):** log results in this file. **Phase 2 (December build):** promote to a Supabase
`benchmark_results` table + a dashboard trend panel against targets.

## How to test (so the numbers mean something)

- **Controlled conditions.** Same course/treadmill, equipment, and (where possible) time of day. A
  benchmark is only a signal if the setup is repeatable.
- **Test in a deload-adjacent / fresh window**, not on the back of a hard block — fatigue confounds
  the read. Never test two maximal domains on the same day.
- **Log the context:** RPE, sleep/readiness, temperature, shoes, anything that moves the number.
- **Rotate, don't re-test everything every time** — see the cadence table.
- **A treadmill test needs a trusted speed source.** A watch that isn't paired to the treadmill
  estimates distance from the wrist, which voids the pace half of the benchmark — HR still stands.
  Either pair the watch, calibrate the run against the console distance afterwards, or write down
  console speed by hand. Otherwise run any pace-anchored test outdoors. (Cost this one 2026-08-11.)
- **One effort, not steps.** A 30-min TT is a single maximal, near-even effort. Stepping the pace up
  through the test invalidates the last-20-min LTHR average, because that window then spans several
  intensities instead of one. Even splits, small negative finish at most.

## Cadence

| Benchmark | Frequency | Preferred window |
|---|---|---|
| 5k time trial | every 4–6 wk | end of a build block, post-deload |
| Threshold field test (30-min TT) | only with a flat verified route or calibrated treadmill | fresh, block boundary |
| Long-run HR/pace decoupling | continuous (each long run) | review monthly |
| Garmin VO2max estimate | continuous | directional only |
| Est-1RM squat + trap-bar DL | every ~8 wk | fresh strength day |
| Upper: pull-up / OHP / bench | every ~8 wk | once baselined (post 2026-07-23) |
| CMJ + standing broad jump | every ~4 wk | also doubles as a readiness check |
| SkiErg 1000 m / Row 1000 m TT | every ~6–8 wk | fresh |
| Hyrox station battery (Pro load) | every ~8 wk | controlled, fresh |
| Compromised-run pace | continuous (read from each sim) | — |
| Bodyweight | weekly | fasted AM |
| **Actual Hyrox race** | the event itself | **2026-12-13 = true benchmark** |

## The battery

### 1. Endurance / running — the priority (running is the limiter)

| Metric | Protocol | Baseline | Target | Why tracked |
|---|---|---|---|---|
| **5k time trial** | Flat, fresh, even pacing. | **~sub-20:00** (PB, self-reported) | **sub-19:00** (PB ~ met — retarget for the pro track) | Single-number proxy for VO2/threshold; the headline goal metric. |
| **Threshold** (LT2 proxy) | **30-min TT** (Friel): avg HR of last 20 min ≈ LTHR, avg pace ≈ threshold pace. Same route, fresh. | **4:16/km @ 175 bpm** (derived 2026-09-06 from the 08-30 10 km; the 2026-06-19 lab pair is superseded) | push pace down at same HR | The ceiling both the 21k and Hyrox running share — re-check so zones don't drift. Lab lactate not repeated (access/cost); field TT keeps it current. |
| **LT1** (aerobic threshold) | No recurring lactate test — approximate as a conservative easy cap below LT2 (the plan already caps easy well under the Z2 ceiling). Optional: DFA-a1 HRV app. | **not captured** — approximated | keep easy genuinely easy | Defines the true easy ceiling; without lactate we hold the safe conservative cap rather than a measured value. |
| **Long-run decoupling** | Pa:HR drift over a steady long run (Garmin/TP). | — | **< 5%** | Aerobic durability — holding pace without HR creep. Essentially free. |
| **Garmin VO2max** | Passive estimate. | — | upward trend | Noisy; directional support only, never a decision on its own. |

### 2. Strength — supports running economy + sled power

| Metric | Protocol | Baseline | Target | Why tracked |
|---|---|---|---|---|
| **Back squat est-1RM** | From an RPE-8 top set (Epley), don't test true 1RM. | **100 kg × 5** (Garmin, 2026-08-18) — triples at 100 kg leave >2 RIR | progressive | Economy + sled drive; low-rep strength is the main economy lever. |
| **Trap-bar deadlift est-1RM** | RPE-8 top set. | **140 kg × 3** top set (Garmin, 2026-08-11); back-off triples at 130 kg | progressive | Posterior-chain power for sleds/carries. |
| **Hip thrust** | Load @ RPE 7–8×6–8. | **110 kg × 8 × 3** (Garmin, 2026-09-08; +5 kg per session since August) | progressive | Hip extension for running + sled push. |
| **Upper: weighted pull-up** | Max reps + weighted 3RM. | **bw +10 kg × 4–5** (Garmin, three sessions since 2026-08-31) | close the gap to press strength | Vertical pull → sled pull, ski. The weakest of the three uppers relative to pressing. |
| **Upper: overhead press** | RPE-8 top set. | **62.5 kg × 4–5** (Garmin, 2026-09-21) | progress | Press strength → wall ball, burpee push-off. |
| **Upper: dumbbell bench** | RPE-8 top set. | **2×34 kg/hand × 8** (Garmin, 2026-09-21); 2×32 kg × 8–10 | progress | Horizontal press → burpee push-off, sled push lockout. |
| **Relative strength** | Best lifts ÷ bodyweight. | **bodyweight 84.4 kg** (scale, mean of 15 fasted AM weigh-ins 2026-09-07..09-22) → trap-bar 1.66× · hip thrust 1.30× · squat 1.18× · pull-up 1.12× (bw+10) · DB bench 0.81× (2×34) · OHP 0.74×. The earlier 75 kg self-report inflated every ratio by ~13% — all from *working* loads, not 1RM | ↑ kg/bw at stable bodyweight | Power-to-weight is what Hyrox running rewards — absolute kg alone can mislead. |

### 3. Power

| Metric | Protocol | Baseline | Target | Why tracked |
|---|---|---|---|---|
| **Countermovement jump** | Best of 3, app/mat height. | — | upward trend | Explosive output; also a sensitive daily fatigue/readiness marker. |
| **Standing broad jump** | Best of 3, distance. | — | upward trend | Horizontal power → burpee broad jumps, sled start. |

### 4. Hyrox-specific

Baseline these from a **controlled self-test**, not from Aug 2 (different stations) — see note below.

| Metric | Protocol | Baseline | Target | Why tracked |
|---|---|---|---|---|
| **SkiErg 1000 m TT** | Fresh, max sustainable. | — | establish | Clean upper-engine test, fully repeatable. |
| **Row 1000 m TT** | Fresh, max sustainable. | — | establish | Clean full-body engine test. |
| **Sled push / pull** | Timed over fixed distance at Pro load (push 202 kg, pull 153 kg). | — | establish | Race-specific strength-endurance at competition load. |
| **Wall balls** | Max unbroken to 3.0 m, 9 kg. | — | establish | Shoulder/leg muscular endurance. |
| **Compromised-run pace** | Pace held on the sim's 1k runs at a set HR. | ~4:50–4:55/km @ 150–160 bpm (current sim target) | faster @ same HR | The integrated "is my Hyrox fitness improving" signal. |
| **Hyrox station battery / half-sim** | Standardized self-test, Pro load, controlled. | — (late Oct / early Nov) | establish | The real, repeatable Hyrox baseline that December 13 is measured against. |

## Baseline plan

- **Aug 2 (Hyrox-*like* event, different stations):** log overall time, **running splits under fatigue**,
  pacing/execution notes, and the event's actual station results **flagged as event-specific / not
  Hyrox-comparable**. This seeds the running/engine line and gives a competitive-effort data point.
  Event format (Mixto): **8 km run** + deadlift 100 rep @ 34 kg · wall ball 100 rep @ 6 kg · burpee
  broad jump 80 m · sandbag lunges 100 m @ 10 kg · thrusters 100 rep @ 29 kg · farmers carry 200 m @
  2×15 kg · tyre flip-over 80 m · obstacle course (final stage). High-rep, lighter-load, no sleds/ski/row.
- **Post-race week (Aug 3–9):** free metrics only while recovering — decoupling from the last long run,
  Garmin VO2max, bodyweight, CMJ if fresh. No hard TTs.
- **Late Oct / early Nov:** full-battery baseline once recovered and built — strength est-1RMs,
  the Hyrox station battery, and a race or calibrated treadmill effort only if a new running
  anchor is needed.
- **2026-12-13:** actual Hyrox — the true competition benchmark.

## Results log

Append-only. One row per measurement.

| Date | Domain | Benchmark | Value | Unit | Context (RPE / conditions) | Notes |
|---|---|---|---|---|---|---|
| 2026-06-19 | Endurance | LT2 | 4:34 @ 163 | /km @ bpm | Lab lactate test | **SUPERSEDED 2026-09-06** — see the 08-30 re-anchor row. Wide method spread; LT1 not captured (started too fast) |
| 2026-07-21 | Endurance | 5k PB | <20:00 | min:s | Self-reported, not a controlled test | Establish a clean baseline in a controlled 5k TT |
| 2026-08-11 | Endurance | 30-min TT — LTHR | ~180 | bpm | Home treadmill, 06:09. **Not fresh**: 6 h hike Sun + gym & 8.9 km Mon. Garmin 23934675768 | **Protocol not met** — run as three progressive steps (5:33/km @ 171 · 5:02 @ 177 · 4:43 @ 182-183), not one even maximal effort. Treadmill auto-paused 75 s at 24:00; moving time still 29:39, so the stop cost ~20 s and is *not* why the test is compromised. HR half survives: 177 held steady 10 min with two step-ups above it, finishing at 191 (max 192). Naive Friel last-20 avg = 179.6. Corroborating: routine easy long runs sit at HR 150, impossible if LT2 HR were 163. |
| 2026-08-11 | Endurance | 30-min TT — threshold pace | VOID | /km | As above | Watch was **not paired to the treadmill** → wrist-estimated distance. Pace unusable at any confidence. Retest outdoors on a flat measured loop. |
| 2026-08-30 | Endurance | 10 km | 39:35 | min:s | Outdoor, 07:30. 10.565 km in 41:49 = 3:57.6/km, avg HR 183, max 194, 84 m gain, cadence 174. 2.4 km warm-up + 5.3 km cool-down. Garmin 24171757728 | Not tagged as a race but run as one. The strongest performance anchor on file — supersedes the self-reported 5k. |
| 2026-09-05 | Hyrox | Full station sim | 48:48 | min:s | Peñalolén, 32 laps, 5.98 km, max HR 194, TE 4.8 (VO2max), anaerobic TE 3.5, load 431. Garmin 24251406115 | Per-station splits not broken out. Log them next time — the sim is only a benchmark if the station times are recoverable. |
| 2026-09-06 | Endurance | LT2 (re-anchor) | 4:16 @ 175 | /km @ bpm | Derived, not tested. From the 08-30 10 km + the surviving HR half of the 08-11 TT | Fitting the measured pace–HR curve (6:02→133, 5:05→154, 3:58→183) and extrapolating to 175 bpm gives 4:18 from either end; Riegel on the 10 km gives 4:03. Took 4:16. `training_zones` reseeded. **Confirm with the outdoor 30-min TT in the week of 09-14** — this is an inference until then. |
| 2026-09-13 | Endurance | Official 10 km race | 40:40 | min:s | Las Condes Carrera; Garmin 9.994 km, 69 m gain, avg HR 181, max HR 195 | Replaces the scheduled outdoor 30-min TT as the current performance benchmark. Rolling course and no kilometre splits: it supports the working 4:16/km threshold prescription but does not precisely re-anchor LTHR. |
| 2026-09-22 | Body | Bodyweight | 84.4 | kg | Fitdays scale, mean of 15 fasted AM weigh-ins 2026-09-07..09-22 (range 83.8–85.4) | Replaces the self-reported 75 kg. `ATHLETE_BODYWEIGHT_KG` updated. |
| 2026-09-22 | Strength | Working loads (config refresh) | see notes | kg | Settled Garmin sets, Aug–Sep | Trap-bar 140×3 top (08-11), 130×3 back-offs · squat 100×5 (08-18) · hip thrust 110×8×3 (09-08) · pull-up bw+10×4–5 (since 08-31) · OHP 62.5×4–5 (09-21) · DB bench 2×34×8 (09-21). `ATHLETE_LOADS` updated. |

_Add new rows as you test. Keep dates ISO (YYYY-MM-DD)._
