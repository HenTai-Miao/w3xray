"""Complete descriptor-held generation snapshots and byte proofs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
from typing import Final

from .description_cache_owned_schema import (
    TRUSTED_DESCRIPTION_CACHE_MANIFEST,
    TRUSTED_DESCRIPTION_CACHE_MARKER,
    TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY,
)
from .trusted_description_cache_file import read_owned_regular_file
from .trusted_description_cache_models import (
    TrustedCacheGenerationProof,
    TrustedCacheLeafProof,
    TrustedDescriptionCacheError,
    TrustedDescriptionCachePayloads,
)


_MAX_METADATA_BYTES: Final = 4 * 1024 * 1024
_MAX_PAYLOAD_BYTES: Final = 512 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class TrustedCacheNamedState:
    """One complete no-follow stat result bound to its owned name."""

    name: str
    details: os.stat_result


@dataclass(frozen=True, slots=True)
class TrustedCacheGenerationState:
    """One held directory and its complete ordered five-leaf snapshot."""

    directory: os.stat_result
    leaves: tuple[TrustedCacheNamedState, ...]


type StableFileState = tuple[int, int, int, int, int, int]
type StableNamedState = tuple[str, int, int, int, int, int, int]
type StableGenerationState = tuple[int, int, int, tuple[StableNamedState, ...]]


def snapshot_trusted_cache_generation(
    descriptor: int,
    display_root: Path,
) -> TrustedCacheGenerationState:
    """Snapshot exactly the five regular owned leaves and held directory."""
    try:
        before = os.fstat(descriptor)
        names = tuple(os.listdir(descriptor))
        leaves = tuple(
            TrustedCacheNamedState(
                name,
                os.stat(name, dir_fd=descriptor, follow_symlinks=False),
            )
            for name in TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY
        )
        after = os.fstat(descriptor)
    except OSError as exc:
        raise TrustedDescriptionCacheError(
            f"cannot snapshot held trusted cache {display_root}: {exc}"
        ) from exc
    if not stat.S_ISDIR(before.st_mode) or _directory_state(before) != _directory_state(
        after
    ):
        raise TrustedDescriptionCacheError(
            f"trusted cache directory changed while snapshotting: {display_root}"
        )
    expected = frozenset(TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY)
    if len(names) != len(expected) or frozenset(names) != expected:
        raise TrustedDescriptionCacheError("owned cache is partial or has unsafe files")
    if any(not stat.S_ISREG(leaf.details.st_mode) for leaf in leaves):
        raise TrustedDescriptionCacheError("owned cache is partial or has unsafe files")
    return TrustedCacheGenerationState(before, leaves)


def read_snapshot_payloads(
    descriptor: int,
    display_root: Path,
    snapshot: TrustedCacheGenerationState,
) -> TrustedDescriptionCachePayloads:
    """Read every leaf through the exact complete stat object captured earlier."""
    payloads: dict[str, bytes] = {}
    for leaf in snapshot.leaves:
        maximum = (
            _MAX_METADATA_BYTES
            if leaf.name
            in {
                TRUSTED_DESCRIPTION_CACHE_MARKER,
                TRUSTED_DESCRIPTION_CACHE_MANIFEST,
            }
            else _MAX_PAYLOAD_BYTES
        )
        payloads[leaf.name] = read_owned_regular_file(
            descriptor,
            leaf.name,
            leaf.details,
            display_root,
            maximum,
        )
    return TrustedDescriptionCachePayloads(
        display_root,
        payloads[TRUSTED_DESCRIPTION_CACHE_MARKER],
        payloads[TRUSTED_DESCRIPTION_CACHE_MANIFEST],
        payloads["可信描述缓存.tsv"],
        payloads["来源清单.tsv"],
        payloads["可信缓存迁移拒绝.tsv"],
    )


def prove_snapshot_payloads(
    before: TrustedCacheGenerationState,
    after: TrustedCacheGenerationState,
    payloads: TrustedDescriptionCachePayloads,
) -> TrustedCacheGenerationProof:
    """Require stable metadata and bind all five exact payload digests."""
    if _stable_generation_state(before) != _stable_generation_state(after):
        raise TrustedDescriptionCacheError(
            "trusted cache generation changed during complete read"
        )
    payload_by_name = {
        TRUSTED_DESCRIPTION_CACHE_MARKER: payloads.marker,
        TRUSTED_DESCRIPTION_CACHE_MANIFEST: payloads.manifest,
        "可信描述缓存.tsv": payloads.cache,
        "来源清单.tsv": payloads.source_manifest,
        "可信缓存迁移拒绝.tsv": payloads.rejections,
    }
    leaves = tuple(
        TrustedCacheLeafProof(
            leaf.name,
            leaf.details.st_dev,
            leaf.details.st_ino,
            leaf.details.st_size,
            leaf.details.st_mtime_ns,
            leaf.details.st_ctime_ns,
            leaf.details.st_mode,
            hashlib.sha256(payload_by_name[leaf.name]).hexdigest(),
        )
        for leaf in before.leaves
    )
    return TrustedCacheGenerationProof(
        before.directory.st_dev,
        before.directory.st_ino,
        leaves,
    )


def read_trusted_cache_from_descriptor(
    descriptor: int,
    display_root: Path,
    expected_leaves: tuple[TrustedCacheLeafProof, ...] | None = None,
) -> tuple[TrustedDescriptionCachePayloads, TrustedCacheGenerationProof]:
    """Read and prove one complete generation already held by the caller."""
    before = snapshot_trusted_cache_generation(descriptor, display_root)
    payloads = read_snapshot_payloads(descriptor, display_root, before)
    after = snapshot_trusted_cache_generation(descriptor, display_root)
    proof = prove_snapshot_payloads(before, after, payloads)
    if expected_leaves is not None and proof.leaves != expected_leaves:
        raise TrustedDescriptionCacheError(
            "held trusted cache differs from its writer proof"
        )
    return payloads, proof


def _stable_file_state(details: os.stat_result) -> StableFileState:
    return (
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
        details.st_mode,
    )


def _stable_generation_state(
    state: TrustedCacheGenerationState,
) -> StableGenerationState:
    return (
        state.directory.st_dev,
        state.directory.st_ino,
        state.directory.st_mode,
        tuple((leaf.name, *_stable_file_state(leaf.details)) for leaf in state.leaves),
    )


def _directory_state(details: os.stat_result) -> tuple[int, int, int]:
    return details.st_dev, details.st_ino, details.st_mode


__all__ = (
    "TrustedCacheGenerationState",
    "TrustedCacheNamedState",
    "prove_snapshot_payloads",
    "read_snapshot_payloads",
    "read_trusted_cache_from_descriptor",
    "snapshot_trusted_cache_generation",
)
