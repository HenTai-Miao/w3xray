"""Stable, traversal-free directory reads for resource-candidate fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
from io import BufferedReader
import os
from pathlib import Path
import stat
from typing import BinaryIO, Protocol, cast, runtime_checkable

from .safe_output import safe_relative_path
from .mpq_storage import open_regular_binary


class ResourceReadableSource(Protocol):
    def read_file(self, name: str) -> bytes: ...


@runtime_checkable
class VerifiableResourceSource(Protocol):
    def verify_source(self) -> None: ...


class ResourcePathConflict(ValueError):
    """Multiple physical entries compete for one archive-style path."""


type _Identity = tuple[int, int, int, int, int, int]


def _identity(path: Path) -> _Identity:
    return _stat_identity(path.lstat())


def _descriptor_identity(handle: BinaryIO) -> _Identity:
    return _stat_identity(os.fstat(handle.fileno()))


def _stat_identity(details: os.stat_result) -> _Identity:
    return (
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
        details.st_mode,
    )


def _content_fingerprint(handle: BinaryIO) -> tuple[bytes, int]:
    """Hash the complete stream with bounded working memory, never a byte quota."""
    digest = hashlib.sha256()
    byte_count = 0
    buffer = bytearray(1024 * 1024)
    view = memoryview(buffer)
    # open_regular_binary owns os.fdopen(..., "rb"), hence a buffered reader.
    reader = cast(BufferedReader, handle)
    while True:
        amount = reader.readinto(buffer)
        if amount is None:
            raise OSError("resource source read unavailable before delivery")
        if not amount:
            return digest.digest(), byte_count
        digest.update(view[:amount])
        byte_count += amount


class ResourceDirectorySource:
    """Index all names; refuse case aliases and changed source snapshots."""

    def __init__(self, root: str) -> None:
        self.root = Path(os.path.abspath(root))
        self._require_ancestors(self.root)
        self._root_identity = _identity(self.root)
        self._entries = self._index()
        self._reads: dict[Path, tuple[_Identity, _Identity, bytes]] = {}

    def _index(self) -> dict[str, tuple[Path, ...]]:
        entries: dict[str, list[Path]] = {}
        for current, directories, names in os.walk(
            self.root, followlinks=False, onerror=_walk_error
        ):
            directories[:] = [
                name
                for name in directories
                if not (Path(current) / name).is_symlink()
                and not (Path(current) / name).is_junction()
            ]
            for name in names:
                path = Path(current) / name
                key = str(path.relative_to(self.root)).replace("/", "\\").casefold()
                entries.setdefault(key, []).append(path)
        return {key: tuple(sorted(paths)) for key, paths in entries.items()}

    def read_file(self, name: str) -> bytes:
        relative = safe_relative_path(name)
        if relative is None:
            raise ValueError(f"unsafe resource path: {name}")
        self._require_ancestors(self.root.joinpath(*relative.parts))
        key = "\\".join(relative.parts).casefold()
        candidates = self._entries.get(key, ())
        if not candidates:
            raise KeyError(name)
        if len(candidates) != 1:
            raise ResourcePathConflict(
                f"resource path aliases: {name}: " + " | ".join(map(str, candidates))
            )
        path = candidates[0]
        self._require_ancestors(path)
        before = _identity(path)
        if not stat.S_ISREG(before[-1]):
            raise ValueError(f"resource source is not a regular file: {path}")
        handle, _size = open_regular_binary(str(path))
        with handle:
            opened = _descriptor_identity(handle)
            # Windows pathname ctime is creation time; descriptor ctime is the
            # change time. Retain both and compare each through its own API.
            if (
                opened[:4] + opened[5:] != before[:4] + before[5:]
                or os.name != "nt"
                and opened != before
            ):
                raise OSError(f"resource source identity changed: {path}")
            data = handle.read()
            if _descriptor_identity(handle) != opened:
                raise OSError(f"resource source changed while reading: {path}")
        if _identity(path) != before or len(data) != before[2]:
            raise OSError(f"resource source changed while reading: {path}")
        witness = before, opened, hashlib.sha256(data).digest()
        first = self._reads.get(path)
        if first is not None and witness != first:
            raise OSError(f"resource source changed since first read: {path}")
        if first is None:
            self._reads[path] = witness
        return data

    def verify_source(self) -> None:
        self._require_ancestors(self.root)
        if (
            _identity(self.root) != self._root_identity
            or self._index() != self._entries
        ):
            raise OSError("resource directory membership or root identity changed")
        for path, (
            expected_named,
            expected_opened,
            expected_digest,
        ) in self._reads.items():
            self._require_ancestors(path)
            if _identity(path) != expected_named:
                raise OSError(f"resource source changed before delivery: {path}")
            handle, _size = open_regular_binary(str(path))
            with handle:
                if (
                    _descriptor_identity(handle) != expected_opened
                    or _size != expected_opened[2]
                ):
                    raise OSError(f"resource source changed before delivery: {path}")
                digest, byte_count = _content_fingerprint(handle)
                if (
                    _descriptor_identity(handle) != expected_opened
                    or byte_count != expected_opened[2]
                    or digest != expected_digest
                ):
                    raise OSError(
                        f"resource source content changed before delivery: {path}"
                    )
            self._require_ancestors(path)
            if _identity(path) != expected_named:
                raise OSError(f"resource source changed before delivery: {path}")

    @staticmethod
    def _require_ancestors(path: Path) -> None:
        for entry in (path, *path.parents):
            if entry.is_symlink() or entry.is_junction():
                raise ValueError(f"resource source contains a symlink: {entry}")


def _walk_error(error: OSError) -> None:
    raise error


@contextmanager
def open_resource_directory(root: str) -> Iterator[ResourceDirectorySource]:
    """The source owns no persistent handles and never writes to the directory."""
    yield ResourceDirectorySource(root)
