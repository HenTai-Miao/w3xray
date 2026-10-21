"""Build all five owned payloads through one held stage descriptor."""

from __future__ import annotations

from collections.abc import Sequence
import hashlib
from pathlib import Path

from .description_cache_migration_exports import format_migration_payloads
from .description_cache_migration_models import (
    DescriptionCacheRejection,
    ProvenDescriptionCandidate,
)
from .description_cache_owned_schema import (
    TRUSTED_DESCRIPTION_CACHE_MANIFEST,
    TRUSTED_DESCRIPTION_CACHE_MARKER,
    TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY,
    TRUSTED_DESCRIPTION_CACHE_SCHEMA,
    TrustedCacheArtifact,
    TrustedCacheManifest,
    format_trusted_cache_manifest,
    format_trusted_cache_marker,
    trusted_content_sha256,
)
from .description_cache_publication_stage_io import write_stage_text
from .durable_io import sync_directory_descriptor
from .trusted_description_cache_models import TrustedCacheLeafProof


def build_description_cache_stage(
    source_root: Path,
    stage_descriptor: int,
    display_root: Path,
    accepted: Sequence[ProvenDescriptionCandidate],
    rejections: Sequence[DescriptionCacheRejection],
) -> tuple[TrustedCacheLeafProof, ...]:
    """Materialize, write, synchronize, and return all leaf proofs."""
    payloads = format_migration_payloads(accepted, rejections)
    artifacts = tuple(
        sorted(
            (
                TrustedCacheArtifact(
                    name,
                    len(text.encode("utf-8")),
                    hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
                for name, text in payloads.items()
            ),
            key=lambda item: item.name.casefold(),
        )
    )
    manifest = TrustedCacheManifest(
        TRUSTED_DESCRIPTION_CACHE_SCHEMA,
        str(source_root),
        artifacts,
        trusted_content_sha256(artifacts),
    )
    manifest_text = format_trusted_cache_manifest(manifest)
    texts = {
        **payloads,
        TRUSTED_DESCRIPTION_CACHE_MANIFEST: manifest_text,
        TRUSTED_DESCRIPTION_CACHE_MARKER: format_trusted_cache_marker(
            hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()
        ),
    }
    proofs = tuple(
        write_stage_text(stage_descriptor, display_root, name, texts[name])
        for name in TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY
    )
    sync_directory_descriptor(stage_descriptor)
    return proofs


__all__ = ("build_description_cache_stage",)
