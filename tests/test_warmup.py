"""Tests for warm-up ramps derived from a working weight."""

from __future__ import annotations

import pytest

from plan.config import GYM_PLATES_KG, TRAP_BAR_KG
from plan.warmup import build_ramp, format_ramp, implement_weight_kg, is_loadable


def _loads(working: float, implement: str, kind: str) -> list[float]:
    return [s.load for s in build_ramp(working, implement, kind).sets]


def test_squat_ramp_matches_the_hand_built_one() -> None:
    ramp = build_ramp(115, "barbell", "full")

    assert [s.load for s in ramp.sets] == [20, 60, 80, 100]
    assert [s.reps for s in ramp.sets] == ["8-10", "5", "3", "1-2"]
    assert [s.added for s in ramp.sets] == [(), (20,), (10,), (10,)]
    assert ramp.final_added == (5, 2.5)


def test_overhead_press_no_longer_jumps_from_the_empty_bar() -> None:
    loads = _loads(60, "barbell", "full")

    assert loads[0] == 20
    assert all(b - a <= 20 for a, b in zip(loads + [60], loads[1:] + [60]))
    assert loads[-1] >= 0.8 * 60


_BAR_LOADS = (40, 62.5, 80, 100, 115, 132.5, 140, 150, 182.5)
_PLATE_CASES = (
    [("barbell", w) for w in _BAR_LOADS]
    + [("trap_bar", w) for w in _BAR_LOADS]
    + [("belt", w) for w in (5, 10, 17.5, 22.5, 30)]
)


@pytest.mark.parametrize("kind", ["full", "short", "single"])
@pytest.mark.parametrize(("implement", "working"), _PLATE_CASES)
def test_ramps_only_ever_add_plates(implement: str, working: float, kind: str) -> None:
    """Every set is the previous set plus plates, and the plates are heaviest first."""
    ramp = build_ramp(working, implement, kind)
    pairs = 1 if implement == "belt" else 2

    stacked: list[float] = []
    for s in ramp.sets:
        stacked += list(s.added)
        assert s.load == pytest.approx(implement_weight_kg(implement) + pairs * sum(stacked))
    stacked += list(ramp.final_added)
    assert stacked == sorted(stacked, reverse=True)
    assert all(p in GYM_PLATES_KG for p in stacked)
    assert implement_weight_kg(implement) + pairs * sum(stacked) == pytest.approx(working)
    assert all(a < b for a, b in zip([s.load for s in ramp.sets], [s.load for s in ramp.sets][1:] + [working]))


def test_trap_bar_ramp_counts_the_bar() -> None:
    ramp = build_ramp(140, "trap_bar", "full")

    assert ramp.sets[0].load == TRAP_BAR_KG
    assert 0.8 * 140 <= ramp.sets[-1].load < 140


def test_belt_ramp_reads_as_added_weight() -> None:
    ramp_line, plate_line = format_ramp(build_ramp(17.5, "belt", "short"))

    assert ramp_line == "Ramp-up: +10×5 · +15×2 → +17.5 kg"
    assert plate_line == "Add to belt: +10 · +5 · then +2.5"


def test_dumbbell_ramp_is_in_pounds_with_no_plate_line() -> None:
    ramp = build_ramp(80, "dumbbell", "short")
    ramp_line, plate_line = format_ramp(ramp)

    assert ramp.unit == "lb"
    assert all(s.load % 5 == 0 for s in ramp.sets)
    assert ramp_line.endswith("→ 80 lb per hand")
    assert plate_line is None


def test_short_and_single_ramps_skip_the_empty_bar() -> None:
    assert _loads(140, "trap_bar", "short")[0] > TRAP_BAR_KG
    assert len(_loads(70, "barbell", "single")) == 1


@pytest.mark.parametrize(
    ("working", "implement"),
    [(139, "barbell"), (21.1, "belt"), (77, "dumbbell"), (10, "barbell")],
)
def test_unloadable_weights_are_rejected(working: float, implement: str) -> None:
    assert not is_loadable(working, implement)
    with pytest.raises(ValueError, match="cannot be loaded"):
        build_ramp(working, implement, "full")


def test_a_bare_bar_working_weight_has_no_ramp() -> None:
    ramp = build_ramp(20, "barbell", "full")

    assert ramp.sets == ()
    assert format_ramp(ramp) == ("", None)


def test_a_light_working_weight_drops_the_lightest_sets() -> None:
    """25 kg leaves too few loads under it for the full scheme, so it is trimmed."""
    ramp = build_ramp(25, "barbell", "full")

    assert 0 < len(ramp.sets) < 4
    assert ramp.sets[-1].reps == "1-2"
