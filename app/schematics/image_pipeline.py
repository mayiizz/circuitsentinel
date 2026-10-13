"""Prepare an image-analysis pipeline without claiming electrical connectivity."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from PIL import Image, UnidentifiedImageError


class ImageInspectError(ValueError):
    """Raised when image bytes cannot be opened."""


VISUAL_DISCLAIMER = (
    "Visual metadata only; does not establish electrical connectivity."
)


def inspect_image(data: bytes) -> dict[str, Any]:
    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            width, height = image.size
            fmt = image.format or "unknown"
            mode = image.mode
    except UnidentifiedImageError as exc:
        raise ImageInspectError("File is not a recognized image.") from exc
    except Exception as exc:
        raise ImageInspectError(f"Unable to open image: {exc}") from exc

    observations = [
        f"Image format: {fmt}",
        f"Dimensions: {width}x{height} pixels",
        f"Color mode: {mode}",
        "Image analysis pipeline prepared; OCR and vision models are not run in this milestone.",
        "No electrical connectivity is inferred from pixels.",
    ]
    return {
        "observations": observations,
        "width": width,
        "height": height,
        "image_format": fmt,
    }
