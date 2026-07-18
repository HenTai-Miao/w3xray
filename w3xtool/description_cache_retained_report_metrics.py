"""Exact proof-metric relations for retained report rows."""

from __future__ import annotations

import re
from typing import Final, assert_never

from .description_cache_owned_schema import (
    TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY,
)
from .description_cache_retained_integrity_models import (
    CacheArtifactKind,
    DescriptionCacheRetentionError,
    RetainedArtifactValidation,
    RetainedDescriptionCacheArtifact,
)


_DIGEST: Final = re.compile(r"[0-9a-f]{64}")
_OWNED_NAMES: Final = frozenset(TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY)


def validate_retained_metrics(item: RetainedDescriptionCacheArtifact) -> None:
    """Require exact validation-state totals, nullability, and problem paths."""
    metrics = (item.size, item.file_count, item.entry_count, item.sha256)
    complete = all(value is not None for value in metrics)
    incomplete = all(value is None for value in metrics)
    if not complete and not incomplete:
        raise DescriptionCacheRetentionError("retained proof fields are mixed")
    if complete:
        _validate_complete_values(item)
    match item.validation:
        case RetainedArtifactValidation.VALID_CACHE:
            if (
                not complete
                or item.kind is not CacheArtifactKind.DIRECTORY
                or item.file_count != 5
                or item.entry_count != 5
                or item.problem_path is not None
            ):
                raise DescriptionCacheRetentionError("invalid valid-cache proof")
        case RetainedArtifactValidation.PARTIAL_EVIDENCE:
            if not complete or item.problem_path is not None:
                raise DescriptionCacheRetentionError("invalid partial-evidence proof")
            _validate_partial_totals(item)
        case RetainedArtifactValidation.INVALID_PREVIOUS:
            if complete:
                _validate_directory_totals(item)
                _validate_complete_invalid_previous(item)
            elif not incomplete or item.problem_path is None:
                raise DescriptionCacheRetentionError(
                    "invalid previous proof is incomplete"
                )
        case RetainedArtifactValidation.UNSAFE_OBJECT:
            if not incomplete:
                raise DescriptionCacheRetentionError("unsafe object has proof metrics")
            _validate_unsafe_problem(item)
        case (
            RetainedArtifactValidation.OVERSIZED
            | RetainedArtifactValidation.UNSTABLE
            | RetainedArtifactValidation.UNREADABLE
        ):
            if not incomplete:
                raise DescriptionCacheRetentionError("failed proof has metrics")
        case unreachable:
            assert_never(unreachable)


def _validate_complete_values(item: RetainedDescriptionCacheArtifact) -> None:
    if (
        item.size is None
        or item.file_count is None
        or item.entry_count is None
        or item.sha256 is None
    ):
        raise DescriptionCacheRetentionError("retained proof fields are incomplete")
    if item.size < 0 or item.file_count < 0 or item.entry_count < 0:
        raise DescriptionCacheRetentionError("negative retained proof metric")
    if _DIGEST.fullmatch(item.sha256) is None:
        raise DescriptionCacheRetentionError("invalid retained SHA-256")


def _validate_partial_totals(item: RetainedDescriptionCacheArtifact) -> None:
    match item.kind:
        case CacheArtifactKind.DIRECTORY:
            _validate_directory_totals(item)
        case CacheArtifactKind.REGULAR_FILE:
            if item.file_count != 1 or item.entry_count != 0:
                raise DescriptionCacheRetentionError(
                    "regular-file partial proof totals are inconsistent"
                )
        case (
            CacheArtifactKind.SYMLINK
            | CacheArtifactKind.SPECIAL
            | CacheArtifactKind.UNKNOWN
        ):
            raise DescriptionCacheRetentionError("partial proof has impossible kind")
        case unreachable:
            assert_never(unreachable)


def _validate_directory_totals(item: RetainedDescriptionCacheArtifact) -> None:
    if (
        item.file_count is None
        or item.entry_count is None
        or item.file_count > item.entry_count
    ):
        raise DescriptionCacheRetentionError("directory proof totals are inconsistent")
    if item.file_count == 0 and item.size != 0:
        raise DescriptionCacheRetentionError("empty directory proof has nonzero size")


def _validate_complete_invalid_previous(
    item: RetainedDescriptionCacheArtifact,
) -> None:
    expected = len(_OWNED_NAMES)
    if item.problem_path is None:
        if item.file_count != expected or item.entry_count != expected:
            raise DescriptionCacheRetentionError(
                "invalid previous inventory mismatch lacks a problem path"
            )
        return
    if (
        item.file_count is not None
        and item.entry_count is not None
        and (item.file_count < expected or item.entry_count < expected)
        and item.problem_path not in _OWNED_NAMES
    ):
        raise DescriptionCacheRetentionError(
            "invalid previous inventory problem path is not canonical"
        )


def _validate_unsafe_problem(item: RetainedDescriptionCacheArtifact) -> None:
    match item.kind:
        case CacheArtifactKind.DIRECTORY:
            if item.problem_path is None:
                raise DescriptionCacheRetentionError(
                    "unsafe directory lacks a problem path"
                )
        case CacheArtifactKind.SYMLINK | CacheArtifactKind.SPECIAL:
            if item.problem_path is not None:
                raise DescriptionCacheRetentionError(
                    "top-level unsafe object has a problem path"
                )
        case CacheArtifactKind.REGULAR_FILE | CacheArtifactKind.UNKNOWN:
            if item.problem_path is not None:
                raise DescriptionCacheRetentionError("unsafe object has a problem path")
        case unreachable:
            assert_never(unreachable)


__all__ = ("validate_retained_metrics",)
