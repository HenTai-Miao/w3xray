"""Deterministic intermediate-parent swap for anchored source-read tests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


type OpenPath = str | bytes | os.PathLike[str] | os.PathLike[bytes]


class OpenFile(Protocol):
    def __call__(
        self,
        path: OpenPath,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int: ...


def swapping_open(
    real_open: OpenFile,
    source_parent: Path,
    moved_parent: Path,
    final_path: Path,
    events: list[str],
) -> OpenFile:
    """Swap one parent around the first relevant open, preserving its inode."""

    def open_after_swap(
        path: OpenPath,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        path_text = os.fsdecode(path)
        final_open = path_text == str(final_path)
        component_open = dir_fd is not None and path_text == source_parent.name
        if events or not (final_open or component_open):
            return _open(real_open, path, flags, mode, dir_fd)
        _ = source_parent.rename(moved_parent)
        source_parent.symlink_to(moved_parent, target_is_directory=True)
        events.append("parent swapped")
        try:
            return _open(real_open, path, flags, mode, dir_fd)
        finally:
            source_parent.unlink()
            _ = moved_parent.rename(source_parent)

    return open_after_swap


def _open(
    real_open: OpenFile,
    path: OpenPath,
    flags: int,
    mode: int,
    dir_fd: int | None,
) -> int:
    if dir_fd is None:
        return real_open(path, flags, mode)
    return real_open(path, flags, mode, dir_fd=dir_fd)


__all__ = ("swapping_open",)
