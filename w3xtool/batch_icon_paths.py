"""Collision-safe output paths for physical batch icon files."""

from __future__ import annotations

import hashlib
import os
from pathlib import PurePosixPath

from .safe_output import safe_destination


def collision_path(root: str, name: str, payload: bytes) -> str:
    """Return a stable hash-suffixed path only for a content collision."""
    digest = hashlib.sha256(payload).hexdigest()
    destination = safe_destination(root, name)
    if destination is None or not os.path.isfile(destination):
        return name
    try:
        if os.path.getsize(destination) == len(payload):
            with open(destination, "rb") as handle:
                if hashlib.sha256(handle.read()).hexdigest() == digest:
                    return name
    except OSError:
        return name
    path = PurePosixPath(name.replace("\\", "/"))
    return str(path.with_name(f"{path.stem}_{digest[:8]}{path.suffix}"))


def icon_path_suffix(path: str) -> str:
    """Return a source icon suffix, defaulting extensionless paths to BLP."""
    leaf = path.replace("\\", "/").rsplit("/", 1)[-1]
    return f".{leaf.rsplit('.', 1)[-1]}" if "." in leaf else ".blp"


def without_leaf_suffix(path: str) -> str:
    """Remove only the final path component's suffix."""
    normalized = path.replace("\\", "/")
    leaf = normalized.rsplit("/", 1)[-1]
    return normalized.rsplit(".", 1)[0] if "." in leaf else normalized
