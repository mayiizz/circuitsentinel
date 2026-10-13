"""Parse KiCad SVG viewBox metadata for honest coordinate mapping.

KiCad Eeschema SVG exports typically use millimetre user units matching
schematic `(at x y)` and ERC positions. We only mark mapping as reliable when
that relationship is explicit in the SVG attributes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_VIEWBOX_RE = re.compile(
    r'viewBox\s*=\s*"\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*"',
    re.IGNORECASE,
)
_WIDTH_MM_RE = re.compile(
    r'\bwidth\s*=\s*"\s*([-\d.]+)\s*mm\s*"',
    re.IGNORECASE,
)
_HEIGHT_MM_RE = re.compile(
    r'\bheight\s*=\s*"\s*([-\d.]+)\s*mm\s*"',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SvgCoordinateMapping:
    reliable: bool
    units: str | None
    view_min_x: float | None
    view_min_y: float | None
    view_width: float | None
    view_height: float | None
    note: str

    def to_dict(self) -> dict:
        return {
            "reliable": self.reliable,
            "units": self.units,
            "view_min_x": self.view_min_x,
            "view_min_y": self.view_min_y,
            "view_width": self.view_width,
            "view_height": self.view_height,
            "note": self.note,
        }


def unavailable_mapping(note: str) -> SvgCoordinateMapping:
    return SvgCoordinateMapping(
        reliable=False,
        units=None,
        view_min_x=None,
        view_min_y=None,
        view_width=None,
        view_height=None,
        note=note,
    )


def parse_svg_coordinate_mapping(svg_text: str) -> SvgCoordinateMapping:
    """Return mapping metadata. Never invents a transform when units are unclear."""
    vb = _VIEWBOX_RE.search(svg_text)
    if not vb:
        return unavailable_mapping(
            "SVG has no viewBox; schematic millimetre coordinates cannot be mapped reliably."
        )

    min_x, min_y, width, height = (float(vb.group(i)) for i in range(1, 5))
    if width <= 0 or height <= 0:
        return unavailable_mapping("SVG viewBox has non-positive size; mapping refused.")

    width_mm = _WIDTH_MM_RE.search(svg_text)
    height_mm = _HEIGHT_MM_RE.search(svg_text)
    if not width_mm or not height_mm:
        return SvgCoordinateMapping(
            reliable=False,
            units=None,
            view_min_x=min_x,
            view_min_y=min_y,
            view_width=width,
            view_height=height,
            note=(
                "SVG viewBox is present but width/height are not in millimetres; "
                "highlight markers are disabled to avoid inventing pin locations."
            ),
        )

    attr_w = float(width_mm.group(1))
    attr_h = float(height_mm.group(1))
    # Allow tiny float noise between mm attributes and viewBox extents.
    if abs(attr_w - width) > 0.05 or abs(attr_h - height) > 0.05:
        return SvgCoordinateMapping(
            reliable=False,
            units="mm",
            view_min_x=min_x,
            view_min_y=min_y,
            view_width=width,
            view_height=height,
            note=(
                "SVG millimetre size does not match viewBox extents; "
                "highlight markers are disabled."
            ),
        )

    return SvgCoordinateMapping(
        reliable=True,
        units="mm",
        view_min_x=min_x,
        view_min_y=min_y,
        view_width=width,
        view_height=height,
        note=(
            "KiCad SVG user units match millimetres (viewBox == width/height mm). "
            "ERC and symbol coordinates in mm can be mapped onto the preview."
        ),
    )


def mm_to_view_percent(
    x_mm: float,
    y_mm: float,
    mapping: SvgCoordinateMapping,
) -> tuple[float, float] | None:
    """Map schematic mm into percentage of the SVG content box, or None if unreliable."""
    if (
        not mapping.reliable
        or mapping.view_min_x is None
        or mapping.view_min_y is None
        or mapping.view_width is None
        or mapping.view_height is None
        or mapping.view_width == 0
        or mapping.view_height == 0
    ):
        return None
    left = (x_mm - mapping.view_min_x) / mapping.view_width * 100.0
    top = (y_mm - mapping.view_min_y) / mapping.view_height * 100.0
    return (left, top)
