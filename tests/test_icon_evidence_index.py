"""Immutable icon evidence index ordering tests."""

from __future__ import annotations

from dataclasses import replace

from w3xtool.extraction_ledger import BlockSource, BlockState
from w3xtool.icon_evidence_index import (
    IconEvidenceIndex,
    merge_icon_evidence_indexes,
)
from w3xtool.icon_evidence_models import (
    IconCandidateEvidence,
    IconCandidateKind,
    IconGapReason,
    IconResolutionLayer,
    ResolvedIconEvidence,
    UnresolvedIconEvidence,
)
from w3xtool.icon_resources import AnonymousIconResource, IconObjectReference

_DIGEST = "a" * 64
_PATH = r"ReplaceableTextures\CommandButtons\BTNHero.blp"


def test_reference_sort_is_independent_of_equal_primary_key_input_order() -> None:
    # Given
    row = UnresolvedIconEvidence(
        IconObjectReference(
            "技能",
            "A001",
            "当前对象",
            map_sha256=_DIGEST,
            field_label="图标 - 普通",
            requested_path=_PATH,
            normalized_path=_PATH,
        ),
        IconGapReason.NAMED_RESOURCE_MISSING,
        (),
        (),
    )
    first = replace(row, reference=replace(row.reference, field_label="A"))
    second = replace(row, reference=replace(row.reference, field_label="Z"))

    # When
    forward = IconEvidenceIndex.build(unresolved=(second, first)).unresolved
    reverse = IconEvidenceIndex.build(unresolved=(first, second)).unresolved

    # Then
    assert forward == reverse == (first, second)


def test_candidate_sort_is_independent_of_anonymous_map_input_order() -> None:
    # Given
    first = _candidate("a" * 64)
    second = _candidate("b" * 64)

    # When
    forward = IconEvidenceIndex.build(candidates=(second, first)).candidates
    reverse = IconEvidenceIndex.build(candidates=(first, second)).candidates

    # Then
    assert forward == reverse == (first, second)


def test_resolved_sort_is_independent_of_case_only_source_path_input_order() -> None:
    # Given
    upper = _resolved(source_path="Map.w3x", payload=b"BLP1same")
    lower = replace(upper, source_path="map.w3x")

    # When
    forward = IconEvidenceIndex.build(resolved=(lower, upper)).resolved
    reverse = IconEvidenceIndex.build(resolved=(upper, lower)).resolved

    # Then
    assert forward == reverse == (upper, lower)


def test_resolved_sort_is_independent_of_equal_metadata_payload_input_order() -> None:
    # Given
    first = _resolved(source_path="map.w3x", payload=b"BLP1a")
    second = replace(first, payload=b"BLP1z")

    # When
    forward = IconEvidenceIndex.build(resolved=(second, first)).resolved
    reverse = IconEvidenceIndex.build(resolved=(first, second)).resolved

    # Then
    assert forward == reverse == (first, second)


def test_anonymous_sort_is_independent_of_equal_metadata_payload_input_order() -> None:
    # Given
    first = AnonymousIconResource(
        7,
        b"BLP1a",
        "c" * 64,
        "block_000007_cccccccc",
        "map.w3x",
        BlockSource.ARCHIVE_RECOVERED,
        BlockState.DECODED,
    )
    second = replace(first, payload=b"BLP1z")

    # When
    forward = IconEvidenceIndex.build(anonymous=(second, first)).anonymous
    reverse = IconEvidenceIndex.build(anonymous=(first, second)).anonymous

    # Then
    assert forward == reverse == (first, second)


def test_merge_never_preserves_an_adopted_candidate() -> None:
    # Given
    source = IconEvidenceIndex.build(candidates=(_candidate("a" * 64),))
    object.__setattr__(source.candidates[0], "adopted", True)

    # When
    merged = merge_icon_evidence_indexes((source,))

    # Then
    assert merged.candidates[0].adopted is False


def _resolved(*, source_path: str, payload: bytes) -> ResolvedIconEvidence:
    return ResolvedIconEvidence(
        IconObjectReference(
            "技能",
            "A001",
            "当前对象",
            map_sha256=_DIGEST,
            requested_path=_PATH,
            normalized_path=_PATH,
        ),
        _PATH,
        source_path,
        payload,
        "b" * 64,
        IconResolutionLayer.CURRENT_MAP,
        (),
    )


def _candidate(anonymous_map_sha256: str) -> IconCandidateEvidence:
    return IconCandidateEvidence(
        IconCandidateKind.ANONYMOUS_HASH_MATCH,
        _DIGEST,
        _PATH,
        anonymous_map_sha256,
        7,
        "c" * 64,
        _PATH,
        "d" * 64,
    )
