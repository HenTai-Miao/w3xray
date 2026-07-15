"""Durable path-based publication for hosts without directory-fd writes."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from . import durable_io


def publish_staged_path(staged_path: str, destination: str) -> None:
    """Replace a regular destination and restore it on commit failure."""
    target = Path(destination)
    parent = target.parent
    backup: Path | None = None
    if target.exists():
        backup = parent / f".w3xray-backup-{uuid4().hex}.tmp"
        os.replace(target, backup)
        try:
            durable_io.sync_directory(parent)
        except OSError:
            os.replace(backup, target)
            durable_io.sync_directory(parent)
            raise
    try:
        os.replace(staged_path, target)
        durable_io.sync_directory(parent)
    except OSError:
        if backup is not None and backup.exists():
            os.replace(backup, target)
            durable_io.sync_directory(parent)
        raise
    if backup is not None:
        backup.unlink()
        durable_io.sync_directory(parent)
