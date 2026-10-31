"""Compatibility path reader for public trusted-cache loading."""

from __future__ import annotations

from contextlib import ExitStack
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Final

from .bounded_file import read_bounded_regular_file
from .description_cache_owned_schema import (
    TRUSTED_DESCRIPTION_CACHE_FILES,
    TRUSTED_DESCRIPTION_CACHE_MANIFEST,
    TRUSTED_DESCRIPTION_CACHE_MARKER,
    TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY,
)
from .trusted_description_cache_generation_io import (
    TrustedCacheGenerationState,
    TrustedCacheNamedState,
    prove_snapshot_payloads,
)
from .trusted_description_cache_models import (
    TrustedDescriptionCacheError,
    TrustedDescriptionCachePayloads,
)
from .windows_source_reads import WindowsSourceError, WindowsSourceRoot


_MAX_METADATA_BYTES: Final[int | None] = None
_MAX_PAYLOAD_BYTES: Final[int | None] = None


def read_trusted_cache_path(root: Path) -> TrustedDescriptionCachePayloads:
    """Read all five owned files within one proved complete generation."""
    directory = _canonical_directory(root)
    try:
        with ExitStack() as stack:
            if os.name == "nt":
                protected = stack.enter_context(WindowsSourceRoot.open(directory))
                # Keep every leaf held for the entire generation, not only its
                # individual double-read. The complete inventory is still checked
                # twice because directory handles do not exclude new children.
                before = _require_exact_inventory(directory)
                for name in TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY:
                    _ = stack.enter_context(protected.protect(PurePosixPath(name)))
            else:
                before = _require_exact_inventory(directory)
            payloads = TrustedDescriptionCachePayloads(
                directory,
                _read_stable(
                    directory / TRUSTED_DESCRIPTION_CACHE_MARKER,
                    _MAX_METADATA_BYTES,
                ),
                _read_stable(
                    directory / TRUSTED_DESCRIPTION_CACHE_MANIFEST,
                    _MAX_METADATA_BYTES,
                ),
                _read_stable(directory / "可信描述缓存.tsv", _MAX_PAYLOAD_BYTES),
                _read_stable(directory / "来源清单.tsv", _MAX_PAYLOAD_BYTES),
                _read_stable(directory / "可信缓存迁移拒绝.tsv", _MAX_PAYLOAD_BYTES),
            )
            _ = prove_snapshot_payloads(
                before, _require_exact_inventory(directory), payloads
            )
            return payloads
    except WindowsSourceError as exc:
        raise TrustedDescriptionCacheError(f"cannot read trusted cache: {exc}") from exc


def _canonical_directory(path: Path) -> Path:
    absolute = path.expanduser().absolute()
    if absolute.is_symlink() or not absolute.is_dir():
        raise TrustedDescriptionCacheError(
            "trusted cache root is not a regular directory or is a symlink"
        )
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise TrustedDescriptionCacheError(
            f"trusted cache root is unreadable: {exc}"
        ) from exc
    if resolved != absolute:
        raise TrustedDescriptionCacheError("trusted cache root traverses a symlink")
    return resolved


def _require_exact_inventory(root: Path) -> TrustedCacheGenerationState:
    expected = {
        *TRUSTED_DESCRIPTION_CACHE_FILES,
        TRUSTED_DESCRIPTION_CACHE_MANIFEST,
        TRUSTED_DESCRIPTION_CACHE_MARKER,
    }
    try:
        directory = root.stat(follow_symlinks=False)
        entries = tuple(root.iterdir())
    except OSError as exc:
        raise TrustedDescriptionCacheError(f"cannot list trusted cache: {exc}") from exc
    if (
        not stat.S_ISDIR(directory.st_mode)
        or {entry.name for entry in entries} != expected
    ):
        raise TrustedDescriptionCacheError("owned cache is partial or has unsafe files")
    try:
        leaves = tuple(
            TrustedCacheNamedState(name, (root / name).stat(follow_symlinks=False))
            for name in TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY
        )
    except OSError as exc:
        raise TrustedDescriptionCacheError(
            f"owned cache is partial or unreadable: {exc}"
        ) from exc
    if any(not stat.S_ISREG(leaf.details.st_mode) for leaf in leaves):
        raise TrustedDescriptionCacheError("owned cache is partial or has unsafe files")
    return TrustedCacheGenerationState(directory, leaves)


def _read_stable(path: Path, maximum: int | None) -> bytes:
    try:
        first, identity = read_bounded_regular_file(path, maximum)
        second, _repeated = read_bounded_regular_file(
            path,
            maximum,
            expected=identity,
        )
    except OSError as exc:
        raise TrustedDescriptionCacheError(
            f"cannot read owned regular file {path}: {exc}"
        ) from exc
    if first != second:
        raise TrustedDescriptionCacheError(f"owned file changed while reading: {path}")
    return first


__all__ = ("read_trusted_cache_path",)
