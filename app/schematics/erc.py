"""Run KiCad ERC on a temporary schematic copy and parse structured findings.

Never invents violations. Never modifies the original uploaded file.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from app.schematics.kicad_cli import find_kicad_cli, probe_kicad_cli_erc
from app.schematics.models import ErcFinding, ErcReport

HOW_TO_ENABLE = (
    "Install KiCad and ensure `kicad-cli` is on PATH "
    "(verify with `kicad-cli sch erc --help`), or set CIRCUITSENTINEL_KICAD_CLI "
    "to the executable. CircuitSentinel will not invent ERC faults."
)

_ITEM_RE = re.compile(
    r"Symbol\s+(?P<reference>\S+)"
    r"(?:\s+Pin\s+(?P<pin>\S+))?",
    re.IGNORECASE,
)
_REPORT_BLOCK_RE = re.compile(
    r"\[(?P<rule_id>[^\]]+)\]:\s*(?P<description>.+?)\n"
    r"\s*;\s*(?P<severity>\w+)\s*\n"
    r"\s*@\((?P<x>[-\d.]+)\s*mm,\s*(?P<y>[-\d.]+)\s*mm\):\s*(?P<item>.+)",
    re.MULTILINE,
)
_REPORT_COUNTS_RE = re.compile(
    r"ERC messages:\s*(?P<messages>\d+)\s+Errors\s+(?P<errors>\d+)\s+Warnings\s+(?P<warnings>\d+)",
    re.IGNORECASE,
)


def probe_kicad_cli() -> bool:
    """Return True when kicad-cli appears available for ERC."""
    return probe_kicad_cli_erc()


def build_erc_report(*, schematic_path: str | Path | None = None) -> ErcReport:
    """Run ERC when possible and return structured KiCad findings."""
    cli = find_kicad_cli()
    available = bool(cli) and probe_kicad_cli_erc()

    if schematic_path is None:
        return ErcReport(
            ran=False,
            available=available,
            findings=[],
            how_to_enable=HOW_TO_ENABLE,
            failure_reason=(
                None
                if available
                else "KiCad CLI is not available; ERC was not executed."
            ),
        )

    path = Path(schematic_path)
    if path.suffix.lower() != ".kicad_sch":
        return ErcReport(
            ran=False,
            available=False,
            findings=[],
            how_to_enable=HOW_TO_ENABLE,
            failure_reason="ERC applies only to KiCad schematic (.kicad_sch) files.",
        )

    if not available or cli is None:
        return ErcReport(
            ran=False,
            available=False,
            findings=[],
            how_to_enable=HOW_TO_ENABLE,
            failure_reason="KiCad CLI is not available; ERC was not executed.",
        )

    if not path.is_file():
        return ErcReport(
            ran=False,
            available=True,
            findings=[],
            how_to_enable=HOW_TO_ENABLE,
            failure_reason=f"Schematic file not found for ERC: {path.name}",
        )

    try:
        return _run_erc_on_copy(cli=cli, schematic_path=path)
    except Exception as exc:  # noqa: BLE001 — surface as honest failure
        return ErcReport(
            ran=False,
            available=True,
            findings=[],
            how_to_enable=HOW_TO_ENABLE,
            failure_reason=f"ERC execution failed: {type(exc).__name__}: {exc}",
        )


def _run_erc_on_copy(*, cli: str, schematic_path: Path) -> ErcReport:
    """Copy the schematic to a temp dir, run ERC, parse JSON, delete temps."""
    work = Path(tempfile.mkdtemp(prefix="circuitsentinel-erc-"))
    try:
        copy_name = f"{uuid.uuid4().hex}.kicad_sch"
        copy_path = work / copy_name
        report_path = work / f"{uuid.uuid4().hex}-erc.json"
        shutil.copy2(schematic_path, copy_path)

        completed = subprocess.run(
            [
                cli,
                "sch",
                "erc",
                "--format",
                "json",
                "--units",
                "mm",
                "--severity-all",
                "--output",
                str(report_path),
                str(copy_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

        if not report_path.is_file():
            detail = (completed.stderr or completed.stdout or "").strip()
            return ErcReport(
                ran=False,
                available=True,
                findings=[],
                how_to_enable=HOW_TO_ENABLE,
                failure_reason=(
                    "KiCad CLI did not write an ERC report"
                    + (f": {detail[:400]}" if detail else ".")
                ),
            )

        raw = report_path.read_text(encoding="utf-8")
        findings, meta = parse_erc_json(raw)
        error_count = sum(1 for f in findings if f.severity.lower() == "error")
        warning_count = sum(1 for f in findings if f.severity.lower() == "warning")
        return ErcReport(
            ran=True,
            available=True,
            findings=findings,
            error_count=error_count,
            warning_count=warning_count,
            message_count=len(findings),
            how_to_enable=HOW_TO_ENABLE,
            failure_reason=None,
            kicad_version=meta.get("kicad_version"),
            units=meta.get("coordinate_units") or "mm",
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)


def parse_erc_json(raw: str) -> tuple[list[ErcFinding], dict[str, Any]]:
    """Parse KiCad ERC JSON (schema erc.v1) into structured findings."""
    data = json.loads(raw)
    findings: list[ErcFinding] = []
    for sheet in data.get("sheets") or []:
        for violation in sheet.get("violations") or []:
            rule_id = str(violation.get("type") or "unknown")
            severity = str(violation.get("severity") or "unknown")
            description = str(violation.get("description") or "")
            items = violation.get("items") or []
            if not items:
                findings.append(
                    ErcFinding(
                        rule_id=rule_id,
                        severity=severity,
                        description=description,
                    )
                )
                continue
            for item in items:
                item_desc = str(item.get("description") or "")
                reference, pin = _parse_item_symbols(item_desc)
                pos = item.get("pos") or {}
                x_mm = _as_float(pos.get("x"))
                y_mm = _as_float(pos.get("y"))
                findings.append(
                    ErcFinding(
                        rule_id=rule_id,
                        severity=severity,
                        description=description,
                        reference=reference,
                        pin=pin,
                        x_mm=x_mm,
                        y_mm=y_mm,
                        item_description=item_desc or None,
                    )
                )
    meta = {
        "kicad_version": data.get("kicad_version"),
        "coordinate_units": data.get("coordinate_units"),
    }
    return findings, meta


def parse_erc_report_text(raw: str) -> tuple[list[ErcFinding], dict[str, int]]:
    """Parse classic KiCad text ERC reports (fallback / tests)."""
    findings: list[ErcFinding] = []
    for match in _REPORT_BLOCK_RE.finditer(raw):
        item = match.group("item").strip()
        reference, pin = _parse_item_symbols(item)
        findings.append(
            ErcFinding(
                rule_id=match.group("rule_id").strip(),
                severity=match.group("severity").strip(),
                description=match.group("description").strip(),
                reference=reference,
                pin=pin,
                x_mm=_as_float(match.group("x")),
                y_mm=_as_float(match.group("y")),
                item_description=item,
            )
        )
    counts = {"messages": len(findings), "errors": 0, "warnings": 0}
    count_match = _REPORT_COUNTS_RE.search(raw)
    if count_match:
        counts = {
            "messages": int(count_match.group("messages")),
            "errors": int(count_match.group("errors")),
            "warnings": int(count_match.group("warnings")),
        }
    else:
        counts["errors"] = sum(1 for f in findings if f.severity.lower() == "error")
        counts["warnings"] = sum(1 for f in findings if f.severity.lower() == "warning")
    return findings, counts


def _parse_item_symbols(item_description: str) -> tuple[str | None, str | None]:
    match = _ITEM_RE.search(item_description)
    if not match:
        return None, None
    reference = match.group("reference")
    pin = match.group("pin")
    if pin is not None:
        pin = pin.rstrip(",")
    return reference, pin


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def erc_status_dict() -> dict[str, Any]:
    report = build_erc_report()
    return report.model_dump()
