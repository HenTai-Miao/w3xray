"""Descriptor-anchored inventory and stable reads for trusted caches."""

from __future__ import annotations

import errno
import os
from pathlib import Path
import stat
from typing import Final

from .trusted_description_cache_generation_io import (
    read_trusted_cache_from_descriptor,
)
from .trusted_description_cache_models import (
    TrustedDescriptionCacheError,
    TrustedDescriptionCachePayloads,
)


_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_ANCHORED_CACHE_AVAILABLE: Final = bool(
    os.listdir in os.supports_fd
    and os.open in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks
    and hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
)


def read_trusted_cache_from_parent(
    parent_descriptor: int,
    name: str,
    display_root: Path,
) -> TrustedDescriptionCachePayloads:
    """Read one cache leaf relative to an already-held parent descriptor."""
    _require_anchored_support(display_root)
    if not name or name in {".", ".."} or Path(name).name != name:
        raise TrustedDescriptionCacheError("trusted cache leaf name is unsafe")
    descriptor = -1
    try:
        named = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_descriptor)
        opened = os.fstat(descriptor)
        if not _same_directory(named, opened):
            raise TrustedDescriptionCacheError(
                "trusted cache directory identity changed before open"
            )
        payloads, _proof = read_trusted_cache_from_descriptor(
            descriptor,
            display_root,
        )
        after = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        if not _same_directory(opened, after):
            raise TrustedDescriptionCacheError(
                "trusted cache directory identity changed while reading"
            )
        return payloads
    except TrustedDescriptionCacheError:
        raise
    except OSError as exc:
        reason = "cache leaf is a symlink" if exc.errno == errno.ELOOP else str(exc)
        raise TrustedDescriptionCacheError(
            f"cannot read anchored trusted cache {display_root}: {reason}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _require_anchored_support(path: Path) -> None:
    if not _ANCHORED_CACHE_AVAILABLE:
        raise TrustedDescriptionCacheError(
            f"descriptor-anchored trusted cache reads are unavailable: {path}"
        )


def _same_directory(first: os.stat_result, second: os.stat_result) -> bool:
    return bool(
        stat.S_ISDIR(first.st_mode)
        and stat.S_ISDIR(second.st_mode)
        and (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)
    )


__all__ = ("read_trusted_cache_from_parent",)
