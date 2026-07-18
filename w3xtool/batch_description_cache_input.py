"""One-time trusted-description cache selection for a batch parent."""

from __future__ import annotations

from pathlib import Path

from .batch_configuration import BatchConfigurationError, BatchOptions
from .description_cache_models import (
    EMPTY_DESCRIPTION_CACHE,
    NO_DESCRIPTION_CACHE_SHA256,
)
from .trusted_description_cache import (
    TrustedDescriptionCacheError,
    VerifiedDescriptionCache,
    load_trusted_description_cache,
)


def empty_verified_description_cache() -> VerifiedDescriptionCache:
    """Return the stable identity for an explicitly absent cache input."""
    return VerifiedDescriptionCache(
        EMPTY_DESCRIPTION_CACHE,
        NO_DESCRIPTION_CACHE_SHA256,
        NO_DESCRIPTION_CACHE_SHA256,
    )


def load_batch_description_cache(options: BatchOptions) -> VerifiedDescriptionCache:
    """Verify an explicit owned root once before any worker is created."""
    if options.description_cache_path is None:
        return empty_verified_description_cache()
    try:
        return load_trusted_description_cache(Path(options.description_cache_path))
    except TrustedDescriptionCacheError as exc:
        raise BatchConfigurationError(f"description cache is invalid: {exc}") from exc


__all__ = (
    "NO_DESCRIPTION_CACHE_SHA256",
    "empty_verified_description_cache",
    "load_batch_description_cache",
)
