# Benchmarks — hybrid endurance (Hyrox + 21k)

Progress-tracking battery for the macrocycle toward **Hyrox #2 (2026-11-14)** and standing 21k
readiness. Benchmarks close the loop the plan can't: they verify the prescription is actually moving
fitness, so the "err high / auto-regulate by feel" approach stays honest against a measured trend.
Companion to [METHODOLOGY.md](METHODOLOGY.md) — every benchmark maps to a limiter or a goal.

**Phase 1 (now):** log results in this file. **Phase 2 (Nov build):** promote to a Supabase
`benchmark_results` table + a dashboard trend panel against targets.

## How to test (so the numbers mean something)

- **Controlled conditions.** Same course/treadmill, equipment, and (where possible) time of day. A
  benchmark is only a signal if the setup is repeatable.
- **Test in a deload-adjacent / fresh window**, not on the back of a hard block — fatigue confounds
  the read. Never test two maximal domains on the same day.
- **Log the context:** RPE, sleep/readiness, temperature, shoes, anything that moves the number.
- **Rotate, don't re-test everything every time** — see the cadence table.

## Cadence

| Benchmark | Frequency | Preferred window |
|---|---|---|
| 5k time trial | every 4–6 wk | end of a build block, post-deload |
| Threshold field test (30-min TT) | every ~6–8 wk | fresh, block boundary |
| Long-run HR/pace decoupling | continuous (each long run) | review monthly |
| Garmin VO2max estimate | continuous | directional only |
| Est-1RM squat + trap-bar DL | every ~8 wk | fresh strength day |
| Upper: pull-up / OHP / bench | every ~8 wk | once baselined (post 2026-07-23) |
| CMJ + standing broad jump | every ~4 wk | also doubles as a readiness check |
| SkiErg 1000 m / Row 1000 m TT | every ~6–8 wk | fresh |
| Hyrox station battery (Pro load) | every ~8 wk | controlled, fresh |
| Compromised-run pace | continuous (read from each sim) | — |
| Bodyweight | weekly | fasted AM |
| **Actual Hyrox race** | the event itself | **2026-11-14 = true benchmark** |

## The battery

### 1. Endurance / running — the priority (running is the limiter)

| Metric | Protocol | Baseline | Target | Why tracked |
|---|---|---|---|---|
| **5k time trial** | Flat, fresh, even pacing. | **~sub-20:00** (PB, self-reported) | **sub-19:00** (PB ~ met — retarget for the pro track) | Single-number proxy for VO2/threshold; the headline goal metric. |
| **Threshold** (LT2 proxy) | **30-min TT** (Friel): avg HR of last 20 min ≈ LTHR, avg pace ≈ threshold pace. Same route, fresh. | **4:34/km @ 163 bpm** (lab 2026-06-19, one-time anchor) | push pace down at same HR | The ceiling both the 21k and Hyrox running share — re-check so zones don't drift. Lab lactate not repeated (access/cost); field TT keeps it current. |
| **LT1** (aerobic threshold) | No recurring lactate test — approximate as a conservative easy cap below LT2 (the plan already caps easy well under the Z2 ceiling). Optional: DFA-a1 HRV app. | **not captured** — approximated | keep easy genuinely easy | Defines the true easy ceiling; without lactate we hold the safe conservative cap rather than a measured value. |
| **Long-run decoupling** | Pa:HR drift over a steady long run (Garmin/TP). | — | **< 5%** | Aerobic durability — holding pace without HR creep. Essentially free. |
| **Garmin VO2max** | Passive estimate. | — | upward trend | Noisy; directional support only, never a decision on its own. |

### 2. Strength — supports running economy + sled power

| Metric | Protocol | Baseline | Target | Why tracked |
|---|---|---|---|---|
| **Back squat est-1RM** | From an RPE-8 top set (Epley), don't test true 1RM. | working ~100–110 kg @ RPE 8×3 | progressive | Economy + sled drive; low-rep strength is the main economy lever. |
| **Trap-bar deadlift est-1RM** | RPE-8 top set. | working 130 kg @ RPE 8×3 | progressive | Posterior-chain power for sleds/carries. |
| **Hip thrust** | Load @ RPE 7–8×6–8. | 110 kg | progressive | Hip extension for running + sled push. |
| **Upper: weighted pull-up** | Max reps + weighted 3RM. | — (baseline 2026-07-23) | establish → progress | Vertical pull → sled pull, ski. |
| **Upper: overhead press / bench** | RPE-8 top set. | — (baseline 2026-07-23) | establish → progress | Press strength → wall ball, burpee push-off. |
| **Relative strength** | Best lifts ÷ bodyweight. | — | ↑ kg/bw | Power-to-weight is what Hyrox running rewards — absolute kg alone can mislead. |

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
| **Hyrox station battery / half-sim** | Standardized self-test, Pro load, controlled. | — (Nov build wk 2–3) | establish | The real, repeatable Hyrox baseline that Nov 14 is measured against. |

## Baseline plan

- **Aug 2 (Hyrox-*like* event, different stations):** log overall time, **running splits under fatigue**,
  pacing/execution notes, and the event's actual station results **flagged as event-specific / not
  Hyrox-comparable**. This seeds the running/engine line and gives a competitive-effort data point.
  Event format (Mixto): **8 km run** + deadlift 100 rep @ 34 kg · wall ball 100 rep @ 6 kg · burpee
  broad jump 80 m · sandbag lunges 100 m @ 10 kg · thrusters 100 rep @ 29 kg · farmers carry 200 m @
  2×15 kg · tyre flip-over 80 m · obstacle course (final stage). High-rep, lighter-load, no sleds/ski/row.
- **Post-race week (Aug 3–9):** free metrics only while recovering — decoupling from the last long run,
  Garmin VO2max, bodyweight, CMJ if fresh. No hard TTs.
- **Nov build, wk 2–3:** full-battery baseline once recovered and built — 5k TT, **30-min threshold TT**
  (LTHR + threshold pace), strength est-1RMs, the Hyrox station battery.
- **2026-11-14:** actual Hyrox — the true competition benchmark.

## Results log

Append-only. One row per measurement.

| Date | Domain | Benchmark | Value | Unit | Context (RPE / conditions) | Notes |
|---|---|---|---|---|---|---|
| 2026-06-19 | Endurance | LT2 | 4:34 @ 163 | /km @ bpm | Lab lactate test | Wide method spread; LT1 not captured (started too fast) |
| 2026-07-21 | Endurance | 5k PB | <20:00 | min:s | Self-reported, not a controlled test | Establish a clean baseline in a controlled 5k TT |

_Add new rows as you test. Keep dates ISO (YYYY-MM-DD)._
