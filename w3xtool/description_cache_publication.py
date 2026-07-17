"""Atomic non-destructive publication for trusted description evidence."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

from .atomic_rename import (
    rename_exchange,
    rename_noreplace,
    require_atomic_rename_support,
)
from .description_cache_migration_models import (
    DescriptionCacheRejection,
    ProvenDescriptionCandidate,
)
from .description_cache_publication_build import build_description_cache_stage
from .description_cache_publication_errors import (
    DescriptionCacheConcurrentDestinationError,
    DescriptionCachePublicationError,
    PublicationCommitContextError,
    merge_retained,
)
from .description_cache_publication_failure import _raise_after_private_finalization
from .description_cache_publication_models import (
    DescriptionCachePublicationProof,
    DescriptionCachePublicationResult,
    RetainedCacheRecord,
)
from .description_cache_publication_result_evidence import (
    require_live_result_evidence,
)
from .description_cache_publication_retention_names import RetainedCacheNames
from .description_cache_publication_stage import (
    BoundDescriptionCacheStage,
    create_stage_and_capture,
)
from .description_cache_publication_stage_finalization import (
    finalize_private_artifacts,
)
from .description_cache_publication_stage_io import require_stage_io_support
from .description_cache_publication_transaction import publish_valid_stage
from .durable_io import sync_directory_descriptor
from .trusted_description_cache import (
    TrustedDescriptionCacheError,
    load_trusted_description_cache_from_descriptor,
    load_trusted_description_cache_from_parent,
)
from .trusted_description_cache_models import (
    VerifiedDescriptionCache,
    VerifiedDescriptionCacheGeneration,
)


def publish_description_cache(
    source_root: Path,
    output: Path,
    accepted: Sequence[ProvenDescriptionCandidate],
    rejections: Sequence[DescriptionCacheRejection],
) -> DescriptionCachePublicationResult:
    """Stage, self-validate, publish, and report every retained generation."""
    require_atomic_rename_support()
    require_stage_io_support()
    identifier = uuid4().hex
    names = RetainedCacheNames(output.parent, identifier)
    stage = output.parent / f".w3xray-description-cache-stage-{identifier}"
    backup = output.parent / f".w3xray-description-cache-backup-{identifier}"
    with create_stage_and_capture(
        stage,
        output,
        names,
        _rename_noreplace,
        _sync_parent,
    ) as bound:
        published_records: tuple[RetainedCacheRecord, ...] = ()
        try:
            leaf_proofs = build_description_cache_stage(
                source_root,
                bound.stage_descriptor,
                bound.stage,
                accepted,
                rejections,
            )
            generation = load_trusted_description_cache_from_descriptor(
                bound.stage_descriptor,
                bound.stage,
                leaf_proofs,
            )
            proof = _publish_valid_stage(
                bound,
                output,
                backup,
                names,
                generation,
            )
            published_records = proof.result.retained
            private_records = finalize_private_artifacts(
                bound,
                backup,
                output,
                names,
                _rename_noreplace,
                _sync_parent,
                published_records,
            )
            if private_records:
                raise PublicationCommitContextError(
                    "successful publication required private evidence normalization; "
                    "NEEDS_CONTEXT",
                    merge_retained(published_records, private_records),
                )
            result = require_live_result_evidence(
                bound.parent_descriptor,
                bound.stage.parent,
                bound.parent_identity,
                output,
                bound.stage_identity,
                proof,
                (bound.stage, backup),
            )
            bound.close_ledger.remember(result.retained, ())
            return result
        except Exception as exc:  # noqa: BROAD_EXCEPT_OK - transaction evidence boundary
            _raise_after_private_finalization(
                bound,
                backup,
                names,
                output,
                published_records,
                exc,
                _rename_noreplace,
                _sync_parent,
            )


def _require_valid_at(
    parent_descriptor: int,
    root: Path,
) -> VerifiedDescriptionCache:
    try:
        return load_trusted_description_cache_from_parent(
            parent_descriptor,
            root.name,
            root,
        )
    except TrustedDescriptionCacheError as exc:
        raise DescriptionCachePublicationError(
            f"owned cache is not valid: {exc}"
        ) from exc


def _publish_valid_stage(
    bound: BoundDescriptionCacheStage,
    output: Path,
    backup: Path,
    names: RetainedCacheNames,
    generation: VerifiedDescriptionCacheGeneration,
) -> DescriptionCachePublicationProof:
    return publish_valid_stage(
        bound.parent_descriptor,
        bound.stage_descriptor,
        bound.stage,
        bound.stage_identity,
        generation,
        output,
        backup,
        names,
        bound.parent_identity,
        _rename_noreplace,
        _rename_exchange,
        _require_valid_at,
        _sync_parent,
    )


def _rename_noreplace(
    parent_descriptor: int,
    source_name: str,
    destination_name: str,
) -> None:
    rename_noreplace(
        parent_descriptor,
        source_name,
        parent_descriptor,
        destination_name,
    )


def _rename_exchange(
    parent_descriptor: int,
    source_name: str,
    destination_name: str,
) -> None:
    rename_exchange(
        parent_descriptor,
        source_name,
        parent_descriptor,
        destination_name,
    )


def _sync_parent(parent_descriptor: int) -> None:
    sync_directory_descriptor(parent_descriptor)


__all__ = (
    "DescriptionCacheConcurrentDestinationError",
    "DescriptionCachePublicationError",
    "publish_description_cache",
)
