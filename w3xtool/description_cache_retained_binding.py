"""Continuously held publication-parent and active-root identity boundary."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import stat
from typing import Final

from .description_cache_retained_integrity_models import (
    DescriptionCacheRetentionError,
)


_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


@dataclass(frozen=True, slots=True)
class BoundActiveCache:
    """Two held descriptors and the exact public identities they must retain."""

    root: Path
    parent_descriptor: int
    root_descriptor: int
    parent_identity: tuple[int, int]
    root_identity: tuple[int, int]

    def require_current(self) -> None:
        """Prove the held descriptors and both requested pathnames still agree."""
        try:
            held_parent = os.fstat(self.parent_descriptor)
            named_parent = os.stat(self.root.parent, follow_symlinks=False)
            held_root = os.fstat(self.root_descriptor)
            named_root = os.stat(
                self.root.name,
                dir_fd=self.parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise DescriptionCacheRetentionError(
                "active cache binding became unavailable"
            ) from exc
        if (
            not stat.S_ISDIR(held_parent.st_mode)
            or not stat.S_ISDIR(named_parent.st_mode)
            or not stat.S_ISDIR(held_root.st_mode)
            or not stat.S_ISDIR(named_root.st_mode)
            or _identity(held_parent) != self.parent_identity
            or _identity(named_parent) != self.parent_identity
            or _identity(held_root) != self.root_identity
            or _identity(named_root) != self.root_identity
        ):
            raise DescriptionCacheRetentionError("active cache identity changed")


@contextmanager
def bind_active_cache(active_root: Path) -> Generator[BoundActiveCache]:
    """Bind an explicit non-symlink directory and its canonical parent."""
    root = Path(os.path.abspath(active_root.expanduser()))
    try:
        if root.is_symlink() or root.parent.resolve(strict=True) != root.parent:
            raise DescriptionCacheRetentionError("active root traverses a symlink")
        parent_descriptor = os.open(root.parent, _DIRECTORY_FLAGS)
    except DescriptionCacheRetentionError:
        raise
    except OSError as exc:
        raise DescriptionCacheRetentionError("cannot bind active cache parent") from exc
    try:
        try:
            parent_details = os.fstat(parent_descriptor)
            named_root = os.stat(
                root.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if not stat.S_ISDIR(named_root.st_mode):
                raise DescriptionCacheRetentionError(
                    "active root is not a no-follow directory"
                )
            root_descriptor = os.open(
                root.name,
                _DIRECTORY_FLAGS,
                dir_fd=parent_descriptor,
            )
        except DescriptionCacheRetentionError:
            raise
        except OSError as exc:
            raise DescriptionCacheRetentionError(
                "cannot bind active cache root"
            ) from exc
        try:
            opened_root = os.fstat(root_descriptor)
            if _identity(opened_root) != _identity(named_root):
                raise DescriptionCacheRetentionError(
                    "active root changed while binding"
                )
            bound = BoundActiveCache(
                root,
                parent_descriptor,
                root_descriptor,
                _identity(parent_details),
                _identity(opened_root),
            )
            bound.require_current()
            yield bound
            bound.require_current()
        finally:
            os.close(root_descriptor)
    finally:
        os.close(parent_descriptor)


def _identity(details: os.stat_result) -> tuple[int, int]:
    return details.st_dev, details.st_ino


__all__ = ("BoundActiveCache", "bind_active_cache")
