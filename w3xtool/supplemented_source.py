"""Reopenable path source that revalidates every supplemental input."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from .author_plaintext_bundle import load_author_plaintext_bundle
from .compat_bundle import load_compat_bundle
from .mpq import MPQArchive
from .supplemental_evidence import (
    SupplementalEvidence,
    evidence_from_author_bundle,
    merge_supplemental_evidence,
)
from .supplemented_archive import SupplementedArchive


@dataclass(frozen=True, slots=True)
class SupplementedPathArchiveSource:
    """Open the source MPQ with freshly verified optional evidence."""

    path: str
    author_bundle_path: str | None = None
    compat_bundle_path: str | None = None

    @contextmanager
    def open(self) -> Iterator[SupplementedArchive]:
        """Open one independent reader and close it on every exit path."""
        evidence = self._load_evidence()
        base = None
        try:
            base = MPQArchive(self.path)
        except (OSError, ValueError):
            if evidence is None or not evidence.files:
                raise
        archive = SupplementedArchive(self.path, base, evidence)
        try:
            yield archive
        finally:
            archive.close()

    def close(self) -> None:
        """Release no persistent state because every open owns its reader."""

    def _load_evidence(self) -> SupplementalEvidence | None:
        author = None
        if self.author_bundle_path is not None:
            author = evidence_from_author_bundle(
                load_author_plaintext_bundle(self.author_bundle_path, self.path),
            )
        compat = None
        if self.compat_bundle_path is not None:
            compat = load_compat_bundle(self.compat_bundle_path, self.path)
        return merge_supplemental_evidence(author, compat)
