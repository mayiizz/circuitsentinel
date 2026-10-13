"""Shared KiCad CLI discovery. Never invents ERC or render results."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# Common macOS application bundle location when not on PATH.
_MACOS_KICAD_CLI = Path(
    "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
)


def find_kicad_cli() -> str | None:
    """Return an absolute path to kicad-cli, or None if not installed.

    Resolution order:
    1. ``CIRCUITSENTINEL_KICAD_CLI`` (explicit executable path)
    2. ``PATH`` lookup for ``kicad-cli``
    3. Standard macOS KiCad.app bundle location
    """
    configured = os.environ.get("CIRCUITSENTINEL_KICAD_CLI", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
        return None

    which = shutil.which("kicad-cli")
    if which:
        return which
    if _MACOS_KICAD_CLI.is_file():
        return str(_MACOS_KICAD_CLI)
    return None


def probe_kicad_cli_erc() -> bool:
    """True when kicad-cli responds to `sch erc --help`."""
    path = find_kicad_cli()
    if not path:
        return False
    try:
        completed = subprocess.run(
            [path, "sch", "erc", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    combined = (completed.stdout + completed.stderr).lower()
    return completed.returncode == 0 or "erc" in combined


def probe_kicad_cli_export_svg() -> bool:
    """True when kicad-cli appears to support schematic SVG export."""
    path = find_kicad_cli()
    if not path:
        return False
    try:
        completed = subprocess.run(
            [path, "sch", "export", "svg", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    combined = (completed.stdout + completed.stderr).lower()
    return completed.returncode == 0 or "svg" in combined


def probe_kicad_cli_export_netlist() -> bool:
    """True when kicad-cli appears to support schematic netlist export."""
    path = find_kicad_cli()
    if not path:
        return False
    try:
        completed = subprocess.run(
            [path, "sch", "export", "netlist", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    combined = (completed.stdout + completed.stderr).lower()
    return completed.returncode == 0 or "netlist" in combined
