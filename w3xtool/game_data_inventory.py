"""Shared inventory capability for Warcraft III client-data sources."""

from __future__ import annotations

import fnmatch
from collections.abc import Generator
from enum import StrEnum
from typing import Protocol, TypeGuard, runtime_checkable

from .casclib_enumeration import CascEntry, CascNameType

GameDataEntry = CascEntry


class GameDataInventoryView(StrEnum):
    """Completeness of the names exposed by one client-data source."""

    FULL_ROOT = "full_root"
    KNOWN_PATHS = "known_paths"


class ReadableGameDataSource(Protocol):
    """Minimum typed boundary shared by every client-data reader."""

    def has_file(self, name: str) -> bool: ...

    def read_file(self, name: str) -> bytes: ...

    def close(self) -> None: ...


@runtime_checkable
class GameDataInventorySource(ReadableGameDataSource, Protocol):
    """Readable client data that can enumerate stable entry identities."""

    inventory_view: GameDataInventoryView

    def iter_entries(
        self,
        mask: str = "*",
        listfile: str | None = None,
    ) -> Generator[GameDataEntry, None, None]: ...


def supports_inventory(
    source: ReadableGameDataSource | None,
) -> TypeGuard[GameDataInventorySource]:
    """Return whether a readable source exposes the inventory capability."""
    return source is not None and isinstance(source, GameDataInventorySource)


def known_path_entry(
    name: str,
    *,
    size: int | None,
    is_local: bool,
) -> GameDataEntry:
    """Build an honest entry for a path known outside the native Root table."""
    return GameDataEntry(
        name=name,
        name_type=CascNameType.FULL,
        file_data_id=None,
        ckey="",
        ekey="",
        size=size,
        is_local=is_local,
        locale_flags=None,
        content_flags=None,
    )


def inventory_name_matches(name: str, mask: str) -> bool:
    """Match logical client paths case-insensitively across slash styles."""
    normalized_name = name.replace("\\", "/").casefold()
    normalized_mask = (mask or "*").replace("\\", "/").casefold()
    return fnmatch.fnmatchcase(normalized_name, normalized_mask)
