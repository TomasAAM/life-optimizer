# life-optimizer-dashboard: project instructions

## Question what is already here (standing instruction)

Existing code, config and plan structure are not settled just because they exist.
In every session, especially ones that touch `plan/`, `data/plan_block.json`,
`BENCHMARKS.md` or the dashboard:

- **Challenge the training structure.** Weekly split, session mix, volume ceiling,
  zone anchor, loads, progression, taper and benchmark cadence are all open to
  question. If something looks suboptimal for the goal (pro-competitive Hyrox,
  running as the limiter), say so and propose the alternative with its reasoning
  and its trade-off. Don't just carry forward what the last block did.
- **Check the config against the data before you trust it.** Compare every athlete
  constant (`ATHLETE_LOADS`, `ATHLETE_BODYWEIGHT_KG`, the LT2 anchor, `base_weekly_km`)
  with what Garmin and the scale actually recorded. If they disagree, raise it.
  A stale constant is an under-prescription that no amount of care in a single week
  will catch.
- **Compare what was planned with what was done.** Before designing new weeks, check
  what was actually executed: km, key-session paces and HR, loads lifted, missed
  sessions. A plan the athlete isn't executing is a signal about the plan, not only
  about the athlete.
- **Innovate.** If you see a better method, metric, dashboard panel or piece of
  tooling, propose it unprompted. Keep speculation labelled as speculation and grade
  the evidence, as `METHODOLOGY.md` does.
- **Challenging is not the same as changing.** Surface the critique and the proposal,
  then follow the normal gates: a plan update is a review before `plan.persist`, and
  software changes need a plan approved before implementation (see the global
  instructions).

## Evidence before prescription (standing rule)

Every plan change goes through these checks before it is proposed (set 2026-11-03):

1. **Athlete data first.** Check what Garmin, the scale and the plan history show for
   the thing being changed.
2. **Use the highest level of evidence that exists**, in this order: systematic
   reviews, meta-analyses and position stands; randomised trials; single studies;
   documented practice of elite coaches and athletes; convention; speculation. Drop a
   level only when the higher one is missing, and say so.
3. **Check elite practice when research is thin or missing.** Use named sources
   (books, interviews, published training logs) and compare several coaches. Generic
   coaching blogs count as convention. Note how well the elite context fits this
   athlete's volume, recovery and schedule. Where research and elite practice
   disagree, show both.
4. **Retrieve, don't recall.** Search for every claim and cite it with a link in the
   same answer.
5. **Match the evidence to the claim.** State the population, duration and outcomes
   measured (for a review, the studies it pooled), and claim only what those outcomes
   support. A 5-week study of rugby players' 1RM and sprint says nothing about Hyrox
   station endurance.
6. **Grade every recommendation** with its level from point 2, next to the
   recommendation itself.
7. **Check logistics** before placing a session. The Hyrox zone is busy on Fridays,
   and a Hyrox class starts at 07:00 on Thursdays. Ask when equipment or timing is
   unknown.
8. **Every hard session gets a cut rule** (HR, pace or pain) the athlete can apply
   mid-session.

## Where the context lives

- Wiki: `~/Google Drive/ObsidianVault/life-optimizer-dashboard/`. Read `index.md` and
  `wiki/weekly-planning.md` before touching the plan.
- Zone values live in three places that must move together: `plan/zones.py`,
  `dashboard/zones.py`, and the prose in `dashboard/render.py` + `METHODOLOGY.md`.
- The GitHub repo and its Pages site are **public by Tomás's choice** (confirmed
  2026-09-22): personal training data (plan, loads, bodyweight, benchmarks) in the
  repo and on the dashboard is accepted, so don't re-raise it. Secrets are
  different: credentials, tokens and `.env` values must never be committed or
  rendered.
