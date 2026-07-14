"""Read classic Warcraft III game data from layered MPQ archives."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Final, Protocol, final

from .mpq import MPQArchive

CLASSIC_MPQ_NAMES: Final[tuple[str, ...]] = (
    "War3Patch.mpq",
    "War3xLocal.mpq",
    "War3x.mpq",
    "war3.mpq",
)


class ClassicArchive(Protocol):
    """Small archive surface required by the layered source."""

    def has_file(self, name: str) -> bool: ...

    def read_file(self, name: str) -> bytes: ...

    def close(self) -> None: ...


type ArchiveFactory = Callable[[str], ClassicArchive]


def classic_mpq_paths(root: str) -> tuple[str, ...]:
    """Return available classic archives in Warcraft override order."""
    directory = Path(root)
    if not directory.is_dir():
        return ()
    try:
        by_name = {
            entry.name.casefold(): entry
            for entry in directory.iterdir()
            if entry.is_file()
        }
    except OSError:
        return ()
    return tuple(
        str(by_name[name.casefold()])
        for name in CLASSIC_MPQ_NAMES
        if name.casefold() in by_name
    )


def is_classic_mpq_install(root: str) -> bool:
    """Return whether the directory contains the required base archive."""
    return any(
        Path(path).name.casefold() == "war3.mpq" for path in classic_mpq_paths(root)
    )


@final
class ClassicMpqDataSource:
    """Layer classic MPQs without modifying or copying their contents."""

    def __init__(
        self, root: str, *, archive_factory: ArchiveFactory = MPQArchive
    ) -> None:
        paths = classic_mpq_paths(root)
        if not any(Path(path).name.casefold() == "war3.mpq" for path in paths):
            raise FileNotFoundError(root)
        archives: list[ClassicArchive] = []
        try:
            archives.extend(archive_factory(path) for path in paths)
        except OSError, ValueError:
            for archive in archives:
                archive.close()
            raise
        self.root = str(Path(root))
        self._paths = paths
        self._archives = tuple(archives)
        self._closed = False

    def has_file(self, name: str) -> bool:
        """Return whether any layer contains the normalized member path."""
        member = _member_name(name)
        return any(archive.has_file(member) for archive in self._archives)

    def read_file(self, name: str) -> bytes:
        """Read the highest-priority matching member."""
        payload, _source_path = self.read_file_with_source(name)
        return payload

    def read_file_with_source(self, name: str) -> tuple[bytes, str]:
        """Read a member and identify the exact MPQ layer that supplied it."""
        member = _member_name(name)
        for source_path, archive in zip(self._paths, self._archives, strict=True):
            if archive.has_file(member):
                return archive.read_file(member), source_path
        raise FileNotFoundError(name)

    def close(self) -> None:
        """Close every owned MPQ exactly once."""
        if self._closed:
            return
        self._closed = True
        for archive in self._archives:
            archive.close()


def _member_name(name: str) -> str:
    return name.replace("/", "\\").lstrip("\\")
