"""Datasheet PDF ingestion, normalization, and explicit component linking."""

from app.datasheets.checks import (
    CHECK_ID,
    PHASE4B_LIMITATIONS,
    EngineeringCheckFinding,
    EngineeringCheckRequest,
    EngineeringCheckResponse,
    StatedSupplyVoltage,
    run_recommended_supply_check,
)
from app.datasheets.ingest import PHASE3A_LIMITATIONS, ingest_datasheet_pdf
from app.datasheets.link import PHASE4A_LIMITATIONS, create_datasheet_component_link
from app.datasheets.models import (
    DatasheetComponentLink,
    DatasheetComponentLinkRequest,
    DatasheetComponentLinkResponse,
    DatasheetIngestReport,
    DatasheetPageText,
    DatasheetSource,
    FactType,
    NormalizedClaim,
    NormalizedDatasheetFact,
    RawDatasheetEvidence,
    UnresolvedNormalization,
)
from app.datasheets.normalize import (
    PHASE3B_LIMITATIONS,
    SUPPORTED_FACT_TYPES,
    normalize_raw_evidence,
)

__all__ = [
    "CHECK_ID",
    "PHASE3A_LIMITATIONS",
    "PHASE3B_LIMITATIONS",
    "PHASE4A_LIMITATIONS",
    "PHASE4B_LIMITATIONS",
    "SUPPORTED_FACT_TYPES",
    "DatasheetComponentLink",
    "DatasheetComponentLinkRequest",
    "DatasheetComponentLinkResponse",
    "DatasheetIngestReport",
    "DatasheetPageText",
    "DatasheetSource",
    "EngineeringCheckFinding",
    "EngineeringCheckRequest",
    "EngineeringCheckResponse",
    "FactType",
    "NormalizedClaim",
    "NormalizedDatasheetFact",
    "RawDatasheetEvidence",
    "StatedSupplyVoltage",
    "UnresolvedNormalization",
    "create_datasheet_component_link",
    "ingest_datasheet_pdf",
    "normalize_raw_evidence",
    "run_recommended_supply_check",
]
