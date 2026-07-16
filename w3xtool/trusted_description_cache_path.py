"""Compatibility path reader for public trusted-cache loading."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from .bounded_file import read_bounded_regular_file
from .description_cache_owned_schema import (
    TRUSTED_DESCRIPTION_CACHE_FILES,
    TRUSTED_DESCRIPTION_CACHE_MANIFEST,
    TRUSTED_DESCRIPTION_CACHE_MARKER,
)
from .trusted_description_cache_models import (
    TrustedDescriptionCacheError,
    TrustedDescriptionCachePayloads,
)


_MAX_METADATA_BYTES: Final = 4 * 1024 * 1024
_MAX_PAYLOAD_BYTES: Final = 512 * 1024 * 1024


def read_trusted_cache_path(root: Path) -> TrustedDescriptionCachePayloads:
    """Read one public path with its established stable-file behavior."""
    directory = _canonical_directory(root)
    _require_exact_inventory(directory)
    return TrustedDescriptionCachePayloads(
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


def _require_exact_inventory(root: Path) -> None:
    expected = {
        *TRUSTED_DESCRIPTION_CACHE_FILES,
        TRUSTED_DESCRIPTION_CACHE_MANIFEST,
        TRUSTED_DESCRIPTION_CACHE_MARKER,
    }
    try:
        entries = tuple(root.iterdir())
    except OSError as exc:
        raise TrustedDescriptionCacheError(f"cannot list trusted cache: {exc}") from exc
    if {entry.name for entry in entries} != expected or any(
        entry.is_symlink() or not entry.is_file() for entry in entries
    ):
        raise TrustedDescriptionCacheError("owned cache is partial or has unsafe files")


def _read_stable(path: Path, maximum: int) -> bytes:
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
