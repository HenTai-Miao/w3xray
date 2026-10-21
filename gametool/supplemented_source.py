"""Reopenable path source that revalidates every supplemental input."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ContextManager

from .map_archive_open import open_map_archive
from .mpq import MPQArchive
from .supplemented_archive import SupplementBase


@dataclass(frozen=True, slots=True)
class SupplementedPathArchiveSource:
    """Open the source MPQ with freshly verified optional evidence."""

    path: str
    author_bundle_path: str | None = None
    compat_bundle_path: str | None = None

    def open(self) -> ContextManager[SupplementBase]:
        """Open one independent reader and close it on every exit path."""
        return open_map_archive(
            self.path,
            author_bundle_path=self.author_bundle_path,
            compat_bundle_path=self.compat_bundle_path,
            archive_factory=MPQArchive,
        )

    def close(self) -> None:
        """Release no persistent state because every open owns its reader."""
