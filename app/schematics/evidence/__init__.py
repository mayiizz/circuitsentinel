"""Circuit Evidence Graph (Phase 1: symbols + ERC; Phase 2: KiCad netlist)."""

from app.schematics.evidence.models import (
    Citation,
    EvidenceEdge,
    EvidenceGraph,
    EvidenceNode,
)

__all__ = [
    "Citation",
    "EvidenceEdge",
    "EvidenceGraph",
    "EvidenceNode",
    "build_evidence_graph",
]


def __getattr__(name: str):
    # Lazy export avoids import cycles with app.schematics.models.
    if name == "build_evidence_graph":
        from app.schematics.evidence.build import build_evidence_graph

        return build_evidence_graph
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
