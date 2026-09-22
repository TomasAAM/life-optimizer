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

## Where the context lives

- Wiki: `~/Google Drive/ObsidianVault/life-optimizer-dashboard/`. Read `index.md` and
  `wiki/weekly-planning.md` before touching the plan.
- Zone values live in three places that must move together: `plan/zones.py`,
  `dashboard/zones.py`, and the prose in `dashboard/render.py` + `METHODOLOGY.md`.
- The GitHub repo and its Pages site are **public**. Never commit personal health
  data, and keep that exposure in mind for anything new that the dashboard renders.
