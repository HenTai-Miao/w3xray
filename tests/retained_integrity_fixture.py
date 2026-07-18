"""Filesystem fixtures for retained description-cache integrity tests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

import pytest

from tests.trusted_description_cache_fixture import published_cache


_RETAINED: Final = ".w3xray-description-cache-retained-"
_STAGE: Final = ".w3xray-description-cache-stage-"
_BACKUP: Final = ".w3xray-description-cache-backup-"


def retained(active: Path, digit: str, role: str) -> Path:
    """Return one exact retained sibling path."""
    return active.parent / f"{_RETAINED}{digit * 32}-{role}"


def stage(active: Path, digit: str) -> Path:
    """Return one exact stage sibling path."""
    return active.parent / f"{_STAGE}{digit * 32}"


def backup(active: Path, digit: str) -> Path:
    """Return one exact backup sibling path."""
    return active.parent / f"{_BACKUP}{digit * 32}"


def active_cache(tmp_path: Path) -> Path:
    """Publish one active cache entirely below pytest's temporary root."""
    return published_cache(tmp_path / "active-source", raw="active")


def install_previous(active: Path, tmp_path: Path) -> Path:
    """Publish and rename one independently valid cache as previous evidence."""
    old = published_cache(tmp_path / "old-source", raw="previous")
    target = retained(active, "1", "previous")
    old.rename(target)
    return target


def make_fifo(path: Path) -> None:
    """Create a special object on hosts that support POSIX FIFOs."""
    if not hasattr(os, "mkfifo"):
        pytest.skip("POSIX FIFO fixtures are unavailable")
    os.mkfifo(path)


__all__ = (
    "active_cache",
    "backup",
    "install_previous",
    "make_fifo",
    "retained",
    "stage",
)
