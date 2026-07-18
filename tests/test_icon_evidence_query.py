"""Icon-gap projections stay exact and non-adopting."""

from w3xtool.icon_evidence_query import (
    IconGapFilter,
    IconGapViewRow,
    filter_icon_gap_rows,
    global_icon_gap_rows,
)
from w3xtool.batch_global_evidence_models import GlobalEvidenceIndex, GlobalIconGap
from w3xtool.icon_evidence_models import IconGapReason
from w3xtool.icon_resources import IconObjectReference


def test_icon_gap_filter_matches_reason_category_rawcode_and_path() -> None:
    # Given
    rows = (
        IconGapViewRow(
            "gap:a",
            "/maps/a.w3x",
            "a" * 64,
            "historical_client_miss",
            "物品",
            "I001",
            r"Custom\BTNBlade.blp",
            "存在原始块",
            2,
            False,
            False,
            ("物品", "I001"),
            "完整字段证据",
        ),
    )
    criteria = IconGapFilter(
        "BTNBlade I001", "historical_client_miss", "物品", "存在原始块", False
    )
    # When
    visible = filter_icon_gap_rows(rows, criteria)
    # Then
    assert visible == rows


def test_candidate_filter_never_changes_gap_rows_or_adoption() -> None:
    # Given
    candidate = IconGapViewRow(
        "candidate:a",
        "/maps/a.w3x",
        "a" * 64,
        "exact_other_map_path",
        "",
        "",
        r"Custom\BTNBlade.blp",
        "",
        0,
        True,
        False,
        None,
        "候选未采用",
    )
    # When
    shown = filter_icon_gap_rows(
        (candidate,), IconGapFilter("", "全部", "全部", "全部", True)
    )
    # Then
    assert shown == (candidate,)
    assert shown[0].adopted is False


def test_global_navigation_identity_requires_the_exact_current_map_identity() -> None:
    # Given
    first = _global_gap("/maps/a.w3x", "a" * 64)
    second = _global_gap("/maps/b.w3x", "b" * 64)
    index = GlobalEvidenceIndex.build((first, second), (), (), ())

    # When
    rows = global_icon_gap_rows(index, ("/maps/a.w3x", "a" * 64))

    # Then
    assert rows[0].object_identity == ("物品", "I001")
    assert rows[1].object_identity is None


def _global_gap(path: str, digest: str) -> GlobalIconGap:
    reference = IconObjectReference(
        "物品",
        "I001",
        "同名 Rawcode",
        map_path=path,
        map_sha256=digest,
        normalized_path=r"Custom\BTNBlade.blp",
    )
    return GlobalIconGap(
        path,
        digest,
        "map",
        reference.normalized_path,
        IconGapReason.NAMED_RESOURCE_MISSING,
        (),
        ("物品",),
        ("I001",),
        (reference,),
        1,
    )
