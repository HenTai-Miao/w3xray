"""Descriptor-anchored inventory and stable reads for trusted caches."""

from __future__ import annotations

import errno
import os
from pathlib import Path
import stat
from typing import Final

from .description_cache_owned_schema import (
    TRUSTED_DESCRIPTION_CACHE_FILES,
    TRUSTED_DESCRIPTION_CACHE_MANIFEST,
    TRUSTED_DESCRIPTION_CACHE_MARKER,
)
from .trusted_description_cache_file import read_owned_regular_file
from .trusted_description_cache_models import (
    TrustedDescriptionCacheError,
    TrustedDescriptionCachePayloads,
)


_MAX_METADATA_BYTES: Final = 4 * 1024 * 1024
_MAX_PAYLOAD_BYTES: Final = 512 * 1024 * 1024
_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_EXPECTED_INVENTORY: Final = frozenset(
    (
        *TRUSTED_DESCRIPTION_CACHE_FILES,
        TRUSTED_DESCRIPTION_CACHE_MANIFEST,
        TRUSTED_DESCRIPTION_CACHE_MARKER,
    )
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
        payloads = _read_directory(descriptor, display_root)
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


def _read_directory(
    descriptor: int,
    root: Path,
) -> TrustedDescriptionCachePayloads:
    names = tuple(os.listdir(descriptor))
    if len(names) != len(_EXPECTED_INVENTORY) or set(names) != _EXPECTED_INVENTORY:
        raise TrustedDescriptionCacheError("owned cache is partial or has unsafe files")
    states: dict[str, os.stat_result] = {}
    for name in names:
        details = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if not stat.S_ISREG(details.st_mode):
            raise TrustedDescriptionCacheError(
                "owned cache is partial or has unsafe files"
            )
        states[name] = details
    marker = read_owned_regular_file(
        descriptor,
        TRUSTED_DESCRIPTION_CACHE_MARKER,
        states[TRUSTED_DESCRIPTION_CACHE_MARKER],
        root,
        _MAX_METADATA_BYTES,
    )
    manifest = read_owned_regular_file(
        descriptor,
        TRUSTED_DESCRIPTION_CACHE_MANIFEST,
        states[TRUSTED_DESCRIPTION_CACHE_MANIFEST],
        root,
        _MAX_METADATA_BYTES,
    )
    cache = read_owned_regular_file(
        descriptor,
        "可信描述缓存.tsv",
        states["可信描述缓存.tsv"],
        root,
        _MAX_PAYLOAD_BYTES,
    )
    source_manifest = read_owned_regular_file(
        descriptor,
        "来源清单.tsv",
        states["来源清单.tsv"],
        root,
        _MAX_PAYLOAD_BYTES,
    )
    rejections = read_owned_regular_file(
        descriptor,
        "可信缓存迁移拒绝.tsv",
        states["可信缓存迁移拒绝.tsv"],
        root,
        _MAX_PAYLOAD_BYTES,
    )
    return TrustedDescriptionCachePayloads(
        root,
        marker,
        manifest,
        cache,
        source_manifest,
        rejections,
    )


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
