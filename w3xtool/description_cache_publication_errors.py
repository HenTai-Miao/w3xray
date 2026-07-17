"""Typed errors shared by trusted-cache publication modules."""

from __future__ import annotations

from typing import override

from .description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRecord,
    RetainedCacheRole,
)


def merge_retained(
    earlier: tuple[RetainedCacheRecord, ...],
    later: tuple[RetainedCacheRecord, ...],
) -> tuple[RetainedCacheRecord, ...]:
    """Merge evidence in event order while keeping the first occurrence."""
    return tuple(dict.fromkeys((*earlier, *later)))


def merge_failures(
    earlier: tuple[Exception, ...],
    later: tuple[Exception, ...],
) -> tuple[Exception, ...]:
    """Merge exception evidence by identity in event order."""
    merged: list[Exception] = []
    for failure in (*earlier, *later):
        if all(current is not failure for current in merged):
            merged.append(failure)
    return tuple(merged)


class DescriptionCachePublicationError(OSError):
    """A trusted cache could not be published without partial evidence."""

    __slots__: tuple[str, ...] = ("detail", "failures", "retained", "transient")

    detail: str
    retained: tuple[RetainedCacheRecord, ...]
    transient: tuple[PublicationTransientRecord, ...]
    failures: tuple[Exception, ...]

    def __init__(
        self,
        detail: str,
        retained: tuple[RetainedCacheRecord, ...] = (),
        transient: tuple[PublicationTransientRecord, ...] = (),
        failures: tuple[Exception, ...] = (),
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.retained = retained
        self.transient = transient
        self.failures = failures

    def replace_retained(
        self,
        retained: tuple[RetainedCacheRecord, ...],
    ) -> None:
        self.retained = retained

    def replace_transient(
        self,
        transient: tuple[PublicationTransientRecord, ...],
    ) -> None:
        self.transient = transient

    def replace_failures(self, failures: tuple[Exception, ...]) -> None:
        self.failures = failures

    def append_close_context(
        self,
        detail: str,
        failures: tuple[Exception, ...],
    ) -> None:
        """Append descriptor-close evidence without replacing this subtype."""
        self.detail = f"{self.detail}; {detail}; NEEDS_CONTEXT"
        self.failures = merge_failures(self.failures, failures)

    @override
    def __str__(self) -> str:
        return self.detail


class DescriptionCacheConcurrentDestinationError(DescriptionCachePublicationError):
    """Another writer acquired the destination during this transaction."""


class PublicationCommitContextError(DescriptionCachePublicationError):
    """A publication state needs explicit operator recovery context."""

    __slots__: tuple[str, ...] = ()


class RetainedObjectInstalledContextError(PublicationCommitContextError):
    """The intended retained target was installed; rollback is forbidden."""

    __slots__: tuple[str, ...] = ("installed",)

    installed: RetainedCacheRecord

    def __init__(
        self,
        installed: RetainedCacheRecord,
        detail: str,
        retained: tuple[RetainedCacheRecord, ...] = (),
        transient: tuple[PublicationTransientRecord, ...] = (),
        failures: tuple[Exception, ...] = (),
    ) -> None:
        super().__init__(detail, retained, transient, failures)
        self.installed = installed


def installed_context_error(
    installed: RetainedCacheRecord,
    evidence: DescriptionCachePublicationError,
) -> RetainedObjectInstalledContextError:
    """Wrap finalized evidence without discarding that object or its cause."""
    return RetainedObjectInstalledContextError(
        installed,
        str(evidence),
        evidence.retained,
        evidence.transient,
        merge_failures(evidence.failures, (evidence,)),
    )


__all__ = (
    "DescriptionCacheConcurrentDestinationError",
    "DescriptionCachePublicationError",
    "PublicationCommitContextError",
    "RetainedObjectInstalledContextError",
    "RetainedCacheRecord",
    "RetainedCacheRole",
    "installed_context_error",
    "merge_failures",
    "merge_retained",
)
