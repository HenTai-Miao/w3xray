"""Root archive construction with optional verified static evidence."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from .author_plaintext_bundle import load_author_plaintext_bundle
from .bounded_file import BoundedFileError, sha256_regular_file
from .compat_bundle import load_compat_bundle
from .mpq import MPQArchive
from .supplemental_evidence import (
    SupplementalEvidence,
    SupplementalEvidenceError,
    evidence_from_author_bundle,
    merge_supplemental_evidence,
)
from .supplemented_archive import SupplementBase, SupplementedArchive


type ArchiveFactory = Callable[[str], SupplementBase]


@contextmanager
def open_map_archive(
    path: str,
    *,
    author_bundle_path: str | None = None,
    compat_bundle_path: str | None = None,
    archive_factory: ArchiveFactory = MPQArchive,
) -> Iterator[SupplementBase]:
    """Open the existing MPQ reader, adding only verified static evidence."""
    evidence = load_supplemental_evidence(
        path,
        author_bundle_path=author_bundle_path,
        compat_bundle_path=compat_bundle_path,
    )
    base: SupplementBase | None = None
    try:
        base = archive_factory(path)
    except OSError, ValueError:
        if evidence is None or not evidence.files:
            raise
    archive: SupplementBase
    if evidence is None:
        if base is None:
            raise SupplementalEvidenceError("archive did not open")
        archive = base
    else:
        archive = SupplementedArchive(path, base, evidence)
    try:
        yield archive
    finally:
        archive.close()


def load_supplemental_evidence(
    path: str,
    *,
    author_bundle_path: str | None,
    compat_bundle_path: str | None,
) -> SupplementalEvidence | None:
    """Load and conflict-check both optional evidence sources."""
    author = None
    if author_bundle_path is not None:
        author = evidence_from_author_bundle(
            load_author_plaintext_bundle(author_bundle_path, path),
        )
    compat = None
    if compat_bundle_path is not None:
        compat = load_compat_bundle(compat_bundle_path, path)
    return merge_supplemental_evidence(author, compat)


def source_sha256(path: str) -> str:
    """Hash one stable regular source path for report identity."""
    try:
        digest, _identity = sha256_regular_file(Path(path))
    except BoundedFileError as exc:
        raise SupplementalEvidenceError(f"cannot hash source: {exc.reason}") from exc
    return digest
