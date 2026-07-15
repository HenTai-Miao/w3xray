"""Picklable snapshot of one immutable map execution request."""

from __future__ import annotations

from dataclasses import dataclass

from .batch_configuration import BatchOptions
from .batch_models import SourceFingerprint
from .client_object_data import ClientBaseObject
from .description_cache_models import DescriptionCache, DescriptionCacheEntry
from .load_context import MapLoadContext
from .trigger_schema import TriggerSchema


@dataclass(frozen=True, slots=True)
class MapExecutionRequest:
    """Spawn-safe fields needed to reconstruct a map load context."""

    index: int
    fingerprint: SourceFingerprint
    options: BatchOptions
    external_names: tuple[str, ...]
    trigger_schema: TriggerSchema | None
    author_bundle_path: str | None
    client_base_objects: tuple[ClientBaseObject, ...]
    compat_bundle_path: str | None
    client_text_available: bool
    cache_entries: tuple[DescriptionCacheEntry, ...]
    cache_diagnostics: tuple[str, ...]

    def context(self) -> MapLoadContext:
        """Rebuild mapping-backed cache state inside the child process."""
        return MapLoadContext(
            external_names=self.external_names,
            trigger_schema=self.trigger_schema,
            author_bundle_path=self.author_bundle_path,
            client_base_objects=self.client_base_objects,
            compat_bundle_path=self.compat_bundle_path,
            client_text_available=self.client_text_available,
            description_cache=DescriptionCache.build(
                self.cache_entries,
                self.cache_diagnostics,
            ),
        )


def build_execution_request(
    index: int,
    fingerprint: SourceFingerprint,
    options: BatchOptions,
    context: MapLoadContext,
) -> MapExecutionRequest:
    """Remove non-picklable mapping proxies from an immutable load context."""
    cache = context.description_cache
    return MapExecutionRequest(
        index,
        fingerprint,
        options,
        context.external_names,
        context.trigger_schema,
        context.author_bundle_path,
        context.client_base_objects,
        context.compat_bundle_path,
        context.client_text_available,
        cache.entries,
        cache.diagnostics,
    )


__all__ = ("MapExecutionRequest", "build_execution_request")
