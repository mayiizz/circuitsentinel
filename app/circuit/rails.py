"""Persist operator-confirmed rail maps. Never invents voltages from net names."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.circuit.models import RailEntry, RailMap
from app.circuit.topology import CircuitTopology
from app.schematics.config import ensure_upload_dir

_FILE_ID_RE = re.compile(r"^[a-f0-9]{32}$")


def rail_maps_dir() -> Path:
    path = ensure_upload_dir() / "rail_maps"
    path.mkdir(parents=True, exist_ok=True)
    return path


def rail_map_path(file_id: str) -> Path:
    return rail_maps_dir() / f"{file_id.lower()}.json"


def load_rail_map(file_id: str) -> RailMap | None:
    fid = (file_id or "").strip().lower()
    if not _FILE_ID_RE.fullmatch(fid):
        return None
    path = rail_map_path(fid)
    if not path.is_file():
        return None
    try:
        return RailMap.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def store_rail_map(rail_map: RailMap) -> Path:
    fid = rail_map.schematic_file_id.strip().lower()
    rail_map.schematic_file_id = fid
    path = rail_map_path(fid)
    path.write_text(rail_map.model_dump_json(indent=2), encoding="utf-8")
    return path


def merge_suggested_rails(
    topology: CircuitTopology,
    stored: RailMap | None,
    file_id: str,
) -> RailMap:
    """Combine stored operator rails with topology candidates (no invented volts)."""
    by_name: dict[str, RailEntry] = {}
    if stored:
        for rail in stored.rails:
            by_name[rail.net_name] = rail.model_copy(deep=True)

    for net_name, reason in topology.candidate_supply_nets:
        if net_name in by_name:
            existing = by_name[net_name]
            existing.suggested = True
            existing.suggestion_reason = reason
        else:
            by_name[net_name] = RailEntry(
                net_name=net_name,
                status="unconfirmed",
                source="operator",
                suggested=True,
                suggestion_reason=reason,
            )

    return RailMap(
        schematic_file_id=file_id.strip().lower(),
        rails=sorted(by_name.values(), key=lambda r: r.net_name),
    )


def confirmed_rail_voltage(rails: list[RailEntry], net_name: str) -> float | None:
    for rail in rails:
        if rail.net_name != net_name:
            continue
        if rail.status == "confirmed" and rail.value_v is not None:
            return rail.value_v
        return None
    return None


def rail_is_unknown(rails: list[RailEntry], net_name: str) -> bool:
    for rail in rails:
        if rail.net_name == net_name:
            return rail.status != "confirmed" or rail.value_v is None
    return True
