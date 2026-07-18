"""Anchored relevant-sibling inventory and exact publication-name grammar."""

from __future__ import annotations

import os
import re
import stat
from typing import Final

from .description_cache_publication_models import RetainedCacheRole
from .description_cache_retained_integrity_models import (
    CacheArtifactKind,
    DescriptionCacheRetentionError,
    SiblingState,
)


RETAINED_PREFIX: Final = ".w3xray-description-cache-retained-"
STAGE_PREFIX: Final = ".w3xray-description-cache-stage-"
BACKUP_PREFIX: Final = ".w3xray-description-cache-backup-"
_HEX: Final = "[0-9a-f]{32}"
_RETAINED_PATTERN: Final = re.compile(
    rf"{re.escape(RETAINED_PREFIX)}({_HEX})-"
    r"(previous|failed-stage|failed-output|recovery)"
)
_STAGE_PATTERN: Final = re.compile(rf"{re.escape(STAGE_PREFIX)}({_HEX})")
_BACKUP_PATTERN: Final = re.compile(rf"{re.escape(BACKUP_PREFIX)}({_HEX})")
_HEX_SET: Final = frozenset("0123456789abcdef")


def stat_sibling(parent_descriptor: int, name: str) -> os.stat_result:
    """Stat one parent entry without following its final name."""
    return os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)


def capture_relevant_siblings(
    parent_descriptor: int,
    active_name: str,
) -> tuple[SiblingState, ...]:
    """Capture active and publication-relevant siblings in UTF-8 byte order."""
    try:
        names = tuple(os.listdir(parent_descriptor))
    except OSError as exc:
        raise DescriptionCacheRetentionError(
            "publication parent enumeration failed"
        ) from exc
    relevant = tuple(
        name
        for name in names
        if name == active_name
        or name.startswith(RETAINED_PREFIX)
        or name.startswith(STAGE_PREFIX)
        or name.startswith(BACKUP_PREFIX)
    )
    try:
        ordered = tuple(sorted(relevant, key=lambda name: name.encode("utf-8")))
    except UnicodeError as exc:
        raise DescriptionCacheRetentionError(
            "publication-relevant sibling is not UTF-8"
        ) from exc
    states: list[SiblingState] = []
    for name in ordered:
        try:
            details = stat_sibling(parent_descriptor, name)
        except FileNotFoundError:
            continue
        except OSError:
            states.append(
                SiblingState(
                    name,
                    CacheArtifactKind.UNKNOWN,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                )
            )
            continue
        states.append(
            SiblingState(
                name,
                kind_from_mode(details.st_mode),
                details.st_dev,
                details.st_ino,
                details.st_size,
                details.st_mtime_ns,
                details.st_ctime_ns,
                details.st_mode,
            )
        )
    return tuple(states)


def kind_from_mode(mode: int) -> CacheArtifactKind:
    """Map one no-follow stat mode to the closed artifact kind."""
    if stat.S_ISDIR(mode):
        return CacheArtifactKind.DIRECTORY
    if stat.S_ISREG(mode):
        return CacheArtifactKind.REGULAR_FILE
    if stat.S_ISLNK(mode):
        return CacheArtifactKind.SYMLINK
    return CacheArtifactKind.SPECIAL


def parse_retained_name(name: str) -> tuple[str, RetainedCacheRole] | None:
    """Parse only the exact retained transaction-and-role grammar."""
    matched = _RETAINED_PATTERN.fullmatch(name)
    if matched is None:
        return None
    transaction_id, role = matched.groups()
    return transaction_id, RetainedCacheRole(role)


def parse_stage_name(name: str) -> str | None:
    """Return the transaction identifier only for an exact stage name."""
    matched = _STAGE_PATTERN.fullmatch(name)
    return None if matched is None else matched.group(1)


def parse_backup_name(name: str) -> str | None:
    """Return the transaction identifier only for an exact backup name."""
    matched = _BACKUP_PATTERN.fullmatch(name)
    return None if matched is None else matched.group(1)


def transaction_prefix(name: str, prefix: str) -> str | None:
    """Preserve a valid leading transaction ID from a malformed name."""
    remainder = name.removeprefix(prefix)
    candidate = remainder[:32]
    if len(candidate) != 32 or any(value not in _HEX_SET for value in candidate):
        return None
    return candidate


__all__ = (
    "BACKUP_PREFIX",
    "RETAINED_PREFIX",
    "STAGE_PREFIX",
    "capture_relevant_siblings",
    "kind_from_mode",
    "parse_backup_name",
    "parse_retained_name",
    "parse_stage_name",
    "stat_sibling",
    "transaction_prefix",
)
