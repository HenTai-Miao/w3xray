"""Icon-gap projections stay exact and non-adopting."""

from w3xtool.icon_evidence_query import (
    IconGapFilter,
    IconGapViewRow,
    filter_icon_gap_rows,
)


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
