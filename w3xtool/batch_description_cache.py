"""Build and safely publish the trusted cache used by one batch run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, override

from .description_cache import (
    EMPTY_DESCRIPTION_CACHE,
    DescriptionCache,
    build_description_cache_from_batch,
    format_description_cache_tsv,
    load_description_cache_text,
)
from .batch_global_publication import load_current_generation
from .safe_output import write_text_safely
from .safe_output_models import SafeWriteStatus

DESCRIPTION_CACHE_REPORT: Final = "可信描述缓存.tsv"


@dataclass(frozen=True, slots=True)
class BatchDescriptionCacheError(OSError):
    """Report a failed or unsafe cache publication."""

    path: str
    detail: str

    @override
    def __str__(self) -> str:
        return f"cannot publish {self.path}: {self.detail}"


def build_and_publish_description_cache(output_root: str) -> DescriptionCache:
    """Freeze trusted owned evidence before any source map is processed."""
    root = Path(output_root)
    generation = load_current_generation(root)
    previous = (
        EMPTY_DESCRIPTION_CACHE
        if generation is None
        else load_description_cache_text(
            generation.cache_text,
            str(generation.directory / DESCRIPTION_CACHE_REPORT),
        )
    )
    cache = build_description_cache_from_batch(root, previous)
    result = write_text_safely(
        output_root,
        DESCRIPTION_CACHE_REPORT,
        format_description_cache_tsv(cache),
    )
    if result.status is not SafeWriteStatus.WRITTEN:
        raise BatchDescriptionCacheError(
            DESCRIPTION_CACHE_REPORT,
            result.error or result.status.value,
        )
    return cache
