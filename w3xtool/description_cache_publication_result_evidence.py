"""Final byte and namespace proof before publication returns success."""

from __future__ import annotations

from pathlib import Path

from .description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
    merge_failures,
)
from .description_cache_publication_evidence import (
    finalize_error_evidence,
    require_live_retained_evidence,
)
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_generation_evidence import (
    ExpectedPublishedGeneration,
    require_stable_generation_set,
)
from .description_cache_publication_models import (
    DescriptionCachePublicationProof,
    DescriptionCachePublicationResult,
)
from .description_cache_publication_named_leaf import capture_named_transient


def require_live_result_evidence(
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    output: Path,
    output_identity: DirectoryIdentity,
    proof: DescriptionCachePublicationProof,
    private_paths: tuple[Path, Path],
) -> DescriptionCachePublicationResult:
    """Revalidate the complete generation set and private namespace."""
    result = proof.result
    live = require_live_retained_evidence(
        parent_descriptor,
        parent,
        parent_identity,
        result.retained,
        parent_loss_evidence=capture_named_transient(
            parent_descriptor,
            parent,
            parent_identity,
            output,
        ),
    )
    expected_records = tuple(item.record for item in proof.retained_expectations)
    try:
        if expected_records != live:
            raise PublicationCommitContextError(
                "publication result has unmatched retained proof; NEEDS_CONTEXT"
            )
        require_stable_generation_set(
            parent_descriptor,
            parent,
            parent_identity,
            (
                ExpectedPublishedGeneration(
                    output,
                    output_identity,
                    result.active,
                ),
                *(
                    ExpectedPublishedGeneration(
                        expectation.record.path,
                        expectation.record.identity,
                        expectation.verified,
                    )
                    for expectation in proof.retained_expectations
                ),
            ),
            private_paths,
        )
    except DescriptionCachePublicationError as evidence_error:
        raise finalize_error_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            evidence_error,
            earlier_retained=live,
            parent_loss_evidence=capture_named_transient(
                parent_descriptor,
                parent,
                parent_identity,
                output,
            ),
        )
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK - result evidence boundary
        context_error = PublicationCommitContextError(
            "publication result revalidation raised an ordinary exception; "
            "NEEDS_CONTEXT",
            failures=(exc,),
        )
        finalized = finalize_error_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            context_error,
            earlier_retained=live,
            parent_loss_evidence=capture_named_transient(
                parent_descriptor,
                parent,
                parent_identity,
                output,
            ),
        )
        finalized.replace_failures(merge_failures(finalized.failures, (exc,)))
        raise finalized
    return result


__all__ = ("require_live_result_evidence",)
