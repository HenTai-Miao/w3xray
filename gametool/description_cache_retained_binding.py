"""Continuously held publication-parent and active-root identity boundary."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import stat

from .description_cache_retained_integrity_models import (
    DescriptionCacheRetentionError,
)
from .integrity_path_binding import (
    BoundDirectoryPath,
    IntegrityPathBindingError,
    bind_directory_path,
)


@dataclass(frozen=True, slots=True)
class BoundActiveCache:
    """Held ancestry descriptors and the active cache's exact identity."""

    root: Path
    binding: BoundDirectoryPath
    parent_descriptor: int
    root_descriptor: int
    parent_identity: tuple[int, int]
    root_identity: tuple[int, int]

    def require_current(self) -> None:
        """Prove every held ancestry component and active root still agree."""
        try:
            self.binding.require_current()
            held_parent = os.fstat(self.parent_descriptor)
            held_root = os.fstat(self.root_descriptor)
        except (IntegrityPathBindingError, OSError, NotImplementedError) as exc:
            raise DescriptionCacheRetentionError(
                "active cache binding became unavailable"
            ) from exc
        if (
            not stat.S_ISDIR(held_parent.st_mode)
            or not stat.S_ISDIR(held_root.st_mode)
            or _identity(held_parent) != self.parent_identity
            or _identity(held_root) != self.root_identity
        ):
            raise DescriptionCacheRetentionError("active cache identity changed")


@contextmanager
def bind_active_cache(active_root: Path) -> Generator[BoundActiveCache]:
    """Bind every no-follow component through the active directory."""
    root = Path(os.path.abspath(active_root.expanduser()))
    try:
        binding = bind_directory_path(root)
        with binding:
            if len(binding.descriptors) < 2:
                raise DescriptionCacheRetentionError(
                    "active root must name a directory"
                )
            parent_descriptor = binding.descriptors[-2]
            root_descriptor = binding.descriptor
            parent_details = os.fstat(parent_descriptor)
            opened_root = os.fstat(root_descriptor)
            bound = BoundActiveCache(
                root,
                binding,
                parent_descriptor,
                root_descriptor,
                _identity(parent_details),
                _identity(opened_root),
            )
            bound.require_current()
            yield bound
            bound.require_current()
    except DescriptionCacheRetentionError:
        raise
    except (IntegrityPathBindingError, OSError, NotImplementedError) as exc:
        raise DescriptionCacheRetentionError("cannot bind active cache") from exc


def _identity(details: os.stat_result) -> tuple[int, int]:
    return details.st_dev, details.st_ino


__all__ = ("BoundActiveCache", "bind_active_cache")
