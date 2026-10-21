"""Archive export path safety helpers."""

from __future__ import annotations

from .safe_output import safe_destination


def _safe_export_path(out_dir: str, name: str) -> str | None:
    """Map an archive path to a safe path under ``out_dir``."""
    return safe_destination(out_dir, name)
