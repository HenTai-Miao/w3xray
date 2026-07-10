"""Reusable, closeable sources for MPQ-backed map data."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
import os
from pathlib import Path
import tempfile
from types import TracebackType
from typing import ContextManager, Protocol, override

from .map_archive_reader import MapArchiveReader
from .mpq import MPQArchive


class ArchiveSource(Protocol):
    """Open a fresh reader for a map archive and release source-owned state."""

    path: str

    def open(self) -> ContextManager[MapArchiveReader]: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ArchiveSourceClosedError(OSError):
    """Raised when a closed byte-backed archive source is reopened."""

    path: str

    @override
    def __str__(self) -> str:
        return f"archive source is closed: {self.path}"


@dataclass(frozen=True, slots=True)
class PathArchiveSource:
    """Open independent MPQ readers from an on-disk map path."""

    path: str

    def open(self) -> MPQArchive:
        """Open a new MPQ reader; the reader owns its own context lifecycle."""
        return MPQArchive(self.path)

    def close(self) -> None:
        """Release no state because path-backed sources own no open archive."""


@dataclass(slots=True)
class BytesArchiveSource:
    """Own immutable payload bytes until close releases them permanently.

    This is intentionally mutable because ``close`` drops the payload and makes
    future opens invalid. Each open writes a unique system-temporary MPQ file.
    """

    path: str
    _payload: bytes = field(repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    @property
    def is_closed(self) -> bool:
        """Whether the source can no longer produce archive readers."""
        return self._closed

    def open(self) -> ContextManager[MPQArchive]:
        """Return a temporary-file reader context or reject a closed source."""
        if self._closed:
            raise ArchiveSourceClosedError(path=self.path)
        return self._open()

    @contextmanager
    def _open(self) -> Iterator[MPQArchive]:
        """Yield a reader backed by a temporary file removed after use."""
        descriptor, temp_path = tempfile.mkstemp(
            prefix="w3xray-bytes-",
            suffix=Path(self.path).suffix or ".w3x",
        )
        archive: MPQArchive | None = None
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(self._payload)
            archive = MPQArchive(temp_path)
            try:
                yield archive
            finally:
                archive.close()
        finally:
            try:
                os.remove(temp_path)
            except FileNotFoundError:
                pass

    def close(self) -> None:
        """Release the owned bytes and reject all future opens."""
        if self._closed:
            return
        self._closed = True
        self._payload = b""

    def __enter__(self) -> BytesArchiveSource:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.close()
