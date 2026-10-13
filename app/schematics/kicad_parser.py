"""Parse KiCad schematic S-expressions into confirmed structural findings.

Placed symbol instances (top-level children of kicad_sch with lib_id) are
collected separately from library definitions inside lib_symbols.
"""

from __future__ import annotations

from typing import Any

import sexpdata

from app.schematics.models import (
    ConnectivityHint,
    HierarchyNode,
    LabelFinding,
    SymbolFinding,
)


class KiCadParseError(ValueError):
    """Raised when a file is not a parseable KiCad schematic."""


def _atom_name(node: Any) -> str | None:
    if isinstance(node, sexpdata.Symbol):
        return str(node)
    if isinstance(node, str):
        return node
    return None


def _is_form(node: Any) -> bool:
    return isinstance(node, list) and len(node) > 0


def _form_head(node: list[Any]) -> str | None:
    return _atom_name(node[0])


def _as_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, sexpdata.Symbol):
        return str(value)
    return str(value)


def _property_map(symbol_form: list[Any]) -> dict[str, str]:
    props: dict[str, str] = {}
    for child in symbol_form[1:]:
        if not _is_form(child) or _form_head(child) != "property":
            continue
        if len(child) < 3:
            continue
        key = _as_str(child[1])
        value = _as_str(child[2])
        props[key] = value
    return props


def _child_value(symbol_form: list[Any], name: str) -> Any | None:
    for child in symbol_form[1:]:
        if _is_form(child) and _form_head(child) == name and len(child) >= 2:
            return child[1]
    return None


def _lib_id(symbol_form: list[Any]) -> str | None:
    value = _child_value(symbol_form, "lib_id")
    if value is None:
        return None
    return _as_str(value)


def _unit(symbol_form: list[Any]) -> int | None:
    value = _child_value(symbol_form, "unit")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _uuid(symbol_form: list[Any]) -> str | None:
    value = _child_value(symbol_form, "uuid")
    if value is None:
        return None
    return _as_str(value)


def _at_position(symbol_form: list[Any]) -> tuple[float | None, float | None, float | None]:
    """Parse (at x y [angle]) from a placed symbol. Never invents coordinates."""
    for child in symbol_form[1:]:
        if not _is_form(child) or _form_head(child) != "at" or len(child) < 3:
            continue
        try:
            x = float(child[1])
            y = float(child[2])
        except (TypeError, ValueError):
            return (None, None, None)
        angle: float | None = None
        if len(child) >= 4:
            try:
                angle = float(child[3])
            except (TypeError, ValueError):
                angle = None
        return (x, y, angle)
    return (None, None, None)


def _label_text(form: list[Any]) -> str | None:
    if len(form) < 2:
        return None
    return _as_str(form[1])


def _parse_placed_symbol(node: list[Any]) -> SymbolFinding | None:
    """Return a placed instance when the form has lib_id; otherwise None."""
    lib = _lib_id(node)
    if not lib:
        return None
    props = _property_map(node)
    at_x, at_y, at_angle = _at_position(node)
    return SymbolFinding(
        reference=props.get("Reference"),
        value=props.get("Value"),
        lib_id=lib,
        unit=_unit(node),
        uuid=_uuid(node),
        properties=props,
        at_x=at_x,
        at_y=at_y,
        at_angle=at_angle,
    )


def _walk_structure(
    node: Any,
    *,
    labels: list[LabelFinding],
    connectivity: list[ConnectivityHint],
    hierarchy: list[HierarchyNode],
) -> None:
    """Collect labels, wires, junctions, and sheets. Skips lib_symbols entirely."""
    if not _is_form(node):
        return
    head = _form_head(node)
    if head == "lib_symbols":
        return
    if head in {"label", "global_label", "hierarchical_label"}:
        text = _label_text(node)
        if text:
            labels.append(LabelFinding(kind=head, text=text))
    elif head == "wire":
        connectivity.append(
            ConnectivityHint(kind="wire", detail="Wire segment present in schematic.")
        )
    elif head == "junction":
        connectivity.append(
            ConnectivityHint(kind="junction", detail="Junction present in schematic.")
        )
    elif head == "sheet":
        props = _property_map(node)
        hierarchy.append(
            HierarchyNode(
                name=props.get("Sheetname") or props.get("Sheet name") or "sheet",
                file=props.get("Sheetfile") or props.get("Sheet file"),
                detail="Hierarchical sheet instance",
            )
        )
    elif head == "sheet_instances":
        hierarchy.append(
            HierarchyNode(name="sheet_instances", detail="Sheet instance block present")
        )

    for child in node[1:]:
        _walk_structure(
            child,
            labels=labels,
            connectivity=connectivity,
            hierarchy=hierarchy,
        )


def looks_like_kicad_sch(data: bytes) -> bool:
    try:
        text = data.decode("utf-8", errors="replace").lstrip()
    except Exception:
        return False
    return text.startswith("(kicad_sch")


def parse_kicad_sch(data: bytes) -> dict[str, Any]:
    """Return confirmed findings dict or raise KiCadParseError."""
    if not looks_like_kicad_sch(data):
        raise KiCadParseError(
            "File does not start with (kicad_sch). Not a KiCad schematic S-expression."
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise KiCadParseError("KiCad schematic is not valid UTF-8.") from exc

    try:
        tree = sexpdata.loads(text)
    except Exception as exc:
        raise KiCadParseError(f"Malformed KiCad S-expression: {exc}") from exc

    if not _is_form(tree) or _form_head(tree) != "kicad_sch":
        raise KiCadParseError("Root form must be (kicad_sch ...).")

    symbols: list[SymbolFinding] = []
    labels: list[LabelFinding] = []
    connectivity: list[ConnectivityHint] = []
    hierarchy: list[HierarchyNode] = []

    # Placed instances are direct children of kicad_sch with a lib_id.
    # Library definitions live under lib_symbols and must not be counted.
    for child in tree[1:]:
        if not _is_form(child):
            continue
        head = _form_head(child)
        if head == "lib_symbols":
            continue
        if head == "symbol":
            placed = _parse_placed_symbol(child)
            if placed is not None:
                symbols.append(placed)
            continue
        _walk_structure(
            child,
            labels=labels,
            connectivity=connectivity,
            hierarchy=hierarchy,
        )

    wire_count = sum(1 for item in connectivity if item.kind == "wire")
    junction_count = sum(1 for item in connectivity if item.kind == "junction")
    summarized: list[ConnectivityHint] = []
    if wire_count:
        summarized.append(
            ConnectivityHint(
                kind="wire",
                detail=(
                    f"{wire_count} wire segment(s) found "
                    "(structural hint only; not an ERC result)."
                ),
            )
        )
    if junction_count:
        summarized.append(
            ConnectivityHint(
                kind="junction",
                detail=(
                    f"{junction_count} junction(s) found "
                    "(structural hint only; not an ERC result)."
                ),
            )
        )

    return {
        "symbols": symbols,
        "labels": labels,
        "connectivity": summarized,
        "hierarchy": hierarchy,
    }
