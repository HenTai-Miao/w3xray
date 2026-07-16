"""Typed errors shared by trusted-cache publication modules."""

from __future__ import annotations

from typing import override


class DescriptionCachePublicationError(OSError):
    """A trusted cache could not be published without partial evidence."""

    __slots__: tuple[str, ...] = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    @override
    def __str__(self) -> str:
        return self.detail


class DescriptionCacheConcurrentDestinationError(DescriptionCachePublicationError):
    """Another writer acquired the destination during this transaction."""


class PublicationCommitContextError(DescriptionCachePublicationError):
    """A publication state needs explicit operator recovery context."""

    __slots__: tuple[str, ...] = ()


__all__ = (
    "DescriptionCacheConcurrentDestinationError",
    "DescriptionCachePublicationError",
    "PublicationCommitContextError",
)
