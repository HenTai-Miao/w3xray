"""Immutable outcomes for retained trusted-cache publication."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path

from .trusted_description_cache_models import VerifiedDescriptionCache


@unique
class RetainedCacheRole(StrEnum):
    """The only evidence roles publication may assign."""

    PREVIOUS = "previous"
    FAILED_STAGE = "failed-stage"
    FAILED_OUTPUT = "failed-output"
    RECOVERY = "recovery"


@dataclass(frozen=True, slots=True)
class RetainedCacheRecord:
    """One intentionally preserved sibling object and its proven inode."""

    path: Path
    role: RetainedCacheRole
    device: int
    inode: int

    @property
    def identity(self) -> tuple[int, int]:
        return self.device, self.inode


@dataclass(frozen=True, slots=True)
class PublicationTransientRecord:
    """One non-normalized leaf anchored to the parent that created it."""

    parent: Path
    leaf_name: str
    parent_identity: tuple[int, int]
    identity: tuple[int, int] | None
    held_identity: tuple[int, int] | None = None

    @property
    def path(self) -> Path:
        return self.parent / self.leaf_name


@dataclass(frozen=True, slots=True)
class DescriptionCachePublicationResult:
    """The verified active cache plus non-active evidence."""

    active: VerifiedDescriptionCache
    retained: tuple[RetainedCacheRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class RetainedCacheExpectation:
    """Exact validated bytes expected at one successful retained record."""

    record: RetainedCacheRecord
    verified: VerifiedDescriptionCache


@dataclass(frozen=True, slots=True)
class DescriptionCachePublicationProof:
    """Internal success proof kept until the public result boundary."""

    result: DescriptionCachePublicationResult
    retained_expectations: tuple[RetainedCacheExpectation, ...] = ()


@dataclass(frozen=True, slots=True)
class NamedLeafProof:
    """One no-follow named read and its exact non-absence failure."""

    readable: bool
    identity: tuple[int, int] | None
    failure: OSError | None = None

    @property
    def failures(self) -> tuple[Exception, ...]:
        return () if self.failure is None else (self.failure,)


@dataclass(frozen=True, slots=True)
class RetainedEvidenceReproof:
    """Current exact records, uncertain names, and exact read failures."""

    retained: tuple[RetainedCacheRecord, ...] = ()
    transient: tuple[PublicationTransientRecord, ...] = ()
    failures: tuple[Exception, ...] = ()


__all__ = (
    "DescriptionCachePublicationProof",
    "DescriptionCachePublicationResult",
    "NamedLeafProof",
    "PublicationTransientRecord",
    "RetainedCacheExpectation",
    "RetainedCacheRecord",
    "RetainedCacheRole",
    "RetainedEvidenceReproof",
)
