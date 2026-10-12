"""Structured component and symbol-proposal data for the in-memory sandbox."""

from pydantic import BaseModel, Field


class Component(BaseModel):
    """A schematic part held only in process memory."""

    reference: str = Field(min_length=1, description="Reference designator, such as R1.")
    value: str = Field(min_length=1, description="Part value, such as 10k or 100nF.")
    footprint: str | None = Field(default=None, description="Optional footprint name.")
    description: str | None = None


class SymbolProposal(BaseModel):
    """A proposed schematic symbol. Proposals are not written to a library or board."""

    library: str = Field(min_length=1)
    name: str = Field(min_length=1)
    pins: list[str] = Field(default_factory=list)
    rationale: str | None = None
