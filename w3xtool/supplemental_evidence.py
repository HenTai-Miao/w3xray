"""Normalized immutable plaintext, name, and MPQ-key evidence."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, override

from .bounded_file import BoundedFileError, FileIdentity, read_bounded_regular_file
from .extraction_ledger import BlockSource

if TYPE_CHECKING:
    from .author_plaintext_bundle import AuthorPlaintextBundle


_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class SupplementalEvidenceError(OSError):
    """Reject unsafe, changed, or conflicting supplemental evidence."""

    reason: str

    @override
    def __str__(self) -> str:
        return f"supplemental evidence rejected: {self.reason}"


@dataclass(frozen=True, slots=True)
class SupplementalFile:
    """One identity-pinned static plaintext file."""

    name: str
    path: Path
    sha256: str
    size: int
    identity: FileIdentity
    max_bytes: int
    source: BlockSource

    def read(self) -> bytes:
        """Re-read and verify the same regular-file identity and digest."""
        try:
            payload, identity = read_bounded_regular_file(
                self.path,
                self.max_bytes,
                expected=self.identity,
            )
        except BoundedFileError as exc:
            raise SupplementalEvidenceError(
                f"plaintext changed after validation: {self.name} ({exc.reason})",
            ) from exc
        if (
            identity.size != self.size
            or len(payload) != self.size
            or hashlib.sha256(payload).hexdigest() != self.sha256
        ):
            raise SupplementalEvidenceError(
                f"plaintext changed after validation: {self.name}",
            )
        return payload


@dataclass(frozen=True, slots=True)
class SupplementalKey:
    """Final 32-bit MPQ file key with required plaintext digest."""

    block_index: int
    key: int
    plaintext_sha256: str
    internal_path: str | None

    def __post_init__(self) -> None:
        if self.block_index < 0:
            raise SupplementalEvidenceError("block index must be non-negative")
        if not 0 <= self.key <= 0xFFFF_FFFF:
            raise SupplementalEvidenceError("MPQ key must be a 32-bit integer")
        if _SHA256_RE.fullmatch(self.plaintext_sha256) is None:
            raise SupplementalEvidenceError("invalid plaintext SHA-256")


@dataclass(frozen=True, slots=True)
class SupplementalEvidence:
    """All supplemental evidence bound to exactly one source digest."""

    source_sha256: str
    names: tuple[str, ...] = ()
    files: tuple[SupplementalFile, ...] = ()
    keys: tuple[SupplementalKey, ...] = ()

    def __post_init__(self) -> None:
        if _SHA256_RE.fullmatch(self.source_sha256) is None:
            raise SupplementalEvidenceError("invalid source SHA-256")
        _reject_internal_conflicts(self)

    def file_for(self, name: str) -> SupplementalFile | None:
        """Return the verified plaintext declaration for one normalized path."""
        key = normalize_internal_name(name)
        return next(
            (item for item in self.files if normalize_internal_name(item.name) == key),
            None,
        )

    def key_for(self, block_index: int) -> SupplementalKey | None:
        """Return the unique final key declaration for one block."""
        return next(
            (item for item in self.keys if item.block_index == block_index),
            None,
        )


def merge_supplemental_evidence(
    *sources: SupplementalEvidence | None,
) -> SupplementalEvidence | None:
    """Merge bound sources while rejecting path and block ownership conflicts."""
    present = tuple(source for source in sources if source is not None)
    if not present:
        return None
    source_sha256 = present[0].source_sha256
    names: list[str] = []
    files: list[SupplementalFile] = []
    keys: list[SupplementalKey] = []
    claimed_paths: set[str] = set()
    claimed_blocks: set[int] = set()
    for source in present:
        if source.source_sha256 != source_sha256:
            raise SupplementalEvidenceError("source SHA-256 conflict")
        for name in (*source.names, *(item.name for item in source.files)):
            key = normalize_internal_name(name)
            if key in claimed_paths:
                raise SupplementalEvidenceError(f"path conflict: {name}")
            claimed_paths.add(key)
        for item in source.keys:
            if item.block_index in claimed_blocks:
                raise SupplementalEvidenceError(
                    f"block conflict: {item.block_index}",
                )
            claimed_blocks.add(item.block_index)
        names.extend(source.names)
        files.extend(source.files)
        keys.extend(source.keys)
    return SupplementalEvidence(source_sha256, tuple(names), tuple(files), tuple(keys))


def evidence_from_author_bundle(
    bundle: AuthorPlaintextBundle,
) -> SupplementalEvidence:
    """Adapt the legacy v1 author bundle to the unified immutable model."""
    from .author_plaintext_bundle import MAX_BUNDLE_FILE_SIZE

    files = tuple(
        SupplementalFile(
            item.name,
            item.path,
            item.sha256,
            item.size,
            item.identity,
            MAX_BUNDLE_FILE_SIZE,
            BlockSource.AUTHOR_PLAINTEXT,
        )
        for item in bundle.files
    )
    return SupplementalEvidence(bundle.source_sha256, (), files, ())


def normalize_internal_name(name: str) -> str:
    """Return the case-insensitive lookup key for an already-safe path."""
    return name.replace("\\", "/").casefold()


def _reject_internal_conflicts(evidence: SupplementalEvidence) -> None:
    paths: set[str] = set()
    for name in (*evidence.names, *(item.name for item in evidence.files)):
        key = normalize_internal_name(name)
        if key in paths:
            raise SupplementalEvidenceError(f"duplicate internal path: {name}")
        paths.add(key)
    blocks: set[int] = set()
    for item in evidence.keys:
        if item.block_index in blocks:
            raise SupplementalEvidenceError(
                f"duplicate MPQ key block: {item.block_index}",
            )
        blocks.add(item.block_index)
