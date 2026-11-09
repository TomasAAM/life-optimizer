"""Warm-up ramps derived from a strength step's working weight.

The plan prescribes only the working weight. This module derives the warm-up sets
in front of it so that, between sets, the athlete only ever adds plates. The plates
for the working weight are stacked heaviest first, and every warm-up load is a
prefix of that stack: the bare bar, then the bar plus the first plates, and so on.
The working weight can usually be stacked several ways (115 kg on a 20 kg bar is
25+20+2.5 a side, or 20+10+10+5+2.5); the search picks the stack whose prefixes
sit closest to the scheme's target fractions, preferring fewer plates on a tie.

Barbell and trap-bar loads are totals in kg with plates in pairs. A dip belt
carries one stack of kg plates and its load is the weight added to bodyweight.
Dumbbells in this gym are in pounds and step by ``DUMBBELL_STEP_LB``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Literal

from plan.config import (
    BARBELL_KG,
    DUMBBELL_STEP_LB,
    GYM_PLATES_KG,
    RAMP_SCHEMES,
    TRAP_BAR_KG,
    RampStep,
)

Implement = Literal["barbell", "trap_bar", "dumbbell", "belt"]
RampKind = Literal["full", "short", "single"]

# Plate arithmetic runs in quarter-kilograms so 1.25 kg plates stay exact integers.
_Q = 4
_MAX_PLATES_PER_STACK = 8
# Each extra plate on a stack costs as much as missing one warm-up target by 10% of
# the working weight. Without it the search reaches every target exactly by
# building stacks of 1.25 kg plates, which nobody wants to load.
_PLATE_PENALTY = 0.01


@dataclass(frozen=True)
class RampSet:
    """One warm-up set.

    Parameters
    ----------
    load : float
        Load for the set: total kg on a bar, kg added on a belt (0 is bodyweight),
        or lb per dumbbell.
    reps : str
        Reps for the set, e.g. ``"5"`` or ``"1-2"``.
    added : tuple of float
        Plates (kg) to add before this set: per side on a bar, onto the belt for a
        belt. Empty for the bare implement and for dumbbells.
    """

    load: float
    reps: str
    added: tuple[float, ...]


@dataclass(frozen=True)
class WarmupRamp:
    """The warm-up sets in front of one working weight.

    Parameters
    ----------
    implement : {"barbell", "trap_bar", "dumbbell", "belt"}
        What is being loaded.
    working : float
        The working weight, in the implement's unit.
    sets : tuple of RampSet
        Warm-up sets, lightest first. Empty when no ramp fits below the working
        weight (e.g. a working weight equal to the bare bar).
    final_added : tuple of float
        Plates to add after the last warm-up set to reach the working weight.
    """

    implement: Implement
    working: float
    sets: tuple[RampSet, ...]
    final_added: tuple[float, ...]

    @property
    def unit(self) -> str:
        """Unit of every load in the ramp: ``"lb"`` for dumbbells, else ``"kg"``."""
        return "lb" if self.implement == "dumbbell" else "kg"


def implement_weight_kg(implement: Implement) -> float:
    """Return the empty weight counted in a load for a plate-loaded implement.

    Parameters
    ----------
    implement : {"barbell", "trap_bar", "belt"}
        A plate-loaded implement. A belt counts as 0 because its load is the
        weight added to bodyweight.

    Returns
    -------
    float
        The implement's empty weight in kg.

    Raises
    ------
    ValueError
        For dumbbells, which are not plate-loaded.

    Examples
    --------
    >>> implement_weight_kg("barbell")
    20.0
    """
    if implement == "barbell":
        return BARBELL_KG
    if implement == "trap_bar":
        return TRAP_BAR_KG
    if implement == "belt":
        return 0.0
    raise ValueError(f"{implement} is not plate-loaded.")


def _stack_target_q(working: float, implement: Implement) -> int | None:
    """Return the plate weight one stack must carry, in quarter-kg, or None if impossible."""
    plates_total = working - implement_weight_kg(implement)
    per_stack = plates_total if implement == "belt" else plates_total / 2
    quarters = per_stack * _Q
    if per_stack < 0 or abs(quarters - round(quarters)) > 1e-9:
        return None
    return round(quarters)


def _stacks(target_q: int, max_plate_q: int, depth: int) -> Iterator[tuple[int, ...]]:
    """Yield every heaviest-first plate stack (quarter-kg) that sums to ``target_q``."""
    if target_q == 0:
        yield ()
        return
    if depth == 0:
        return
    for plate_q in sorted((round(p * _Q) for p in GYM_PLATES_KG), reverse=True):
        if plate_q <= max_plate_q and plate_q <= target_q:
            for rest in _stacks(target_q - plate_q, plate_q, depth - 1):
                yield (plate_q,) + rest


def is_loadable(working: float, implement: Implement) -> bool:
    """Say whether a working weight can be built from the gym's equipment.

    Parameters
    ----------
    working : float
        Working weight: total kg on a bar, kg added on a belt, lb per dumbbell.
    implement : {"barbell", "trap_bar", "dumbbell", "belt"}
        What is being loaded.

    Returns
    -------
    bool
        True if the weight is reachable.

    Examples
    --------
    >>> is_loadable(115, "barbell")
    True
    >>> is_loadable(139, "barbell")
    False
    """
    if implement == "dumbbell":
        steps = working / DUMBBELL_STEP_LB
        return working >= DUMBBELL_STEP_LB and abs(steps - round(steps)) < 1e-9
    target_q = _stack_target_q(working, implement)
    if target_q is None:
        return False
    return next(_stacks(target_q, target_q, _MAX_PLATES_PER_STACK), None) is not None


def _pick(candidates: list[float], scheme: tuple[RampStep, ...], working: float) -> tuple[float, list[int]] | None:
    """Match each scheme step to a strictly heavier candidate load, closest first.

    Returns the summed squared relative miss and the chosen candidate indices, or
    None when there are fewer candidates than steps.
    """
    chosen: list[int] = []
    cost = 0.0
    last = -1
    for step in scheme:
        target = step.fraction * working
        options = [(abs(c - target), j) for j, c in enumerate(candidates) if j > last]
        if not options:
            return None
        miss, j = min(options)
        chosen.append(j)
        cost += (miss / working) ** 2
        last = j
    return cost, chosen


def _plate_ramp(working: float, implement: Implement, scheme: tuple[RampStep, ...]) -> WarmupRamp | None:
    """Build a bar or belt ramp for one scheme, or None if the scheme does not fit."""
    target_q = _stack_target_q(working, implement)
    if target_q is None:
        return None
    pairs = 1 if implement == "belt" else 2
    empty = implement_weight_kg(implement)

    best: tuple[tuple[float, int], tuple[int, ...], list[int]] | None = None
    for stack in _stacks(target_q, target_q, _MAX_PLATES_PER_STACK):
        prefix_q = [sum(stack[:i]) for i in range(len(stack))]
        candidates = [empty + pairs * q / _Q for q in prefix_q]
        picked = _pick(candidates, scheme, working)
        if picked is None:
            continue
        key = (round(picked[0] + _PLATE_PENALTY * len(stack), 9), len(stack))
        if best is None or key < best[0]:
            best = (key, stack, picked[1])
    if best is None:
        return None

    _, stack, chosen = best
    plates = [q / _Q for q in stack]
    sets: list[RampSet] = []
    previous = 0
    for step, index in zip(scheme, chosen):
        load = empty + pairs * sum(plates[:index])
        sets.append(RampSet(load=load, reps=step.reps, added=tuple(plates[previous:index])))
        previous = index
    return WarmupRamp(implement, working, tuple(sets), tuple(plates[previous:]))


def _dumbbell_ramp(working: float, scheme: tuple[RampStep, ...]) -> WarmupRamp | None:
    """Build a dumbbell ramp in lb, or None if the scheme does not fit."""
    lifts = [s for s in scheme if s.fraction > 0]
    count = round(working / DUMBBELL_STEP_LB)
    candidates = [DUMBBELL_STEP_LB * k for k in range(1, count)]
    picked = _pick(candidates, tuple(lifts), working)
    if picked is None:
        return None
    sets = tuple(RampSet(load=candidates[j], reps=s.reps, added=()) for s, j in zip(lifts, picked[1]))
    return WarmupRamp("dumbbell", working, sets, ())


def build_ramp(working: float, implement: Implement, kind: RampKind) -> WarmupRamp:
    """Derive the warm-up ramp in front of a working weight.

    If the full scheme does not fit below the working weight (too few loads exist
    between the bare implement and the working weight), the lightest sets are
    dropped until it does.

    Parameters
    ----------
    working : float
        Working weight: total kg on a bar, kg added on a belt, lb per dumbbell.
    implement : {"barbell", "trap_bar", "dumbbell", "belt"}
        What is being loaded.
    kind : {"full", "short", "single"}
        Ramp scheme from ``RAMP_SCHEMES``.

    Returns
    -------
    WarmupRamp
        The warm-up sets and the plates left to add for the working weight.

    Raises
    ------
    ValueError
        If the working weight cannot be loaded with the gym's equipment.

    Examples
    --------
    >>> [s.load for s in build_ramp(115, "barbell", "full").sets]
    [20.0, 60.0, 80.0, 100.0]
    """
    if not is_loadable(working, implement):
        raise ValueError(f"{working} cannot be loaded on a {implement} with this gym's equipment.")
    scheme = RAMP_SCHEMES[kind]
    for start in range(len(scheme)):
        trimmed = scheme[start:]
        ramp = _dumbbell_ramp(working, trimmed) if implement == "dumbbell" else _plate_ramp(working, implement, trimmed)
        if ramp is not None:
            return ramp
    return WarmupRamp(implement, working, (), ())


def _num(value: float) -> str:
    """Format a load without a trailing ``.0`` (60.0 -> '60', 62.5 -> '62.5')."""
    return f"{value:g}"


def _plates(plates: tuple[float, ...]) -> str:
    """Format a plate group as '+20 +2.5'."""
    return " ".join(f"+{_num(p)}" for p in plates)


def format_ramp(ramp: WarmupRamp) -> tuple[str, str | None]:
    """Render a ramp as a card line and, for plate-loaded implements, a plate line.

    Parameters
    ----------
    ramp : WarmupRamp
        The ramp to render.

    Returns
    -------
    tuple of (str, str or None)
        The ramp line, e.g. ``"Ramp-up: 20×8-10 · 60×5 · 80×3 · 100×1-2 → 115 kg"``,
        and the plate line, e.g. ``"Add per side: bar · +20 · +10 · +10 · then +5 +2.5"``.
        The plate line is None for dumbbells. The ramp line is empty when the
        ramp has no sets.

    Examples
    --------
    >>> format_ramp(build_ramp(60, "barbell", "full"))[0]
    'Ramp-up: 20×8-10 · 30×5 · 40×3 · 50×1-2 → 60 kg'
    """
    if not ramp.sets:
        return "", None
    belt = ramp.implement == "belt"

    def load(value: float) -> str:
        if belt:
            return "BW" if value == 0 else f"+{_num(value)}"
        return _num(value)

    sets = " · ".join(f"{load(s.load)}×{s.reps}" for s in ramp.sets)
    suffix = " lb per hand" if ramp.implement == "dumbbell" else " kg"
    line = f"Ramp-up: {sets} → {load(ramp.working)}{suffix}"
    if ramp.implement == "dumbbell":
        return line, None

    empty_label = "BW" if belt else "bar"
    groups = [_plates(s.added) if s.added else empty_label for s in ramp.sets]
    where = "Add to belt" if belt else "Add per side"
    plate_line = f"{where}: {' · '.join(groups)} · then {_plates(ramp.final_added)}"
    return line, plate_line
