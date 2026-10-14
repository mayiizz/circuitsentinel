"""Shared datasheet supply / variant comparison helpers.

Used by the legacy single-component check and the circuit-level rule engine.
Absolute-maximum ratings are never treated as recommended operating limits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.datasheets.models import NormalizedDatasheetFact

_VARIANT_PREFIX = "variant:"

SupplyBoundOutcome = Literal[
    "potential_violation",
    "no_violation_detected",
    "inconclusive",
]


def is_recommended_operating(fact: NormalizedDatasheetFact) -> bool:
    return "recommended_operating" in fact.qualifiers


def is_absolute_maximum_only(fact: NormalizedDatasheetFact) -> bool:
    quals = set(fact.qualifiers)
    return "absolute_maximum" in quals and "recommended_operating" not in quals


def normalize_variant_name(name: str) -> str:
    return name.strip().upper()


def variant_names_on_fact(fact: NormalizedDatasheetFact) -> set[str]:
    names: set[str] = set()
    for q in fact.qualifiers:
        if not q.startswith(_VARIANT_PREFIX):
            continue
        name = normalize_variant_name(q[len(_VARIANT_PREFIX) :])
        if name:
            names.add(name)
    return names


def fact_matches_exact_variant(fact: NormalizedDatasheetFact, variant: str) -> bool:
    target = normalize_variant_name(variant)
    if not target:
        return False
    return target in variant_names_on_fact(fact)


def recommended_variant_names(facts: list[NormalizedDatasheetFact]) -> list[str]:
    names: set[str] = set()
    for fact in facts:
        names.update(variant_names_on_fact(fact))
    return sorted(names)


def split_supply_facts(
    facts: list[NormalizedDatasheetFact],
) -> tuple[
    list[NormalizedDatasheetFact],
    list[NormalizedDatasheetFact],
    list[NormalizedDatasheetFact],
]:
    """Split supply facts into recommended, absolute-maximum-only, and unclassified."""
    recommended: list[NormalizedDatasheetFact] = []
    abs_only: list[NormalizedDatasheetFact] = []
    unclassified: list[NormalizedDatasheetFact] = []
    for fact in facts:
        if fact.fact_type not in {"supply_voltage_min", "supply_voltage_max"}:
            continue
        if fact.unit != "V":
            continue
        if is_recommended_operating(fact):
            recommended.append(fact)
        elif is_absolute_maximum_only(fact):
            abs_only.append(fact)
        else:
            unclassified.append(fact)
    return recommended, abs_only, unclassified


def input_voltage_facts(
    facts: list[NormalizedDatasheetFact],
    *,
    recommended_only: bool = True,
) -> list[NormalizedDatasheetFact]:
    out: list[NormalizedDatasheetFact] = []
    for fact in facts:
        if fact.fact_type not in {"input_voltage_min", "input_voltage_max"}:
            continue
        if fact.unit != "V":
            continue
        if recommended_only and not is_recommended_operating(fact):
            # Accept unclassified input limits when tagged only as input range.
            if "absolute_maximum" in fact.qualifiers:
                continue
        out.append(fact)
    return out


@dataclass(frozen=True)
class SupplyRangeResult:
    outcome: SupplyBoundOutcome
    reason: str
    min_v: float | None
    max_v: float | None
    selected_variant: str | None
    scoped_facts: list[NormalizedDatasheetFact]
    missing_information: list[str]


def resolve_recommended_supply_range(
    facts: list[NormalizedDatasheetFact],
    *,
    device_variant: str | None = None,
) -> SupplyRangeResult:
    """Resolve a single recommended min/max range (exact variant when required)."""
    recommended, _abs_only, _unclassified = split_supply_facts(facts)
    selected_raw = (device_variant or "").strip() or None
    selected = normalize_variant_name(selected_raw) if selected_raw else None

    if not recommended:
        return SupplyRangeResult(
            outcome="inconclusive",
            reason="No recommended_operating supply voltage facts are available.",
            min_v=None,
            max_v=None,
            selected_variant=selected,
            scoped_facts=[],
            missing_information=[
                "recommended_operating supply_voltage_min and/or supply_voltage_max"
            ],
        )

    available = recommended_variant_names(recommended)
    mins_all = [f for f in recommended if f.fact_type == "supply_voltage_min"]
    maxs_all = [f for f in recommended if f.fact_type == "supply_voltage_max"]
    multi_range = len({f.value for f in mins_all}) > 1 or len({f.value for f in maxs_all}) > 1

    if available and multi_range and selected is None:
        return SupplyRangeResult(
            outcome="inconclusive",
            reason=(
                "Multiple device-variant recommended_operating supply ranges are present; "
                "provide device_variant explicitly."
            ),
            min_v=None,
            max_v=None,
            selected_variant=None,
            scoped_facts=recommended,
            missing_information=["device_variant"],
        )

    scoped = recommended
    if selected is not None:
        scoped = [f for f in recommended if fact_matches_exact_variant(f, selected)]
        if not scoped:
            return SupplyRangeResult(
                outcome="inconclusive",
                reason=(
                    f"No recommended_operating supply facts exactly match device "
                    f"variant {selected!r}."
                ),
                min_v=None,
                max_v=None,
                selected_variant=selected,
                scoped_facts=recommended,
                missing_information=[f"variant:{selected} recommended supply facts"],
            )

    mins = [f for f in scoped if f.fact_type == "supply_voltage_min"]
    maxs = [f for f in scoped if f.fact_type == "supply_voltage_max"]
    if len({f.value for f in mins}) > 1 or len({f.value for f in maxs}) > 1:
        return SupplyRangeResult(
            outcome="inconclusive",
            reason="Conflicting recommended_operating supply limits; not choosing among them.",
            min_v=None,
            max_v=None,
            selected_variant=selected,
            scoped_facts=scoped,
            missing_information=["A single consistent recommended_operating supply range"],
        )

    ds_min = mins[0].value if mins else None
    ds_max = maxs[0].value if maxs else None
    missing: list[str] = []
    if ds_min is None:
        missing.append("recommended_operating supply_voltage_min")
    if ds_max is None:
        missing.append("recommended_operating supply_voltage_max")

    if ds_min is None and ds_max is None:
        return SupplyRangeResult(
            outcome="inconclusive",
            reason="Recommended operating supply facts lacked usable min/max values.",
            min_v=None,
            max_v=None,
            selected_variant=selected,
            scoped_facts=scoped,
            missing_information=missing,
        )

    return SupplyRangeResult(
        outcome="no_violation_detected",
        reason="Resolved recommended_operating supply range.",
        min_v=ds_min,
        max_v=ds_max,
        selected_variant=selected,
        scoped_facts=scoped,
        missing_information=missing,
    )


def compare_stated_to_range(
    stated_v: float,
    *,
    min_v: float | None,
    max_v: float | None,
) -> SupplyBoundOutcome:
    below = min_v is not None and stated_v < min_v
    above = max_v is not None and stated_v > max_v
    if below or above:
        return "potential_violation"
    return "no_violation_detected"


def resolve_absolute_maximum_supply_bounds(
    facts: list[NormalizedDatasheetFact],
) -> tuple[float | None, float | None, list[NormalizedDatasheetFact]]:
    """Return abs-max-only supply min/max when unambiguous."""
    _rec, abs_only, _unc = split_supply_facts(facts)
    mins = [f for f in abs_only if f.fact_type == "supply_voltage_min"]
    maxs = [f for f in abs_only if f.fact_type == "supply_voltage_max"]
    if len({f.value for f in mins}) > 1 or len({f.value for f in maxs}) > 1:
        return None, None, abs_only
    return (
        mins[0].value if mins else None,
        maxs[0].value if maxs else None,
        abs_only,
    )


__all__ = [
    "SupplyBoundOutcome",
    "SupplyRangeResult",
    "compare_stated_to_range",
    "fact_matches_exact_variant",
    "input_voltage_facts",
    "is_absolute_maximum_only",
    "is_recommended_operating",
    "normalize_variant_name",
    "recommended_variant_names",
    "resolve_absolute_maximum_supply_bounds",
    "resolve_recommended_supply_range",
    "split_supply_facts",
    "variant_names_on_fact",
]
