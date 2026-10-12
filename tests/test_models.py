"""Tests for sandbox component and symbol-proposal models."""

import pytest
from pydantic import ValidationError

from app.models import Component, SymbolProposal


def test_component_accepts_required_fields() -> None:
    component = Component(reference="R1", value="10k")

    assert component.reference == "R1"
    assert component.value == "10k"
    assert component.footprint is None
    assert component.description is None


def test_component_round_trip() -> None:
    component = Component(
        reference="C1",
        value="100nF",
        footprint="0402",
        description="Decoupling capacitor",
    )

    restored = Component.model_validate(component.model_dump())

    assert restored == component


def test_component_rejects_blank_reference() -> None:
    with pytest.raises(ValidationError):
        Component(reference="", value="10k")


def test_symbol_proposal_defaults_to_no_pins() -> None:
    proposal = SymbolProposal(library="Device", name="R")

    assert proposal.pins == []
    assert proposal.rationale is None


def test_symbol_proposal_round_trip() -> None:
    proposal = SymbolProposal(
        library="Device",
        name="R",
        pins=["1", "2"],
        rationale="Generic resistor symbol",
    )

    restored = SymbolProposal.model_validate(proposal.model_dump())

    assert restored == proposal


def test_symbol_proposal_rejects_blank_name() -> None:
    with pytest.raises(ValidationError):
        SymbolProposal(library="Device", name="")
