"""Schematic preview generation via KiCad CLI. Never draws a fake circuit diagram."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from app.schematics.kicad_cli import find_kicad_cli, probe_kicad_cli_export_svg
from app.schematics.models import CoordinateMapping, ViewerInfo
from app.schematics.storage import (
    content_type_for_path,
    ensure_preview_dir,
    file_id_from_path,
    resolve_preview_path,
)
from app.schematics.svg_coords import (
    parse_svg_coordinate_mapping,
    unavailable_mapping,
)

KICAD_UNAVAILABLE_MSG = (
    "KiCad CLI is not installed or does not support schematic SVG export. "
    "Install KiCad and ensure `kicad-cli sch export svg --help` works "
    "(or set CIRCUITSENTINEL_KICAD_CLI), then re-analyze. "
    "CircuitSentinel will not invent a schematic drawing."
)


def build_viewer_info(
    *,
    stored_path: Path,
    format_name: str,
    page_count: int | None = None,
) -> ViewerInfo:
    """Describe how the frontend should display this upload."""
    file_id = file_id_from_path(stored_path)
    source_url = f"/api/schematics/files/{file_id}"
    content_type = content_type_for_path(stored_path)

    if format_name == "image":
        return ViewerInfo(
            file_id=file_id,
            format="image",
            source_url=source_url,
            preview_url=source_url,
            render_status="ready",
            render_message="Original image ready for display.",
            page_count=1,
            content_type=content_type,
            coordinate_mapping=CoordinateMapping(
                reliable=False,
                note="Image uploads have no schematic millimetre coordinate system.",
            ),
        )

    if format_name == "pdf":
        return ViewerInfo(
            file_id=file_id,
            format="pdf",
            source_url=source_url,
            preview_url=source_url,
            render_status="ready",
            render_message="Original PDF ready for browser embedding.",
            page_count=page_count,
            content_type=content_type,
            coordinate_mapping=CoordinateMapping(
                reliable=False,
                note="PDF embeds do not expose a reliable schematic millimetre map.",
            ),
        )

    preview, mapping, error = export_kicad_svg_preview(stored_path, file_id)
    if preview is not None:
        return ViewerInfo(
            file_id=file_id,
            format="kicad_sch",
            source_url=source_url,
            preview_url=f"/api/schematics/files/{file_id}/preview",
            render_status="ready",
            render_message="Schematic SVG exported with kicad-cli (original file unchanged).",
            page_count=1,
            content_type=content_type,
            coordinate_mapping=CoordinateMapping(**mapping.to_dict()),
        )

    cli = find_kicad_cli()
    if cli is None:
        message = KICAD_UNAVAILABLE_MSG
        status = "unavailable"
    elif not probe_kicad_cli_export_svg():
        message = (
            "kicad-cli was found but schematic SVG export is not available. "
            + KICAD_UNAVAILABLE_MSG
        )
        status = "unavailable"
    else:
        message = error or (
            "kicad-cli SVG export failed for this schematic. "
            "The source file is unchanged; no substitute diagram was generated."
        )
        status = "error"

    return ViewerInfo(
        file_id=file_id,
        format="kicad_sch",
        source_url=source_url,
        preview_url=None,
        render_status=status,  # type: ignore[arg-type]
        render_message=message,
        page_count=None,
        content_type=content_type,
        coordinate_mapping=CoordinateMapping(
            reliable=False,
            note="No SVG preview is available, so finding highlights are disabled.",
        ),
    )


def export_kicad_svg_preview(
    stored_path: Path,
    file_id: str,
) -> tuple[Path | None, object, str | None]:
    """Export SVG using a temporary copy. Never modifies ``stored_path``.

    Returns ``(preview_path_or_none, SvgCoordinateMapping, error_message_or_none)``.
    Temporary working directories are always removed.
    """
    existing = resolve_preview_path(file_id)
    if existing is not None:
        mapping = parse_svg_coordinate_mapping(existing.read_text(encoding="utf-8", errors="replace"))
        return existing, mapping, None

    cli = find_kicad_cli()
    if cli is None or not probe_kicad_cli_export_svg():
        return None, unavailable_mapping(KICAD_UNAVAILABLE_MSG), KICAD_UNAVAILABLE_MSG

    work = Path(tempfile.mkdtemp(prefix="circuitsentinel-svg-"))
    try:
        copy_path = work / f"{uuid.uuid4().hex}.kicad_sch"
        out_dir = work / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(stored_path, copy_path)

        completed = subprocess.run(
            [
                cli,
                "sch",
                "export",
                "svg",
                "--exclude-drawing-sheet",
                "--output",
                str(out_dir),
                str(copy_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            message = "kicad-cli SVG export failed."
            if detail:
                message = f"{message} {detail[:300]}"
            return None, unavailable_mapping(message), message

        produced = sorted(out_dir.glob("*.svg"))
        if not produced:
            message = "kicad-cli reported success but produced no SVG file."
            return None, unavailable_mapping(message), message

        svg_src = produced[0]
        preview_dir = ensure_preview_dir()
        dest = preview_dir / f"{file_id}.svg"
        shutil.copy2(svg_src, dest)
        mapping = parse_svg_coordinate_mapping(
            dest.read_text(encoding="utf-8", errors="replace")
        )
        return dest, mapping, None
    except (OSError, subprocess.TimeoutExpired) as exc:
        message = f"SVG export interrupted: {type(exc).__name__}: {exc}"
        return None, unavailable_mapping(message), message
    finally:
        shutil.rmtree(work, ignore_errors=True)


# Backwards-compatible name used by older tests.
def _try_export_kicad_svg(stored_path: Path, file_id: str) -> Path | None:
    path, _mapping, _error = export_kicad_svg_preview(stored_path, file_id)
    return path
