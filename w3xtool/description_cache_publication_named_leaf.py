"""Exact no-follow proofs for publication-parent leaves."""

from __future__ import annotations

from pathlib import Path

from .description_cache_publication_errors import merge_failures
from .description_cache_publication_fs import DirectoryIdentity, object_identity
from .description_cache_publication_models import (
    NamedLeafProof,
    PublicationTransientRecord,
    RetainedCacheRecord,
    RetainedEvidenceReproof,
)


def read_named_leaf(parent_descriptor: int, name: str) -> NamedLeafProof:
    """Read one name without treating non-absence I/O failure as absence."""
    try:
        return NamedLeafProof(True, object_identity(parent_descriptor, name))
    except FileNotFoundError:
        return NamedLeafProof(True, None)
    except OSError as exc:
        return NamedLeafProof(False, None, exc)


def reprove_retained(
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    records: tuple[RetainedCacheRecord, ...],
) -> RetainedEvidenceReproof:
    """Rebuild exact and uncertain retained rows without losing read faults."""
    retained: list[RetainedCacheRecord] = []
    transient: list[PublicationTransientRecord] = []
    failures: tuple[Exception, ...] = ()
    for record in records:
        if record.path.parent != parent:
            transient.append(
                PublicationTransientRecord(
                    parent, record.path.name, parent_identity, None
                )
            )
            continue
        proof = read_named_leaf(parent_descriptor, record.path.name)
        failures = merge_failures(failures, proof.failures)
        if proof.readable and proof.identity is None:
            continue
        if proof.identity == record.identity:
            retained.append(record)
        else:
            transient.append(
                PublicationTransientRecord(
                    parent,
                    record.path.name,
                    parent_identity,
                    proof.identity,
                )
            )
    return RetainedEvidenceReproof(
        tuple(dict.fromkeys(retained)),
        tuple(dict.fromkeys(transient)),
        failures,
    )


def reprove_transient(
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    records: tuple[PublicationTransientRecord, ...],
) -> RetainedEvidenceReproof:
    """Rebuild current transient rows and retain every non-absence read fault."""
    refreshed: list[PublicationTransientRecord] = []
    failures: tuple[Exception, ...] = ()
    for record in records:
        proof = read_named_leaf(parent_descriptor, record.leaf_name)
        failures = merge_failures(failures, proof.failures)
        if proof.readable and proof.identity is None and record.held_identity is None:
            continue
        refreshed.append(
            PublicationTransientRecord(
                parent,
                record.leaf_name,
                parent_identity,
                proof.identity,
                record.held_identity,
            )
        )
    return RetainedEvidenceReproof(
        transient=tuple(dict.fromkeys(refreshed)),
        failures=failures,
    )


def capture_named_transient(
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    path: Path,
) -> RetainedEvidenceReproof:
    """Capture one current name, readable absence, or exact read failure."""
    proof = read_named_leaf(parent_descriptor, path.name)
    if proof.readable and proof.identity is None:
        return RetainedEvidenceReproof()
    return RetainedEvidenceReproof(
        transient=(
            PublicationTransientRecord(
                parent,
                path.name,
                parent_identity,
                proof.identity,
            ),
        ),
        failures=proof.failures,
    )


__all__ = (
    "capture_named_transient",
    "read_named_leaf",
    "reprove_retained",
    "reprove_transient",
)
