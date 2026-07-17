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
class TrustedCacheLeafProof:
    """Exact identity and bytes written for one owned stage leaf."""

    name: str
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    mode: int
    sha256: str

    @property
    def identity(self) -> tuple[int, int]:
        return self.device, self.inode


@dataclass(frozen=True, slots=True)
class TrustedCacheGenerationProof:
    """One stable directory identity and its complete five-leaf proof."""

    directory_device: int
    directory_inode: int
    leaves: tuple[TrustedCacheLeafProof, ...]

    @property
    def directory_identity(self) -> tuple[int, int]:
        return self.directory_device, self.directory_inode


@dataclass(frozen=True, slots=True)
class VerifiedDescriptionCacheGeneration:
    """Validated cache bytes bound to a complete stable generation proof."""

    verified: VerifiedDescriptionCache
    proof: TrustedCacheGenerationProof


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
    "TrustedCacheGenerationProof",
    "TrustedCacheLeafProof",
    "VerifiedDescriptionCache",
    "VerifiedDescriptionCacheGeneration",
)
