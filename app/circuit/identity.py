"""Component identity inventory from schematic + user-confirmed datasheet links."""

from __future__ import annotations

from app.circuit.models import ComponentInventoryItem
from app.circuit.topology import CircuitTopology, nets_for_reference
from app.datasheets.models import DatasheetComponentLink
from app.datasheets.store import list_links_for_schematic
from app.schematics.models import SymbolFinding


def build_component_inventory(
    topology: CircuitTopology,
    *,
    schematic_file_id: str,
    links: list[DatasheetComponentLink] | None = None,
) -> list[ComponentInventoryItem]:
    link_list = links if links is not None else list_links_for_schematic(schematic_file_id)
    by_ref: dict[str, DatasheetComponentLink] = {}
    for link in link_list:
        # Prefer most recently stored; last write wins for same ref.
        by_ref[link.component_reference] = link

    items: list[ComponentInventoryItem] = []
    for ref in topology.references:
        sym: SymbolFinding | None = topology.symbols_by_ref.get(ref)
        link = by_ref.get(ref)
        # Skip pure power symbols from "unresolved IC" pressure — still list them.
        items.append(
            ComponentInventoryItem(
                reference=ref,
                value=sym.value if sym else None,
                lib_id=sym.lib_id if sym else None,
                footprint=(
                    (sym.properties or {}).get("Footprint")
                    if sym and sym.properties
                    else None
                ),
                datasheet_linked=link is not None,
                link_id=link.id if link else None,
                document_id=link.document_id if link else None,
                content_sha256=link.content_sha256 if link else None,
                identity_status="linked" if link else "unresolved",
                connected_nets=nets_for_reference(topology, ref),
            )
        )
    return items
