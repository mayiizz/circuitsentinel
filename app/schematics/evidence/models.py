"""Circuit Evidence Graph models — parser/ERC/netlist + user-confirmed datasheet links."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

NodeKind = Literal["component", "pin", "finding", "net", "datasheet_document"]
EdgeKind = Literal[
    "has_pin",
    "mentions_component",
    "mentions_pin",
    "connected_to",
    "user_confirmed_datasheet",
]
Provenance = Literal["parser", "kicad_erc", "kicad_netlist", "user_confirmed"]


class EvidenceNode(BaseModel):
    """One graph entity with explicit provenance. No invented electrical meaning."""

    id: str
    kind: NodeKind
    label: str
    attrs: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance


class EvidenceEdge(BaseModel):
    """Directed link between evidence nodes. Provenance required."""

    id: str
    source_id: str
    target_id: str
    kind: EdgeKind
    provenance: Provenance


class Citation(BaseModel):
    """External source citation. Kept empty until verified source ingestion exists."""

    id: str
    source_type: str
    locator: str
    excerpt: str | None = None


class EvidenceGraph(BaseModel):
    """Read-only graph derived from confirmed parser, ERC, and KiCad netlist facts."""

    nodes: list[EvidenceNode] = Field(default_factory=list)
    edges: list[EvidenceEdge] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
