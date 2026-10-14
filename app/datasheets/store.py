"""Persist datasheet ingest reports and user-confirmed component links.

Reports are keyed by content SHA-256. Links are keyed by a stable composite id.
Never invents associations — only stores what callers explicitly confirm.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.datasheets.models import DatasheetComponentLink, DatasheetIngestReport
from app.schematics.config import ensure_upload_dir

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_SAFE_LINK_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")


def datasheets_dir() -> Path:
    path = ensure_upload_dir() / "datasheets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def links_dir() -> Path:
    path = ensure_upload_dir() / "datasheet_links"
    path.mkdir(parents=True, exist_ok=True)
    return path


def store_ingest_report(report: DatasheetIngestReport) -> Path | None:
    """Persist a successful ingest report. Returns path or None if not storable."""
    if report.status not in {"ok", "partial"}:
        return None
    if report.source is None or not _SHA256_RE.fullmatch(report.source.content_sha256):
        return None
    path = datasheets_dir() / f"{report.source.content_sha256}.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_ingest_report(content_sha256: str) -> DatasheetIngestReport | None:
    if not _SHA256_RE.fullmatch((content_sha256 or "").strip().lower()):
        return None
    path = datasheets_dir() / f"{content_sha256.lower()}.json"
    if not path.is_file():
        return None
    try:
        return DatasheetIngestReport.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def make_link_id(
    *,
    schematic_file_id: str,
    component_reference: str,
    content_sha256: str,
) -> str:
    ref = _SAFE_LINK_ID_RE.sub("-", component_reference.strip())
    return f"{schematic_file_id}:{ref}:{content_sha256[:16]}"


def link_path(link_id: str) -> Path:
    safe = _SAFE_LINK_ID_RE.sub("-", link_id)
    return links_dir() / f"{safe}.json"


def load_link(link_id: str) -> DatasheetComponentLink | None:
    path = link_path(link_id)
    if not path.is_file():
        return None
    try:
        return DatasheetComponentLink.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def store_link(link: DatasheetComponentLink) -> Path:
    path = link_path(link.id)
    path.write_text(link.model_dump_json(indent=2), encoding="utf-8")
    return path


def list_links_for_schematic(schematic_file_id: str) -> list[DatasheetComponentLink]:
    """Load all persisted links whose id starts with the given 32-hex file id."""
    fid = (schematic_file_id or "").strip().lower()
    if not re.fullmatch(r"^[a-f0-9]{32}$", fid):
        return []
    prefix = f"{fid}:"
    results: list[DatasheetComponentLink] = []
    for path in links_dir().glob("*.json"):
        try:
            link = DatasheetComponentLink.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if link.schematic_file_id.lower() == fid or link.id.startswith(prefix):
            results.append(link)
    return results
