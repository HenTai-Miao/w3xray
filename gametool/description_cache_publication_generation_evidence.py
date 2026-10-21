"""Whole-set byte and namespace proof for successful publication."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Final, assert_never

from .description_cache_publication_descriptor_close import (
    DescriptorCloseLedger,
    close_publication_descriptors,
)
from .description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
    merge_failures,
)
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedEvidenceReproof,
)
from .description_cache_publication_named_leaf import read_named_leaf
from .description_cache_publication_parent_identity import require_parent_identity
from .trusted_description_cache_generation_io import (
    prove_snapshot_payloads,
    read_snapshot_payloads,
    snapshot_trusted_cache_generation,
)
from .trusted_description_cache_models import (
    TrustedCacheGenerationProof,
    VerifiedDescriptionCache,
)
from .trusted_description_cache_validation import (
    validate_trusted_description_cache_payloads,
)


_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


@dataclass(frozen=True, slots=True)
class ExpectedPublishedGeneration:
    """Expected identity and validated bytes at one public directory name."""

    path: Path
    identity: DirectoryIdentity
    verified: VerifiedDescriptionCache


@dataclass(frozen=True, slots=True)
class _GenerationRound:
    proofs: tuple[TrustedCacheGenerationProof, ...]
    private_before: tuple[DirectoryIdentity | None, ...]
    private_after: tuple[DirectoryIdentity | None, ...]


def require_stable_generation_set(
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    generations: tuple[ExpectedPublishedGeneration, ...],
    private_paths: tuple[Path, Path],
) -> None:
    """Require two stable whole-set reads and an absent private namespace."""
    require_parent_identity(parent_descriptor, parent, parent_identity)
    if not generations or any(item.path.parent != parent for item in generations):
        raise PublicationCommitContextError(
            "published generation set escaped the held parent; NEEDS_CONTEXT"
        )
    descriptors: list[int] = []
    try:
        for expected in generations:
            named = read_named_leaf(parent_descriptor, expected.path.name)
            if named.identity != expected.identity:
                raise PublicationCommitContextError(
                    "published generation name changed before final proof; NEEDS_CONTEXT"
                )
            descriptor = os.open(
                expected.path.name,
                _DIRECTORY_FLAGS,
                dir_fd=parent_descriptor,
            )
            descriptors.append(descriptor)
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != expected.identity:
                raise PublicationCommitContextError(
                    "published generation changed during final open; NEEDS_CONTEXT"
                )
        first = _read_generation_round(
            parent_descriptor,
            tuple(descriptors),
            generations,
            private_paths,
        )
        second = _read_generation_round(
            parent_descriptor,
            tuple(descriptors),
            generations,
            private_paths,
        )
        if first != second:
            raise PublicationCommitContextError(
                "published generation set changed between terminal reads; NEEDS_CONTEXT"
            )
    except OSError as exc:
        evidence = _namespace_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            generations,
            private_paths,
        )
        match exc:
            case DescriptionCachePublicationError() as publication_error:
                publication_error.replace_transient(
                    tuple(
                        dict.fromkeys(
                            (*publication_error.transient, *evidence.transient)
                        )
                    )
                )
                publication_error.replace_failures(
                    merge_failures(
                        publication_error.failures,
                        evidence.failures,
                    )
                )
                raise
            case OSError() as ordinary_error:
                raise PublicationCommitContextError(
                    "published generation-set proof failed; NEEDS_CONTEXT",
                    transient=evidence.transient,
                    failures=merge_failures(
                        (ordinary_error,),
                        evidence.failures,
                    ),
                ) from ordinary_error
            case unreachable:
                assert_never(unreachable)
    finally:
        close_publication_descriptors(
            tuple(
                (generations[index].path.name, descriptor)
                for index, descriptor in enumerate(descriptors)
            ),
            sys.exception(),
            DescriptorCloseLedger(),
            os.close,
        )
    final = _namespace_evidence(
        parent_descriptor,
        parent,
        parent_identity,
        generations,
        private_paths,
    )
    if final.transient or final.failures:
        raise PublicationCommitContextError(
            "published namespace changed after terminal hashes; NEEDS_CONTEXT",
            transient=final.transient,
            failures=final.failures,
        )
    require_parent_identity(parent_descriptor, parent, parent_identity)


def _read_generation_round(
    parent_descriptor: int,
    descriptors: tuple[int, ...],
    generations: tuple[ExpectedPublishedGeneration, ...],
    private_paths: tuple[Path, Path],
) -> _GenerationRound:
    before = tuple(
        snapshot_trusted_cache_generation(descriptor, expected.path)
        for descriptor, expected in zip(descriptors, generations, strict=True)
    )
    private_before = _private_identities(parent_descriptor, private_paths)
    payloads = tuple(
        read_snapshot_payloads(descriptor, expected.path, state)
        for descriptor, expected, state in zip(
            descriptors, generations, before, strict=True
        )
    )
    after = tuple(
        snapshot_trusted_cache_generation(descriptor, expected.path)
        for descriptor, expected in zip(descriptors, generations, strict=True)
    )
    private_after = _private_identities(parent_descriptor, private_paths)
    proofs: list[TrustedCacheGenerationProof] = []
    for expected, earlier, later, payload in zip(
        generations, before, after, payloads, strict=True
    ):
        proof = prove_snapshot_payloads(earlier, later, payload)
        if proof.directory_identity != expected.identity:
            raise PublicationCommitContextError(
                "published generation descriptor changed identity; NEEDS_CONTEXT"
            )
        verified = validate_trusted_description_cache_payloads(payload)
        if verified != expected.verified:
            raise PublicationCommitContextError(
                "published generation bytes differ from commit proof; NEEDS_CONTEXT"
            )
        proofs.append(proof)
    if any(identity is not None for identity in (*private_before, *private_after)):
        raise PublicationCommitContextError(
            "private publication name reappeared during result proof; NEEDS_CONTEXT"
        )
    return _GenerationRound(tuple(proofs), private_before, private_after)


def _private_identities(
    parent_descriptor: int,
    private_paths: tuple[Path, Path],
) -> tuple[DirectoryIdentity | None, ...]:
    identities: list[DirectoryIdentity | None] = []
    for path in private_paths:
        proof = read_named_leaf(parent_descriptor, path.name)
        if not proof.readable:
            assert proof.failure is not None
            raise proof.failure
        identities.append(proof.identity)
    return tuple(identities)


def _namespace_evidence(
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    generations: tuple[ExpectedPublishedGeneration, ...],
    private_paths: tuple[Path, Path],
) -> RetainedEvidenceReproof:
    transient: list[PublicationTransientRecord] = []
    failures: tuple[Exception, ...] = ()
    expected_by_name = {item.path.name: item.identity for item in generations}
    for path in (*tuple(item.path for item in generations), *private_paths):
        proof = read_named_leaf(parent_descriptor, path.name)
        failures = merge_failures(failures, proof.failures)
        expected = expected_by_name.get(path.name)
        if not proof.readable or proof.identity != expected:
            transient.append(
                PublicationTransientRecord(
                    parent,
                    path.name,
                    parent_identity,
                    proof.identity,
                )
            )
    return RetainedEvidenceReproof(
        transient=tuple(dict.fromkeys(transient)),
        failures=failures,
    )


__all__ = ("ExpectedPublishedGeneration", "require_stable_generation_set")
