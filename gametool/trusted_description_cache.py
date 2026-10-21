"""Public and held-parent loaders for trusted description caches."""

from __future__ import annotations

from pathlib import Path

from .description_cache_owned_schema import (
    TRUSTED_DESCRIPTION_CACHE_FILES,
    TRUSTED_DESCRIPTION_CACHE_MANIFEST,
    TRUSTED_DESCRIPTION_CACHE_MARKER,
    TRUSTED_DESCRIPTION_CACHE_SCHEMA,
)
from .trusted_description_cache_io import (
    read_trusted_cache_from_parent,
)
from .trusted_description_cache_generation_io import (
    read_trusted_cache_from_descriptor,
)
from .trusted_description_cache_models import (
    TrustedCacheLeafProof,
    TrustedDescriptionCacheError,
    VerifiedDescriptionCache,
    VerifiedDescriptionCacheGeneration,
)
from .trusted_description_cache_path import read_trusted_cache_path
from .trusted_description_cache_validation import (
    validate_trusted_description_cache_payloads,
)


def load_trusted_description_cache(root: Path) -> VerifiedDescriptionCache:
    """Return a cache only after validating every payload and source proof."""
    return validate_trusted_description_cache_payloads(read_trusted_cache_path(root))


def load_trusted_description_cache_from_parent(
    parent_descriptor: int,
    name: str,
    display_root: Path,
) -> VerifiedDescriptionCache:
    """Validate one cache leaf solely through an already-held parent fd."""
    return validate_trusted_description_cache_payloads(
        read_trusted_cache_from_parent(parent_descriptor, name, display_root)
    )


def load_trusted_description_cache_from_descriptor(
    descriptor: int,
    display_root: Path,
    expected_leaves: tuple[TrustedCacheLeafProof, ...],
) -> VerifiedDescriptionCacheGeneration:
    """Validate bytes and retain their complete generation proof."""
    payloads, proof = read_trusted_cache_from_descriptor(
        descriptor,
        display_root,
        expected_leaves,
    )
    return VerifiedDescriptionCacheGeneration(
        validate_trusted_description_cache_payloads(payloads),
        proof,
    )


__all__ = (
    "TRUSTED_DESCRIPTION_CACHE_FILES",
    "TRUSTED_DESCRIPTION_CACHE_MANIFEST",
    "TRUSTED_DESCRIPTION_CACHE_MARKER",
    "TRUSTED_DESCRIPTION_CACHE_SCHEMA",
    "TrustedDescriptionCacheError",
    "VerifiedDescriptionCache",
    "load_trusted_description_cache",
    "load_trusted_description_cache_from_descriptor",
    "load_trusted_description_cache_from_parent",
)
