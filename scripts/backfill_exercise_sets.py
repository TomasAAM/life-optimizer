"""One-off backfill of the exercise tables over the whole training history.

The daily pipeline only ever looks at its sync window, so switching the feed on
leaves everything before it empty. This walks the full history once and writes
both levels: the per-exercise summary, which rides along in the activity payload
and costs nothing, and the per-set detail, which costs one call per set-bearing
session.

Safe to re-run. Every session is rewritten wholesale, so a second pass produces
the same rows as the first.

Usage
-----
    python -m scripts.backfill_exercise_sets            # from FIRST_SESSION
    python -m scripts.backfill_exercise_sets 2026-07-01 # from a given date
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from ingest import exercise_sets, garmin, garmin_activities
from ingest.run import get_supabase_client

_PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# The first session in Garmin's history for this athlete. Earlier than the
# earliest strength session on purpose -- the point of a backfill is not to
# assume where the data starts.
FIRST_SESSION = date(2026, 3, 1)

# Courtesy pause between per-session calls. Garmin's SSO rate limit is the one
# thing that can lock this pipeline out of its own account, and a backfill is
# the only place that makes tens of calls in a row.
_PAUSE_S = 1.0


def main() -> None:
    """Rewrite the exercise tables for every session since the start date."""
    since = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else FIRST_SESSION
    logger.info("Backfilling exercise data from %s", since)

    supabase = get_supabase_client()
    garmin_client = garmin.get_client()

    # Runs the ordinary activity ingest over the whole history: it upserts the
    # activities themselves (idempotent) and writes the per-exercise summary as
    # a side effect, then hands back the payloads the per-set pass needs.
    activities = garmin_activities.ingest(supabase, garmin_client, since=since)
    targets = [a for a in activities if garmin_activities.has_exercise_sets(a)]
    logger.info(
        "%d activities in range, %d carrying exercise sets", len(activities), len(targets)
    )

    for index, activity in enumerate(targets, start=1):
        logger.info(
            "[%d/%d] %s %s",
            index,
            len(targets),
            activity.get("startTimeLocal"),
            activity.get("activityType", {}).get("typeKey"),
        )
        exercise_sets.ingest(supabase, garmin_client, [activity])
        if index < len(targets):
            time.sleep(_PAUSE_S)

    logger.info("Backfill complete")


if __name__ == "__main__":
    main()
