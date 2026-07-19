"""Exact text-table icon fields retain their object-browser images."""

from __future__ import annotations

import pytest

from w3xtool.object_candidates import (
    ObjectCandidate,
    ObjectFieldValue,
    ObjectSourceKind,
)
from w3xtool.object_pipeline import merge_object_candidates


@pytest.mark.parametrize("category", ("单位", "物品", "科技"))
def test_exact_art_from_text_table_becomes_display_icon(category: str) -> None:
    # Given: an optimized map stores one category's exact Art field in text data.
    candidate = ObjectCandidate(
        category=category,
        obj_id="I001",
        base_id="I001",
        is_custom=True,
        ext="txt",
        fields=(
            ObjectFieldValue(
                key="Art",
                label="图标",
                value=r"war3mapImported\BTNItem.blp",
                source="unknown/block_000001.txt",
                source_kind=ObjectSourceKind.TEXT_ANONYMOUS,
            ),
        ),
        refs=(),
    )

    # When: the candidate is materialized for the object browser.
    materialized = merge_object_candidates((candidate,), {})[0]

    # Then: the exact Art path is retained as the selected display icon.
    assert materialized.icon == r"war3mapImported\BTNItem.blp"
    assert materialized.icon_field_evidence is not None
    assert materialized.icon_field_evidence.key == "Art"
