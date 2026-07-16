"""Typed results and byte inventory for trusted description caches."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .description_cache_models import DescriptionCache


@dataclass(frozen=True, slots=True)
class VerifiedDescriptionCache:
    """A fully rehashed cache and its two generation identities."""

    cache: DescriptionCache
    manifest_sha256: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class TrustedDescriptionCachePayloads:
    """Exact owned bytes read through one held cache-directory descriptor."""

    root: Path
    marker: bytes
    manifest: bytes
    cache: bytes
    source_manifest: bytes
    rejections: bytes


class TrustedDescriptionCacheError(OSError):
    """An owned trusted-description cache failed complete validation."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    def __str__(self) -> str:
        return self.detail


__all__ = (
    "TrustedDescriptionCacheError",
    "TrustedDescriptionCachePayloads",
    "VerifiedDescriptionCache",
)
