"""Closed candidate rules never mutate authoritative icon gaps."""

from __future__ import annotations

import pytest

from w3xtool.batch_global_evidence_models import (
    GlobalAnonymousIcon,
    GlobalEvidenceIndex,
    GlobalEvidenceError,
    GlobalIconGap,
    GlobalResolvedIcon,
)
from w3xtool.icon_candidate_bindings import build_icon_candidate_bindings
from w3xtool.batch_global_evidence_reports import (
    format_icon_candidates_tsv,
    parse_icon_candidates_tsv,
)
from w3xtool.icon_evidence_models import (
    IconCandidateKind,
    IconGapReason,
    IconResolutionLayer,
)
from w3xtool.icon_resources import IconObjectReference


def test_exact_path_in_another_map_is_only_a_non_adopted_candidate() -> None:
    # Given
    gap = GlobalIconGap(
        map_path="/maps/a.w3x",
        map_sha256="a" * 64,
        map_scope="root",
        normalized_path=r"Custom\BTNBlade.blp",
        reason=IconGapReason.NAMED_RESOURCE_MISSING,
        diagnostics=(),
        object_categories=("物品",),
        rawcodes=("I001",),
        references=(
            IconObjectReference(
                category="物品",
                object_id="I001",
                object_name="测试装备",
                base_id="ratf",
                map_path="/maps/a.w3x",
                map_sha256="a" * 64,
                map_scope="root",
                field_key="iico",
                field_label="图标",
                field_type="icon",
                field_source="war3map.w3t",
                wts_source="",
            ),
        ),
        reference_count=1,
    )
    resolved = GlobalResolvedIcon(
        map_path="/maps/b.w3x",
        map_sha256="b" * 64,
        normalized_path=r"Custom\BTNBlade.blp",
        layer=IconResolutionLayer.CURRENT_MAP,
        content_sha256="c" * 64,
        source_path="/maps/b.w3x",
    )
    evidence = GlobalEvidenceIndex.build((gap,), (resolved,), (), ())

    # When
    candidates = build_icon_candidate_bindings(evidence)

    # Then
    assert len(candidates) == 1
    assert candidates[0].kind is IconCandidateKind.EXACT_OTHER_MAP_PATH
    assert candidates[0].adopted is False
    assert evidence.gaps == (gap,)


def test_anonymous_hash_match_has_no_unproved_requested_path() -> None:
    # Given
    resolved = GlobalResolvedIcon(
        "/maps/b.w3x",
        "b" * 64,
        r"Custom\BTNBlade.blp",
        IconResolutionLayer.CURRENT_MAP,
        "c" * 64,
        "/maps/b.w3x",
    )
    anonymous = GlobalAnonymousIcon(
        "/maps/a.w3x",
        "a" * 64,
        17,
        "c" * 64,
        "/maps/a.w3x#block17",
    )
    evidence = GlobalEvidenceIndex.build((), (resolved,), (anonymous,), ())

    # When
    candidate = build_icon_candidate_bindings(evidence)[0]

    # Then
    assert candidate.kind is IconCandidateKind.ANONYMOUS_HASH_MATCH
    assert candidate.requested_path == ""
    assert candidate.anonymous_block_index == 17
    assert candidate.adopted is False


def test_candidate_report_round_trips_without_adopting_suggestions() -> None:
    # Given
    resolved = GlobalResolvedIcon(
        "/maps/b.w3x",
        "b" * 64,
        r"Custom\BTNBlade.blp",
        IconResolutionLayer.CURRENT_MAP,
        "c" * 64,
        "/maps/b.w3x",
    )
    anonymous = GlobalAnonymousIcon(
        "/maps/a.w3x",
        "a" * 64,
        17,
        "c" * 64,
        "/maps/a.w3x#block17",
    )
    base = GlobalEvidenceIndex.build((), (resolved,), (anonymous,), ())
    evidence = GlobalEvidenceIndex.build(
        (),
        (resolved,),
        (anonymous,),
        build_icon_candidate_bindings(base),
    )

    # When
    restored = parse_icon_candidates_tsv(format_icon_candidates_tsv(evidence))

    # Then
    assert restored == evidence.candidates
    assert all(candidate.adopted is False for candidate in restored)


def test_candidate_report_rejects_an_adopted_suggestion() -> None:
    # Given
    candidate = build_icon_candidate_bindings(
        GlobalEvidenceIndex.build(
            (),
            (
                GlobalResolvedIcon(
                    "/maps/b.w3x",
                    "b" * 64,
                    r"Custom\BTNBlade.blp",
                    IconResolutionLayer.CURRENT_MAP,
                    "c" * 64,
                    "/maps/b.w3x",
                ),
            ),
            (GlobalAnonymousIcon("/maps/a.w3x", "a" * 64, 17, "c" * 64, "a#17"),),
            (),
        )
    )
    text = format_icon_candidates_tsv(
        GlobalEvidenceIndex.build((), (), (), candidate)
    ).replace("\t否\n", "\t是\n")

    # When / Then
    with pytest.raises(GlobalEvidenceError, match="adopted"):
        parse_icon_candidates_tsv(text)


def _reference() -> IconObjectReference:
    return IconObjectReference(
        "物品",
        "I001",
        "测试装备",
        map_path="/maps/a.w3x",
        map_sha256="a" * 64,
        map_scope="root",
    )
