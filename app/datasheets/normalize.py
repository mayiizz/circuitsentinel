"""Normalize a small set of scalar electrical facts from raw datasheet evidence.

Conservative text-grounded parsing only. Ambiguous lines become unresolved
records — never guessed facts. Does not match components or judge circuits.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Callable

from app.datasheets.models import (
    FactType,
    NormalizedDatasheetFact,
    RawDatasheetEvidence,
    UnresolvedNormalization,
)

PHASE3B_LIMITATIONS = [
    "Phase 3B normalizes only a small set of scalar voltage facts clearly stated in page text.",
    "Ambiguous, unitless, or conflicting candidates are reported as unresolved — not guessed.",
    "Normalized facts are not engineering interpretations or circuit pass/fail judgments.",
    "Datasheet facts are not automatically associated with schematic components.",
    "No OCR or invented manufacturer claims; section/table context is required to tag "
    "recommended_operating or absolute_maximum supply bounds.",
]

SUPPORTED_FACT_TYPES: tuple[FactType, ...] = (
    "supply_voltage_max",
    "supply_voltage_min",
    "input_voltage_max",
    "input_voltage_min",
)

_SUPPLY_LABEL = (
    r"(?:operating\s+)?(?:supply\s+voltage|supply\s+voltage\s+range|vcc|vdd)"
)
# "range" is handled only by the dedicated range pattern to avoid double matches.
_INPUT_LABEL = r"(?:input\s+voltage(?:\s+limit|\s+limits)?|vin)"
_INPUT_LABEL_OR_RANGE = (
    r"(?:input\s+voltage(?:\s+range|\s+limit|\s+limits)?|vin)"
)

_ABS_MAX_NEAR = re.compile(r"absolute\s+maximum(?:\s+ratings?)?", re.IGNORECASE)
_RECOMMENDED_NEAR = re.compile(
    r"recommended\s+operating(?:\s+conditions?)?", re.IGNORECASE
)

# Figure captions / typical-characteristics parentheses: not rated limits.
_FIGURE_NEAR = re.compile(r"figure\s+\d", re.IGNORECASE)
_TYPICAL_CHARS_NEAR = re.compile(r"typical\s+characteristics", re.IGNORECASE)
_RAIL_NAME_LABEL = re.compile(r"^(?:vcc|vdd)$", re.IGNORECASE)

# Unitless electrical label + number (no V/volts) → unresolved.
# Require a complete integer/decimal token; do not split "-0.3" at the "0".
_UNITLESS_CANDIDATE = re.compile(
    rf"(?P<label>{_SUPPLY_LABEL}|{_INPUT_LABEL_OR_RANGE})\s*[:=]?\s*"
    rf"(?P<val>[+-]?(?:\d+\.\d+|\d+))(?!\d)(?!\.\d)(?!\s*(?:V|volts?)\b)",
    re.IGNORECASE,
)

# TI-style multi-variant supply tables under a rated section.
_SECTION_HEADER = re.compile(
    r"(?P<section>absolute\s+maximum(?:\s+ratings?)?|"
    r"recommended\s+operating(?:\s+conditions)?)",
    re.IGNORECASE,
)
_NEXT_MAJOR_SECTION = re.compile(
    r"\n\s*\d+\.\d+\s+\S+",
)
_SUPPLY_PARAM_START = re.compile(
    r"(?:VS\s+)?Supply\s+voltage\b[^\n]*",
    re.IGNORECASE,
)
_SUPPLY_BLOCK_END = re.compile(
    r"(?:^|\n)\s*(?:"
    r"VCM\b|"
    r"Differential\s+input|"
    r"Input\s+voltage\b|"
    r"Duration\s+of|"
    r"TA\b|"
    r"Operating\s+ambient\s+temperature|"
    r"Operating\s+virtual-junction|"
    r"Storage\s+temperature|"
    r"Thermal\s+Information|"
    r"ESD\s+Ratings|"
    r"\d+\.\d+\s+\S+"
    r")",
    re.IGNORECASE,
)
_DEVICE_TOKEN = r"LM\d+[A-Z]*"
_VARIANT_MIN_MAX = re.compile(
    rf"(?P<prefix>V?)(?P<devices>{_DEVICE_TOKEN}(?:\s*,\s*{_DEVICE_TOKEN})*)\s+"
    rf"(?P<min>[+-]?\d+(?:\.\d+)?)\s+(?P<max>[+-]?\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)
_VARIANT_ABS_OR = re.compile(
    rf"(?P<prefix>V?)(?P<devices>{_DEVICE_TOKEN}(?:\s*,\s*{_DEVICE_TOKEN})*)\s*"
    rf"(?:±|\+/-)\s*(?P<dual>\d+(?:\.\d+)?)\s+or\s+(?P<single>\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _Emit:
    fact_type: FactType
    value: float
    unit: str
    extra_qualifiers: tuple[str, ...] = ()


Handler = Callable[[re.Match[str]], list[_Emit] | None]


def _unit(raw: str) -> str:
    return "V"


def _handle_dual_supply(match: re.Match[str]) -> list[_Emit] | None:
    mag = float(match.group("mag"))
    unit = _unit(match.group("unit"))
    return [
        _Emit("supply_voltage_max", mag, unit, ("dual_rail_symmetric",)),
        _Emit("supply_voltage_min", -mag, unit, ("dual_rail_symmetric",)),
    ]


def _handle_input_range(match: re.Match[str]) -> list[_Emit] | None:
    vlo = float(match.group("vlo"))
    vhi = float(match.group("vhi"))
    unit = _unit(match.group("unit"))
    if vlo > vhi:
        return None  # caller records unresolved
    return [
        _Emit("input_voltage_min", vlo, unit),
        _Emit("input_voltage_max", vhi, unit),
    ]


def _handle_named_value(fact_type: FactType) -> Handler:
    def _inner(match: re.Match[str]) -> list[_Emit] | None:
        return [
            _Emit(fact_type, float(match.group("value")), _unit(match.group("unit")))
        ]

    return _inner


@dataclass(frozen=True)
class _Pattern:
    name: str
    regex: re.Pattern[str]
    handler: Handler
    attempted_fact_type: FactType | None = None
    inverted_range_unresolved: bool = False


_PATTERNS: tuple[_Pattern, ...] = (
    _Pattern(
        name="dual_supply",
        regex=re.compile(
            rf"(?P<label>{_SUPPLY_LABEL})\s*"
            rf"(?:max(?:imum)?|min(?:imum)?|range)?\s*"
            rf"[:=]?\s*(?:±|\+/-)\s*(?P<mag>\d+(?:\.\d+)?)\s*(?P<unit>V|volts?)\b",
            re.IGNORECASE,
        ),
        handler=_handle_dual_supply,
        attempted_fact_type="supply_voltage_max",
    ),
    _Pattern(
        name="supply_max",
        regex=re.compile(
            rf"(?P<label>{_SUPPLY_LABEL})\s+max(?:imum)?\s*[:=]?\s*"
            rf"(?P<value>[+-]?\d+(?:\.\d+)?)\s*(?P<unit>V|volts?)\b",
            re.IGNORECASE,
        ),
        handler=_handle_named_value("supply_voltage_max"),
        attempted_fact_type="supply_voltage_max",
    ),
    _Pattern(
        name="supply_min",
        regex=re.compile(
            rf"(?P<label>{_SUPPLY_LABEL})\s+min(?:imum)?\s*[:=]?\s*"
            rf"(?P<value>[+-]?\d+(?:\.\d+)?)\s*(?P<unit>V|volts?)\b",
            re.IGNORECASE,
        ),
        handler=_handle_named_value("supply_voltage_min"),
        attempted_fact_type="supply_voltage_min",
    ),
    _Pattern(
        name="supply_bare",
        regex=re.compile(
            rf"(?P<label>{_SUPPLY_LABEL})\s*[:=]?\s*"
            rf"(?P<value>[+-]?\d+(?:\.\d+)?)\s*(?P<unit>V|volts?)\b",
            re.IGNORECASE,
        ),
        handler=_handle_named_value("supply_voltage_max"),
        attempted_fact_type="supply_voltage_max",
    ),
    _Pattern(
        name="input_range",
        regex=re.compile(
            rf"(?P<label>input\s+voltage(?:\s+range)?)\s*[:=]?\s*"
            rf"(?P<vlo>[+-]?\d+(?:\.\d+)?)\s*(?:V|volts?)?\s*"
            rf"(?:to|–|—|-)\s*"
            rf"(?P<vhi>[+-]?\d+(?:\.\d+)?)\s*(?P<unit>V|volts?)\b",
            re.IGNORECASE,
        ),
        handler=_handle_input_range,
        attempted_fact_type="input_voltage_min",
        inverted_range_unresolved=True,
    ),
    _Pattern(
        name="input_max",
        regex=re.compile(
            rf"(?P<label>{_INPUT_LABEL})\s+max(?:imum)?\s*[:=]?\s*"
            rf"(?P<value>[+-]?\d+(?:\.\d+)?)\s*(?P<unit>V|volts?)\b",
            re.IGNORECASE,
        ),
        handler=_handle_named_value("input_voltage_max"),
        attempted_fact_type="input_voltage_max",
    ),
    _Pattern(
        name="input_min",
        regex=re.compile(
            rf"(?P<label>{_INPUT_LABEL})\s+min(?:imum)?\s*[:=]?\s*"
            rf"(?P<value>[+-]?\d+(?:\.\d+)?)\s*(?P<unit>V|volts?)\b",
            re.IGNORECASE,
        ),
        handler=_handle_named_value("input_voltage_min"),
        attempted_fact_type="input_voltage_min",
    ),
    _Pattern(
        name="input_bare",
        regex=re.compile(
            rf"(?P<label>{_INPUT_LABEL})\s*[:=]?\s*"
            rf"(?P<value>[+-]?\d+(?:\.\d+)?)\s*(?P<unit>V|volts?)\b",
            re.IGNORECASE,
        ),
        handler=_handle_named_value("input_voltage_max"),
        attempted_fact_type="input_voltage_max",
    ),
)


def _fact_id(
    document_id: str, fact_type: FactType, page_number: int, excerpt: str
) -> str:
    digest = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()[:12]
    return f"{document_id}:fact:{fact_type}:page:{page_number}:{digest}"


def _unresolved_id(
    document_id: str,
    page_number: int | None,
    reason_key: str,
    candidate: str,
) -> str:
    digest = hashlib.sha256(f"{reason_key}:{candidate}".encode("utf-8")).hexdigest()[
        :12
    ]
    page_part = f"page:{page_number}" if page_number is not None else "page:unknown"
    return f"{document_id}:unresolved:{page_part}:{digest}"


def _qualifiers_near(text: str, match_start: int) -> list[str]:
    window = text[max(0, match_start - 160) : match_start]
    quals: list[str] = []
    if _ABS_MAX_NEAR.search(window):
        quals.append("absolute_maximum")
    if _RECOMMENDED_NEAR.search(window):
        quals.append("recommended_operating")
    return quals


def _variant_key(quals: list[str], extra: tuple[str, ...]) -> tuple[str, ...]:
    """Conflict key component so distinct device-variant rows can coexist."""
    variants = [
        q for q in [*quals, *extra] if q.startswith("variant:")
    ]
    return tuple(sorted(variants))


def _parse_devices(devices_blob: str) -> list[str]:
    return [
        tok.strip().upper()
        for tok in re.findall(_DEVICE_TOKEN, devices_blob, flags=re.IGNORECASE)
    ]


def _section_kind(header: str) -> str | None:
    if _RECOMMENDED_NEAR.search(header):
        return "recommended_operating"
    if _ABS_MAX_NEAR.search(header):
        return "absolute_maximum"
    return None


def _supply_block_has_volt_unit(block: str) -> bool:
    """True when the extracted supply block shows volt units (V / volts)."""
    if re.search(r"\bvolts?\b", block, re.IGNORECASE):
        return True
    # UNIT column value often glues to the next device row: "VLM158..."
    if re.search(rf"(?:^|\n|\s)V(?={_DEVICE_TOKEN})", block, re.IGNORECASE):
        return True
    # Standalone unit token on its own line or after MAX header.
    if re.search(r"(?:^|\n)\s*V\s*(?:\n|$)", block):
        return True
    if re.search(r"\bUNIT\b[\s\S]{0,80}\bV\b", block, re.IGNORECASE):
        return True
    return False


def _is_characterization_supply(
    text: str, match: re.Match[str], quals: list[str]
) -> bool:
    """Rail names like VCC=15 V in figures/test conditions are not rated limits."""
    if "recommended_operating" in quals or "absolute_maximum" in quals:
        return False
    label = match.groupdict().get("label") or ""
    if not _RAIL_NAME_LABEL.match(label.strip()):
        return False
    start, end = match.start(), match.end()
    before = text[max(0, start - 120) : start]
    around = text[max(0, start - 8) : min(len(text), end + 8)]
    if _FIGURE_NEAR.search(before) or _TYPICAL_CHARS_NEAR.search(
        text[max(0, start - 400) : start]
    ):
        return True
    # Parenthetical test condition: "... Frequency (VCC = 15 V)"
    if "(" in before[-12:] and ")" in around[len(around) // 2 :]:
        return True
    if re.search(r"\(VCC\s*=", around, re.IGNORECASE) or re.search(
        r"\(VDD\s*=", around, re.IGNORECASE
    ):
        return True
    # Bare VCC/VDD without a rated-section qualifier is not treated as a limit.
    return True


def _iter_rated_supply_sections(text: str) -> list[tuple[str, int, int]]:
    """Return (section_qualifier, start, end) spans for rated sections on a page."""
    sections: list[tuple[str, int, int]] = []
    for match in _SECTION_HEADER.finditer(text):
        kind = _section_kind(match.group("section"))
        if kind is None:
            continue
        start = match.start()
        next_hdr = _NEXT_MAJOR_SECTION.search(text, match.end())
        next_rated = None
        for other in _SECTION_HEADER.finditer(text, match.end()):
            next_rated = other
            break
        end = len(text)
        if next_hdr:
            end = min(end, next_hdr.start())
        if next_rated:
            end = min(end, next_rated.start())
        sections.append((kind, start, end))
    return sections


def _extract_variant_supply_rows(
    text: str,
    *,
    section_kind: str,
    section_start: int,
    section_end: int,
) -> list[tuple[str, float, float, str, list[str]]]:
    """Parse device-variant MIN/MAX (or ±dual or single) supply rows.

    Returns list of (excerpt, min_v, max_v, unit, variant_names).
    """
    section = text[section_start:section_end]
    rows: list[tuple[str, float, float, str, list[str]]] = []
    for param in _SUPPLY_PARAM_START.finditer(section):
        block_start = param.start()
        end_match = _SUPPLY_BLOCK_END.search(section, param.end())
        block_end = end_match.start() if end_match else len(section)
        block = section[block_start:block_end]
        if not _supply_block_has_volt_unit(block):
            continue

        abs_matches = list(_VARIANT_ABS_OR.finditer(block))
        minmax_matches = list(_VARIANT_MIN_MAX.finditer(block))

        if section_kind == "absolute_maximum" and abs_matches:
            for m in abs_matches:
                devices = _parse_devices(m.group("devices"))
                if not devices:
                    continue
                # Prefer the explicit single-ended limit ("±16 or 32" → 32 V).
                max_v = float(m.group("single"))
                excerpt = text[
                    section_start + block_start + m.start() : section_start
                    + block_start
                    + m.end()
                ]
                rows.append((excerpt, float("nan"), max_v, "V", devices))
            continue

        if section_kind == "recommended_operating" and minmax_matches:
            for m in minmax_matches:
                devices = _parse_devices(m.group("devices"))
                if not devices:
                    continue
                min_v = float(m.group("min"))
                max_v = float(m.group("max"))
                if min_v > max_v:
                    continue
                # Temperature-like rows (negative max) are not supply rows.
                if max_v < 0:
                    continue
                excerpt = text[
                    section_start + block_start + m.start() : section_start
                    + block_start
                    + m.end()
                ]
                rows.append((excerpt, min_v, max_v, "V", devices))
    return rows


def normalize_raw_evidence(
    raw_evidence: list[RawDatasheetEvidence],
    *,
    source_content_sha256: str,
    document_id: str,
) -> tuple[list[NormalizedDatasheetFact], list[UnresolvedNormalization]]:
    """Derive normalized facts from raw evidence without mutating it."""
    facts: list[NormalizedDatasheetFact] = []
    unresolved: list[UnresolvedNormalization] = []
    accepted: dict[tuple[FactType, int, tuple[str, ...]], float] = {}
    seen_fact_ids: set[str] = set()
    seen_unresolved_ids: set[str] = set()
    # Spans already covered by rated-table extraction (page, start, end).
    covered_spans: list[tuple[int, int, int]] = []

    def add_unresolved(
        *,
        reason: str,
        reason_key: str,
        candidate: str,
        evidence: RawDatasheetEvidence,
        attempted: FactType | None,
    ) -> None:
        uid = _unresolved_id(
            document_id, evidence.page_number, reason_key, candidate
        )
        if uid in seen_unresolved_ids:
            return
        seen_unresolved_ids.add(uid)
        unresolved.append(
            UnresolvedNormalization(
                id=uid,
                reason=reason,
                attempted_fact_type=attempted,
                page_number=evidence.page_number,
                supporting_evidence_id=evidence.id,
                candidate_text=candidate,
            )
        )

    def emit(
        *,
        evidence: RawDatasheetEvidence,
        excerpt: str,
        quals: list[str],
        item: _Emit,
    ) -> None:
        if excerpt not in evidence.text:
            # Refuse facts whose excerpt is not an exact raw substring.
            add_unresolved(
                reason=(
                    "Candidate supply bound excerpt is not an exact substring of "
                    "page text; not normalized."
                ),
                reason_key="non_substring_excerpt",
                candidate=excerpt[:200],
                evidence=evidence,
                attempted=item.fact_type,
            )
            return
        vkey = _variant_key(quals, item.extra_qualifiers)
        key = (item.fact_type, evidence.page_number, vkey)
        if key in accepted and accepted[key] != item.value:
            # Drop prior fact of this type/variant on this page; record conflict.
            facts[:] = [
                f
                for f in facts
                if not (
                    f.fact_type == item.fact_type
                    and f.page_number == evidence.page_number
                    and _variant_key(f.qualifiers, ()) == vkey
                )
            ]
            accepted.pop(key, None)
            add_unresolved(
                reason=(
                    f"Conflicting values for {item.fact_type} on page "
                    f"{evidence.page_number}; not choosing between them."
                ),
                reason_key=f"conflict:{item.fact_type}",
                candidate=excerpt,
                evidence=evidence,
                attempted=item.fact_type,
            )
            return
        if key in accepted and accepted[key] == item.value:
            return
        fid = _fact_id(document_id, item.fact_type, evidence.page_number, excerpt)
        if fid in seen_fact_ids:
            return
        seen_fact_ids.add(fid)
        accepted[key] = item.value
        facts.append(
            NormalizedDatasheetFact(
                id=fid,
                fact_type=item.fact_type,
                value=item.value,
                unit=item.unit,
                qualifiers=[*quals, *item.extra_qualifiers],
                source_content_sha256=source_content_sha256,
                page_number=evidence.page_number,
                supporting_evidence_id=evidence.id,
                supporting_excerpt=excerpt,
            )
        )

    def emit_rated_tables(evidence: RawDatasheetEvidence) -> None:
        text = evidence.text
        for kind, sec_start, sec_end in _iter_rated_supply_sections(text):
            rows = _extract_variant_supply_rows(
                text,
                section_kind=kind,
                section_start=sec_start,
                section_end=sec_end,
            )
            if not rows:
                continue
            # Mark the supply-parameter region covered so line patterns do not
            # double-count table body numbers as bare VCC facts.
            covered_spans.append((evidence.page_number, sec_start, sec_end))

            range_keys: set[tuple[float, float]] = set()
            for excerpt, min_v, max_v, unit, devices in rows:
                variant_quals = tuple(f"variant:{name}" for name in devices)
                quals = [kind]
                if min_v == min_v:  # not NaN
                    range_keys.add((min_v, max_v))
                    emit(
                        evidence=evidence,
                        excerpt=excerpt,
                        quals=quals,
                        item=_Emit(
                            "supply_voltage_min",
                            min_v,
                            unit,
                            variant_quals,
                        ),
                    )
                    emit(
                        evidence=evidence,
                        excerpt=excerpt,
                        quals=quals,
                        item=_Emit(
                            "supply_voltage_max",
                            max_v,
                            unit,
                            variant_quals,
                        ),
                    )
                else:
                    range_keys.add((max_v, max_v))
                    emit(
                        evidence=evidence,
                        excerpt=excerpt,
                        quals=quals,
                        item=_Emit(
                            "supply_voltage_max",
                            max_v,
                            unit,
                            variant_quals,
                        ),
                    )

            if kind == "recommended_operating" and len(range_keys) > 1:
                device_summary = []
                for excerpt, min_v, max_v, _unit, devices in rows:
                    if min_v == min_v:
                        device_summary.append(
                            f"{','.join(devices)}: {min_v}–{max_v} V"
                        )
                add_unresolved(
                    reason=(
                        "Multiple variant-specific recommended_operating supply "
                        "ranges are stated; variant not selected — not choosing a "
                        "single range. "
                        + "; ".join(device_summary)
                    ),
                    reason_key="multi_variant_recommended_supply",
                    candidate="; ".join(device_summary)[:500],
                    evidence=evidence,
                    attempted="supply_voltage_max",
                )

    for evidence in raw_evidence:
        text = evidence.text
        if not text.strip():
            continue

        emit_rated_tables(evidence)

        for umatch in _UNITLESS_CANDIDATE.finditer(text):
            # Skip unitless hits inside rated supply tables we already parsed.
            if any(
                p == evidence.page_number and s <= umatch.start() < e
                for p, s, e in covered_spans
            ):
                continue
            add_unresolved(
                reason=(
                    "Electrical label with numeric value but no explicit volt unit; "
                    "not normalized."
                ),
                reason_key="unitless",
                candidate=umatch.group(0).strip(),
                evidence=evidence,
                attempted=None,
            )

        for pattern in _PATTERNS:
            for match in pattern.regex.finditer(text):
                if any(
                    p == evidence.page_number and s <= match.start() < e
                    for p, s, e in covered_spans
                ):
                    continue
                excerpt = match.group(0).strip()
                quals = _qualifiers_near(text, match.start())
                if pattern.name == "supply_bare" and _is_characterization_supply(
                    text, match, quals
                ):
                    add_unresolved(
                        reason=(
                            "Supply rail value appears as a figure/test-condition "
                            "or lacks Absolute Maximum / Recommended Operating "
                            "section context; not treated as a rated supply limit."
                        ),
                        reason_key="characterization_or_unscoped_rail",
                        candidate=excerpt,
                        evidence=evidence,
                        attempted=pattern.attempted_fact_type,
                    )
                    continue
                emits = pattern.handler(match)
                if emits is None:
                    if pattern.inverted_range_unresolved:
                        add_unresolved(
                            reason=(
                                "Input voltage range low > high; "
                                "not normalized without guessing."
                            ),
                            reason_key="inverted_range",
                            candidate=excerpt,
                            evidence=evidence,
                            attempted=pattern.attempted_fact_type,
                        )
                    continue
                for item in emits:
                    emit(
                        evidence=evidence,
                        excerpt=excerpt,
                        quals=quals,
                        item=item,
                    )

    return facts, unresolved
