"""Paged CASC inventory model shared by GUI and CLI surfaces."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import override

from .casclib_enumeration import CascEntry, CascNameType
from .game_data_inventory import GameDataInventorySource
from .safe_output import safe_relative_path, write_bytes_safely
from .safe_output_models import SafeWriteStatus


@dataclass(frozen=True, slots=True)
class CascInventoryPage:
    entries: tuple[CascEntry, ...]
    is_complete: bool


@dataclass(frozen=True, slots=True)
class CascEntryExportError(OSError):
    entry_name: str
    reason: str

    @override
    def __str__(self) -> str:
        return f"cannot export CASC entry {self.entry_name}: {self.reason}"


class CascBrowserModel:
    """Own a bounded page cursor over a potentially huge CASC root."""

    def __init__(
        self, source: GameDataInventorySource, *, page_size: int = 200
    ) -> None:
        if page_size < 1:
            raise CascEntryExportError(str(page_size), "page size must be positive")
        self._source: GameDataInventorySource = source
        self._page_size: int = page_size
        self._mask: str = "*"
        self._listfile: str | None = None
        self._iterator: Generator[CascEntry, None, None] | None = None
        self._buffered: CascEntry | None = None
        self._complete: bool = False

    def reset(self, *, mask: str = "*", listfile: str | None = None) -> None:
        """Restart enumeration with a native mask and optional external listfile."""
        self.close()
        self._mask = mask or "*"
        self._listfile = listfile
        self._complete = False

    def next_page(self) -> CascInventoryPage:
        """Return the next bounded page without retaining prior pages."""
        if self._complete:
            return CascInventoryPage((), True)
        iterator = self._open_iterator()
        entries: list[CascEntry] = []
        if self._buffered is not None:
            entries.append(self._buffered)
            self._buffered = None
        while len(entries) < self._page_size:
            try:
                entries.append(next(iterator))
            except StopIteration:
                self._finish()
                return CascInventoryPage(tuple(entries), True)
        try:
            self._buffered = next(iterator)
        except StopIteration:
            self._finish()
        return CascInventoryPage(tuple(entries), self._complete)

    def export_entry(self, entry: CascEntry, output_root: Path) -> Path:
        """Read one selected entry by its stable identity and write it safely."""
        payload = self._source.read_file(entry.read_name)
        relative_name = _export_relative_name(entry)
        result = write_bytes_safely(str(output_root), relative_name, payload)
        if result.status is not SafeWriteStatus.WRITTEN:
            raise CascEntryExportError(entry.name, result.error or result.status.value)
        return Path(result.path)

    def close(self) -> None:
        """Release an active native search even when paging stops early."""
        iterator = self._iterator
        self._iterator = None
        self._buffered = None
        if iterator is not None:
            iterator.close()

    def _open_iterator(self) -> Generator[CascEntry, None, None]:
        if self._iterator is None:
            self._iterator = self._source.iter_entries(self._mask, self._listfile)
        return self._iterator

    def _finish(self) -> None:
        self.close()
        self._complete = True


def _export_relative_name(entry: CascEntry) -> str:
    relative = casc_export_relative_name(entry.name)
    if entry.name_type is CascNameType.FULL and relative is not None:
        return relative
    fallback = relative if relative is not None else entry.ckey
    return f"UnknownCASC/{fallback}"


def casc_export_relative_name(name: str) -> str | None:
    """Map CASC module separators to directories, preserving storage read names.

    Native modular clients use names such as ``war3.w3mod:UI\\file.txt``.
    Colons cannot be ordinary Windows path components, so each proved module
    boundary becomes a directory. Other colon spellings remain invalid rather
    than becoming drive paths or alternate data streams.
    """
    parts = name.replace("\\", "/").split(":")
    if any(
        not part.rsplit("/", 1)[-1].casefold().endswith(".w3mod") for part in parts[:-1]
    ):
        return None
    if any(not part for part in parts):
        return None
    relative = safe_relative_path("/".join(parts))
    return None if relative is None else str(relative)
