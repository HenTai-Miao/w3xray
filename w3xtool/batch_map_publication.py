"""Owned staging directories and atomic per-map directory publication."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import override
from uuid import uuid4

from .safe_output import safe_destination


@dataclass(frozen=True, slots=True)
class BatchMapPublicationError(OSError):
    detail: str

    @override
    def __str__(self) -> str:
        return self.detail


def map_output_relative(index: int, display_name: str, digest: str) -> str:
    """Build a bounded human-readable, content-addressed output directory."""
    cleaned = "".join(
        character if character.isalnum() or character in " ._-" else "_"
        for character in display_name
    ).strip(" ._")
    name = (cleaned or "未命名地图")[:64].rstrip(" ._")
    return f"地图/{index:03d}_{name}_{digest[:8]}"


def create_map_stage(output_root: str) -> Path:
    """Create one private stage below the owned map-output directory."""
    maps_root = Path(output_root, "地图")
    if maps_root.is_symlink():
        raise BatchMapPublicationError("map output directory is a symlink")
    maps_root.mkdir(parents=True, exist_ok=True)
    if maps_root.is_symlink() or not maps_root.is_dir():
        raise BatchMapPublicationError("map output directory is unsafe")
    return Path(tempfile.mkdtemp(prefix=".w3xray-map-stage-", dir=maps_root))


def publish_map_stage(
    stage: Path, output_root: str, relative: str, digest: str
) -> Path:
    """Atomically replace only a previously owned content-addressed result."""
    destination_text = safe_destination(output_root, relative)
    if destination_text is None:
        raise BatchMapPublicationError("unsafe map output path")
    destination = Path(destination_text)
    backup: Path | None = None
    if destination.exists() or destination.is_symlink():
        _require_owned_destination(destination, digest)
        backup = destination.with_name(f".w3xray-map-old-{uuid4().hex}")
        os.replace(destination, backup)
    try:
        os.replace(stage, destination)
    except OSError:
        if backup is not None and not destination.exists():
            os.replace(backup, destination)
        raise
    if backup is not None:
        shutil.rmtree(backup)
    return destination


def discard_map_stage(stage: Path | None, output_root: str) -> None:
    """Remove only a private stage created directly below the map root."""
    if stage is None or not stage.exists() or stage.is_symlink():
        return
    maps_root = Path(output_root, "地图").resolve()
    if stage.parent.resolve() == maps_root and stage.name.startswith(
        ".w3xray-map-stage-"
    ):
        shutil.rmtree(stage)


def _require_owned_destination(destination: Path, digest: str) -> None:
    marker = destination / ".w3xray-batch-owned"
    try:
        owned = (
            destination.is_dir()
            and not destination.is_symlink()
            and not marker.is_symlink()
            and marker.read_text(encoding="ascii") == digest
        )
    except OSError as exc:
        raise BatchMapPublicationError(
            f"cannot inspect previous map output: {exc}"
        ) from exc
    if not owned:
        raise BatchMapPublicationError("refusing to replace unowned map output")
