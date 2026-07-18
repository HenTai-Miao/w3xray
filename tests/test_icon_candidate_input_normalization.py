"""Candidate input normalization and exclusion contracts."""

from __future__ import annotations

import pytest

from w3xtool.batch_global_evidence_models import (
    GlobalEvidenceIndex,
    GlobalIconGap,
    GlobalResolvedIcon,
)
from w3xtool.icon_candidate_bindings import build_icon_candidate_bindings
from w3xtool.icon_evidence_models import IconGapReason, IconResolutionLayer
from w3xtool.icon_resources import IconObjectReference


@pytest.mark.parametrize(
    ("gap_digest", "resolved_digest", "path", "layer", "duplicate"),
    (
        ("a" * 64, "b" * 64, r"Custom\BTN.blp", IconResolutionLayer.CLIENT, False),
        (
            "a" * 64,
            "b" * 64,
            r"Custom\BTN.blp",
            IconResolutionLayer.SAME_MAP_HISTORY,
            False,
        ),
        (
            "a" * 64,
            "b" * 64,
            r"Custom\BTN.blp",
            IconResolutionLayer.TRUSTED_CACHE,
            False,
        ),
        ("a" * 64, "a" * 64, r"Custom\BTN.blp", IconResolutionLayer.CURRENT_MAP, False),
        ("", "b" * 64, r"Custom\BTN.blp", IconResolutionLayer.CURRENT_MAP, False),
        ("a" * 64, "", r"Custom\BTN.blp", IconResolutionLayer.CURRENT_MAP, False),
        ("a" * 64, "b" * 64, r"Custom\BTN.blp", IconResolutionLayer.CURRENT_MAP, True),
        ("a" * 64, "b" * 64, r"Other\BTN.blp", IconResolutionLayer.CURRENT_MAP, False),
        (
            "a" * 64,
            "b" * 64,
            r"More\Custom\BTN.blp",
            IconResolutionLayer.CURRENT_MAP,
            False,
        ),
    ),
    ids=(
        "client",
        "history",
        "cache",
        "self",
        "empty-gap",
        "empty-resolved",
        "duplicate",
        "basename",
        "suffix",
    ),
)
def test_candidate_input_exclusion_matrix(
    gap_digest: str,
    resolved_digest: str,
    path: str,
    layer: IconResolutionLayer,
    duplicate: bool,
) -> None:
    gap = _gap(r"Custom\BTN.blp", gap_digest)
    resolved = _resolved(path, resolved_digest, layer)
    rows = (resolved, resolved) if duplicate else (resolved,)

    candidates = build_icon_candidate_bindings(
        GlobalEvidenceIndex.build((gap,), rows, (), ())
    )

    if duplicate:
        assert len(candidates) == len(set(candidates)) == 1
    else:
        assert candidates == ()


@pytest.mark.parametrize(
    ("gap_path", "resolved_path"),
    (
        (
            r"replaceabletextures\CommandButtons\BTNBlade.blp",
            r"ReplaceableTextures\CommandButtons\BTNBlade.blp",
        ),
        (
            r"ReplaceableTextures\CommandButtons\BTNBlade.blp",
            r"replaceabletextures\CommandButtons\BTNBlade.blp",
        ),
    ),
    ids=("gap", "resolved"),
)
def test_candidate_builder_rejects_noncanonical_paths_on_both_sides(
    gap_path: str,
    resolved_path: str,
) -> None:
    evidence = GlobalEvidenceIndex.build(
        (_gap(gap_path, "a" * 64),),
        (_resolved(resolved_path, "b" * 64, IconResolutionLayer.CURRENT_MAP),),
        (),
        (),
    )

    assert build_icon_candidate_bindings(evidence) == ()


def _gap(path: str, digest: str) -> GlobalIconGap:
    return GlobalIconGap(
        "/maps/a.w3x",
        digest,
        "root",
        path,
        IconGapReason.NAMED_RESOURCE_MISSING,
        (),
        ("物品",),
        ("I001",),
        (IconObjectReference("物品", "I001", "测试", map_path="/maps/a.w3x"),),
        1,
    )


def _resolved(
    path: str,
    digest: str,
    layer: IconResolutionLayer,
) -> GlobalResolvedIcon:
    return GlobalResolvedIcon(
        "/maps/b.w3x", digest, path, layer, "c" * 64, "/maps/b.w3x"
    )
