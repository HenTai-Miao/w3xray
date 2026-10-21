"""Locate the still-open held stage across legal transaction names."""

from __future__ import annotations

from pathlib import Path

from .description_cache_publication_errors import (
    PublicationCommitContextError,
    merge_failures,
    merge_retained,
)
from .description_cache_publication_evidence import finalize_error_evidence
from .description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRecord,
    RetainedEvidenceReproof,
)
from .description_cache_publication_named_leaf import (
    reprove_retained,
    reprove_transient,
)
from .description_cache_publication_parent_identity import require_parent_identity
from .description_cache_publication_retention_names import RetainedCacheNames
from .description_cache_publication_stage import BoundDescriptionCacheStage
from .description_cache_publication_stage_location_scan import (
    _is_known_state,
    _known_records_match,
    _retained_match,
    _snapshot_as_transient,
    _snapshot_failures,
    _snapshot_locations,
    _state_transient,
)
from .description_cache_publication_stage_normalization import (
    capture_transient_record,
)


def locate_consumed_stage(
    bound: BoundDescriptionCacheStage,
    output: Path,
    names: RetainedCacheNames,
    *,
    known_retained: tuple[RetainedCacheRecord, ...] = (),
    known_transient: tuple[PublicationTransientRecord, ...] = (),
    prior_failures: tuple[Exception, ...] = (),
    later_retained: tuple[RetainedCacheRecord, ...] = (),
    later_transient: tuple[PublicationTransientRecord, ...] = (),
    detail: str | None = None,
) -> RetainedCacheRecord | None:
    """Return the unique stable location or surface complete current evidence."""
    expected_records = merge_retained(known_retained, later_retained)
    prior = reprove_retained(
        bound.parent_descriptor,
        bound.stage.parent,
        bound.parent_identity,
        expected_records,
    )
    retained = prior.retained
    transient_proof = reprove_transient(
        bound.parent_descriptor,
        bound.stage.parent,
        bound.parent_identity,
        (*known_transient, *later_transient, *prior.transient),
    )
    transient = tuple(
        current
        for current in transient_proof.transient
        if all(
            current.path != record.path or current.identity != record.identity
            for record in retained
        )
    )
    before = _snapshot_locations(bound, output, names)
    after = _snapshot_locations(bound, output, names)
    failures = merge_failures(prior_failures, prior.failures)
    failures = merge_failures(failures, transient_proof.failures)
    failures = merge_failures(failures, _snapshot_failures(before))
    failures = merge_failures(failures, _snapshot_failures(after))
    locations_changed = before != after
    matches = tuple(
        state
        for state in after
        if state.readable and state.identity == bound.stage_identity
    )
    foreign = tuple(
        _state_transient(bound, state)
        for state in after
        if (
            not state.readable
            or (
                state.identity is not None
                and state.identity != bound.stage_identity
                and not _is_known_state(state, retained)
            )
        )
    )
    matching_records = tuple(
        record for state in matches if (record := _retained_match(state)) is not None
    )
    held_record = _retained_match(matches[0]) if len(matches) == 1 else None
    clean = bool(
        detail is None
        and not locations_changed
        and prior.retained == expected_records
        and _known_records_match(after, retained)
        and len(matches) == 1
        and not transient
        and not foreign
        and not failures
    )
    if clean:
        try:
            require_parent_identity(
                bound.parent_descriptor,
                bound.stage.parent,
                bound.parent_identity,
            )
        except PublicationCommitContextError as parent_error:
            context_error = PublicationCommitContextError(
                "publication parent changed after final stage-location scan; "
                "NEEDS_CONTEXT",
                transient=_snapshot_as_transient(bound, after),
                failures=merge_failures(
                    failures,
                    (*parent_error.failures, parent_error),
                ),
            )
            raise context_error from parent_error
        return held_record

    output_held_identity = (
        bound.stage_identity
        if len(matches) == 1 and matches[0].path == output
        else None
    )
    output_probe = PublicationTransientRecord(
        bound.stage.parent,
        output.name,
        bound.parent_identity,
        after[0].identity,
        output_held_identity,
    )
    missing_held_evidence = (
        RetainedEvidenceReproof()
        if len(matches) == 1
        else capture_transient_record(
            bound.parent_descriptor,
            bound.stage,
            bound.parent_identity,
            bound.stage_identity,
        )
    )
    failures = merge_failures(failures, missing_held_evidence.failures)
    if locations_changed:
        reason = "stage-location names changed between complete scans"
    elif prior.retained != expected_records or not _known_records_match(
        after, retained
    ):
        reason = "known retained evidence changed during stage-location proof"
    elif len(matches) != 1:
        reason = "absent stage leaf does not uniquely locate the held stage"
    elif transient or foreign:
        reason = "stage-location set contains unrelated current evidence"
    else:
        reason = "stage-location proof followed an earlier failure"
    context_error = PublicationCommitContextError(
        (
            f"{reason}; NEEDS_CONTEXT"
            if detail is None
            else f"{detail}; {reason}; NEEDS_CONTEXT"
        ),
        merge_retained(retained, matching_records),
        tuple(
            dict.fromkeys(
                (
                    *transient,
                    *foreign,
                    output_probe,
                    *missing_held_evidence.transient,
                )
            )
        ),
        failures,
    )
    finalized = finalize_error_evidence(
        bound.parent_descriptor,
        bound.stage.parent,
        bound.parent_identity,
        context_error,
    )
    raise finalized


__all__ = ("locate_consumed_stage",)
