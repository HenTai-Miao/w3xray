"""Cross-field and canonical-order invariants for retention reports."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Final, assert_never

from .description_cache_publication_models import RetainedCacheRole
from .description_cache_retained_integrity_models import (
    DESCRIPTION_CACHE_RETENTION_SCHEMA,
    CacheArtifactKind,
    DescriptionCacheRetentionError,
    DescriptionCacheRetentionReport,
    MalformedDescriptionCacheArtifact,
    RetainedArtifactValidation,
    RetainedDescriptionCacheArtifact,
    RetentionArtifactReason,
    TransientDescriptionCacheArtifact,
)
from .description_cache_retained_siblings import (
    BACKUP_PREFIX,
    RETAINED_PREFIX,
    STAGE_PREFIX,
    parse_backup_name,
    parse_retained_name,
    parse_stage_name,
    transaction_prefix,
)
from .safe_output import safe_relative_path


_DIGEST: Final = re.compile(r"[0-9a-f]{64}")
_COMPLETE_VALIDATIONS: Final = frozenset(
    (
        RetainedArtifactValidation.VALID_CACHE,
        RetainedArtifactValidation.PARTIAL_EVIDENCE,
        RetainedArtifactValidation.INVALID_PREVIOUS,
    )
)
_FAILED_DIRECTORY_VALIDATIONS: Final = frozenset(
    (
        RetainedArtifactValidation.PARTIAL_EVIDENCE,
        RetainedArtifactValidation.UNSAFE_OBJECT,
        RetainedArtifactValidation.OVERSIZED,
        RetainedArtifactValidation.UNSTABLE,
        RetainedArtifactValidation.UNREADABLE,
    )
)


def validate_retention_report(report: DescriptionCacheRetentionReport) -> None:
    """Require exact schema, sibling paths, rows, fields, and canonical order."""
    if report.schema != DESCRIPTION_CACHE_RETENTION_SCHEMA:
        raise DescriptionCacheRetentionError("unsupported retention report schema")
    if not report.active_root.is_absolute():
        raise DescriptionCacheRetentionError("active root must be absolute")
    if report.active_device < 0 or report.active_inode < 0:
        raise DescriptionCacheRetentionError("active identity must be nonnegative")
    for item in report.retained:
        _validate_retained(report.active_root, item)
    for item in report.transient:
        _validate_transient(report.active_root, item)
    for item in report.malformed:
        _validate_malformed(report.active_root, item)
    _ordered_unique(
        report.retained, tuple(sorted(report.retained, key=_retained_key)), "retained"
    )
    _ordered_unique(
        report.transient, tuple(sorted(report.transient, key=_other_key)), "transient"
    )
    _ordered_unique(
        report.malformed, tuple(sorted(report.malformed, key=_other_key)), "malformed"
    )


def _validate_retained(active: Path, item: RetainedDescriptionCacheArtifact) -> None:
    _sibling_path(active, item.path)
    if parse_retained_name(item.path.name) != (item.transaction_id, item.role):
        raise DescriptionCacheRetentionError("retained name fields are inconsistent")
    if not _transaction(item.transaction_id):
        raise DescriptionCacheRetentionError("invalid transaction ID")
    _identity(item.kind, item.device, item.inode)
    metrics = (item.size, item.file_count, item.entry_count, item.sha256)
    if (item.validation in _COMPLETE_VALIDATIONS) != all(
        value is not None for value in metrics
    ):
        raise DescriptionCacheRetentionError("retained proof fields are inconsistent")
    if item.size is not None and item.size < 0:
        raise DescriptionCacheRetentionError("negative retained size")
    if item.file_count is not None and item.file_count < 0:
        raise DescriptionCacheRetentionError("negative retained file count")
    if item.entry_count is not None and item.entry_count < 0:
        raise DescriptionCacheRetentionError("negative retained entry count")
    if item.sha256 is not None and _DIGEST.fullmatch(item.sha256) is None:
        raise DescriptionCacheRetentionError("invalid retained SHA-256")
    if item.problem_path is not None:
        safe = safe_relative_path(item.problem_path)
        if safe is None or safe.as_posix() != item.problem_path:
            raise DescriptionCacheRetentionError("unsafe retained problem path")
    _validate_classification(item)


def _validate_classification(item: RetainedDescriptionCacheArtifact) -> None:
    match item.role:
        case RetainedCacheRole.PREVIOUS:
            match item.kind:
                case CacheArtifactKind.DIRECTORY:
                    allowed = {
                        RetainedArtifactValidation.VALID_CACHE,
                        RetainedArtifactValidation.INVALID_PREVIOUS,
                        RetainedArtifactValidation.OVERSIZED,
                        RetainedArtifactValidation.UNSTABLE,
                        RetainedArtifactValidation.UNREADABLE,
                    }
                case (
                    CacheArtifactKind.REGULAR_FILE
                    | CacheArtifactKind.SYMLINK
                    | CacheArtifactKind.SPECIAL
                ):
                    allowed = {RetainedArtifactValidation.UNSAFE_OBJECT}
                case CacheArtifactKind.UNKNOWN:
                    allowed = {RetainedArtifactValidation.UNREADABLE}
                case unreachable:
                    assert_never(unreachable)
        case (
            RetainedCacheRole.FAILED_STAGE
            | RetainedCacheRole.FAILED_OUTPUT
            | RetainedCacheRole.RECOVERY
        ):
            match item.kind:
                case CacheArtifactKind.DIRECTORY:
                    allowed = set(_FAILED_DIRECTORY_VALIDATIONS)
                case CacheArtifactKind.REGULAR_FILE:
                    allowed = {
                        RetainedArtifactValidation.PARTIAL_EVIDENCE,
                        RetainedArtifactValidation.OVERSIZED,
                        RetainedArtifactValidation.UNSTABLE,
                        RetainedArtifactValidation.UNREADABLE,
                    }
                case CacheArtifactKind.SYMLINK | CacheArtifactKind.SPECIAL:
                    allowed = {RetainedArtifactValidation.UNSAFE_OBJECT}
                case CacheArtifactKind.UNKNOWN:
                    allowed = {RetainedArtifactValidation.UNREADABLE}
                case unreachable:
                    assert_never(unreachable)
        case unreachable:
            assert_never(unreachable)
    if item.validation not in allowed:
        raise DescriptionCacheRetentionError("invalid role-kind-validation combination")


def _validate_transient(active: Path, item: TransientDescriptionCacheArtifact) -> None:
    _sibling_path(active, item.path)
    _identity(item.kind, item.device, item.inode)
    stage_id = parse_stage_name(item.path.name)
    backup_id = parse_backup_name(item.path.name)
    if stage_id is not None:
        parsed = stage_id
        normal = RetentionArtifactReason.STAGE_TRANSIENT
    elif backup_id is not None:
        parsed = backup_id
        normal = RetentionArtifactReason.BACKUP_TRANSIENT
    else:
        raise DescriptionCacheRetentionError("transient name is malformed")
    match item.kind:
        case CacheArtifactKind.UNKNOWN:
            expected = RetentionArtifactReason.UNREADABLE_TRANSIENT
        case (
            CacheArtifactKind.DIRECTORY
            | CacheArtifactKind.REGULAR_FILE
            | CacheArtifactKind.SYMLINK
            | CacheArtifactKind.SPECIAL
        ):
            expected = normal
        case unreachable:
            assert_never(unreachable)
    if item.transaction_id != parsed or item.reason is not expected:
        raise DescriptionCacheRetentionError("transient row fields are inconsistent")


def _validate_malformed(active: Path, item: MalformedDescriptionCacheArtifact) -> None:
    _sibling_path(active, item.path)
    _identity(item.kind, item.device, item.inode)
    if item.path.name.startswith(RETAINED_PREFIX):
        prefix = RETAINED_PREFIX
        expected = RetentionArtifactReason.MALFORMED_RETAINED_NAME
    elif item.path.name.startswith(STAGE_PREFIX):
        prefix = STAGE_PREFIX
        expected = RetentionArtifactReason.MALFORMED_STAGE_NAME
    elif item.path.name.startswith(BACKUP_PREFIX):
        prefix = BACKUP_PREFIX
        expected = RetentionArtifactReason.MALFORMED_BACKUP_NAME
    else:
        raise DescriptionCacheRetentionError("malformed row lacks a publication prefix")
    if item.reason is not expected or item.transaction_id != transaction_prefix(
        item.path.name, prefix
    ):
        raise DescriptionCacheRetentionError("malformed row fields are inconsistent")


def _identity(kind: CacheArtifactKind, device: int | None, inode: int | None) -> None:
    if (device is None) != (inode is None):
        raise DescriptionCacheRetentionError("partial artifact identity")
    match kind:
        case CacheArtifactKind.UNKNOWN:
            if device is not None:
                raise DescriptionCacheRetentionError("unknown object has an identity")
        case (
            CacheArtifactKind.DIRECTORY
            | CacheArtifactKind.REGULAR_FILE
            | CacheArtifactKind.SYMLINK
            | CacheArtifactKind.SPECIAL
        ):
            if device is None or inode is None or device < 0 or inode < 0:
                raise DescriptionCacheRetentionError(
                    "readable object lacks an identity"
                )
        case unreachable:
            assert_never(unreachable)


def _sibling_path(active: Path, path: Path) -> None:
    if not path.is_absolute() or path.parent != active.parent:
        raise DescriptionCacheRetentionError("artifact is not an active-root sibling")


def _ordered_unique[T](
    actual: tuple[T, ...], expected: tuple[T, ...], label: str
) -> None:
    if actual != expected or len(set(actual)) != len(actual):
        raise DescriptionCacheRetentionError(
            f"{label} rows are duplicated or unordered"
        )


def _retained_key(item: RetainedDescriptionCacheArtifact) -> tuple[bytes, str]:
    return item.path.as_posix().encode("utf-8"), item.role.value


def _other_key(
    item: TransientDescriptionCacheArtifact | MalformedDescriptionCacheArtifact,
) -> tuple[bytes, str]:
    return item.path.as_posix().encode("utf-8"), item.reason.value


def _transaction(value: str) -> bool:
    return len(value) == 32 and all(
        character in "0123456789abcdef" for character in value
    )


__all__ = ("validate_retention_report",)
