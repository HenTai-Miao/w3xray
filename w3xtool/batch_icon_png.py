"""Convert Warcraft icon payloads into disposable PNG previews."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import struct

from PIL import Image

from .blp import decode_blp


@dataclass(frozen=True, slots=True)
class PngConversion:
    payload: bytes | None
    error: str = ""


def convert_icon_to_png(payload: bytes) -> PngConversion:
    """Decode one BLP payload and retain a stable diagnostic on failure."""
    try:
        image: Image.Image | None = decode_blp(payload)
    except (OSError, ValueError, struct.error) as exc:
        return PngConversion(None, f"{type(exc).__name__}: {exc}")
    if image is None:
        return PngConversion(None, "BLP decode failed")
    try:
        output = BytesIO()
        image.save(output, format="PNG")
        return PngConversion(output.getvalue())
    except (OSError, ValueError) as exc:
        return PngConversion(None, f"{type(exc).__name__}: {exc}")
    finally:
        image.close()
