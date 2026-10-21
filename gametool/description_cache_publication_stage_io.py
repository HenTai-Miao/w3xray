"""Descriptor-relative regular-file writes for one held cache stage."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
from typing import Final

from .description_cache_owned_schema import (
    TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY,
)
from .description_cache_publication_errors import DescriptionCachePublicationError
from .safe_output_chunk_writer import write_chunks_to_descriptor
from .trusted_description_cache_models import TrustedCacheLeafProof


_ALLOWED_STAGE_FILES: Final = frozenset(TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY)
_FILE_CREATE_FLAGS: Final = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_STAGE_IO_AVAILABLE: Final = bool(
    os.open in os.supports_dir_fd
    and os.mkdir in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks
    and os.listdir in os.supports_fd
    and hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_EXCL")
    and hasattr(os, "O_NOFOLLOW")
)


def require_stage_io_support() -> None:
    """Fail before mutation unless the complete anchored stage API exists."""
    if not _STAGE_IO_AVAILABLE:
        raise DescriptionCachePublicationError(
            "descriptor-anchored trusted-cache stage I/O is unavailable"
        )


def write_stage_text(
    stage_descriptor: int,
    display_root: Path,
    name: str,
    text: str,
) -> TrustedCacheLeafProof:
    """Exclusively write and prove one owned regular-file leaf."""
    if name not in _ALLOWED_STAGE_FILES or Path(name).name != name:
        raise DescriptionCachePublicationError(
            f"unsafe trusted-cache stage leaf: {display_root / name}"
        )
    payload = text.encode("utf-8")
    try:
        descriptor = os.open(
            name,
            _FILE_CREATE_FLAGS,
            0o600,
            dir_fd=stage_descriptor,
        )
    except OSError as exc:
        raise DescriptionCachePublicationError(
            f"cannot create trusted-cache stage leaf: {display_root / name}",
            failures=(exc,),
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise DescriptionCachePublicationError(
                f"trusted-cache stage leaf is not regular: {display_root / name}"
            )
        size = write_chunks_to_descriptor(descriptor, (payload,))
        after = os.fstat(descriptor)
        named = os.stat(name, dir_fd=stage_descriptor, follow_symlinks=False)
        expected = opened.st_dev, opened.st_ino
        if (
            not stat.S_ISREG(after.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or (after.st_dev, after.st_ino) != expected
            or (named.st_dev, named.st_ino) != expected
            or after.st_size != size
            or named.st_size != size
            or _stable_file_state(after) != _stable_file_state(named)
        ):
            raise DescriptionCachePublicationError(
                f"trusted-cache stage leaf changed while writing: {display_root / name}"
            )
        return TrustedCacheLeafProof(
            name,
            *expected,
            size,
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_mode,
            hashlib.sha256(payload).hexdigest(),
        )
    finally:
        os.close(descriptor)


def _stable_file_state(details: os.stat_result) -> tuple[int, ...]:
    return (
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
        details.st_mode,
    )


__all__ = ("require_stage_io_support", "write_stage_text")
