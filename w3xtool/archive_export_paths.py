"""Archive export path safety helpers."""

from __future__ import annotations

import os


def _safe_export_path(out_dir: str, name: str) -> str | None:
    """Map an archive path to a safe path under ``out_dir``."""
    out_root = os.path.realpath(out_dir)
    norm = name.replace("\\", "/").strip("/")
    parts = [part for part in norm.split("/") if part and part != "."]
    if not parts:
        return None
    if any(part == ".." for part in parts):
        return None
    if ":" in parts[0]:
        return None
    dest = os.path.realpath(os.path.join(out_root, *parts))
    if out_root != dest and os.path.commonpath([out_root, dest]) != out_root:
        return None
    return dest
