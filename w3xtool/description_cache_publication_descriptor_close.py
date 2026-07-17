"""Typed close boundary for publication-owned descriptors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from typing import assert_never

from .description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
)
from .description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRecord,
)


type CloseDescriptor = Callable[[int], None]
type NamedDescriptor = tuple[str, int]


@dataclass(slots=True)  # noqa: MUTABLE_OK - resource owner records final proof
class DescriptorCloseLedger:
    """Last immutable evidence available if close fails after success."""

    retained: tuple[RetainedCacheRecord, ...] = ()
    transient: tuple[PublicationTransientRecord, ...] = ()

    def remember(
        self,
        retained: tuple[RetainedCacheRecord, ...],
        transient: tuple[PublicationTransientRecord, ...],
    ) -> None:
        self.retained = retained
        self.transient = transient


def close_publication_descriptors(
    descriptors: tuple[NamedDescriptor, ...],
    in_flight: BaseException | None,
    ledger: DescriptorCloseLedger,
    close_descriptor: CloseDescriptor = os.close,
) -> None:
    """Attempt every close without replacing an in-flight typed failure."""
    failures: list[tuple[str, Exception]] = []

    def attempt(index: int) -> None:
        if index == len(descriptors):
            return
        label, descriptor = descriptors[index]
        try:
            close_descriptor(descriptor)
        except Exception as exc:  # noqa: BROAD_EXCEPT_OK - descriptor close evidence
            failures.append((label, exc))
        finally:
            attempt(index + 1)

    attempt(0)
    if not failures:
        return
    detail = "descriptor close failed: " + ", ".join(
        f"{label}={type(cause).__name__}" for label, cause in failures
    )
    failure_objects = tuple(cause for _, cause in failures)
    match in_flight:
        case DescriptionCachePublicationError() as publication_error:
            publication_error.append_close_context(detail, failure_objects)
        case None:
            raise PublicationCommitContextError(
                f"{detail}; NEEDS_CONTEXT",
                ledger.retained,
                ledger.transient,
                failure_objects,
            ) from failures[0][1]
        case BaseException() as active_error:
            active_error.add_note(detail)
        case unreachable:
            assert_never(unreachable)


__all__ = (
    "DescriptorCloseLedger",
    "close_publication_descriptors",
)
