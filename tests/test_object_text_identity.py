"""Exact semantic-field identity contracts for object text."""

from __future__ import annotations

from tests.object_text_priority_fixture import build_text_index, text_field
from w3xtool.description_cache import DescriptionCache, DescriptionCacheEntry
from w3xtool.object_candidates import ObjectSourceKind


def test_distinct_semantic_fields_with_one_role_do_not_conflict() -> None:
    # Given: revive short and long fields share a presentation role and priority.
    index = build_text_index(
        "单位",
        "H001",
        "Hpal",
        (
            text_field(
                "ReviveTip",
                "提示工具 - 复活",
                "短提示",
                "map.w3u",
                ObjectSourceKind.BINARY,
            ),
            text_field(
                "ReviveUbertip",
                "提示工具 - 复活 - 扩展的",
                "长提示",
                "map.w3u",
                ObjectSourceKind.BINARY,
            ),
        ),
    )

    # When / Then: the five-part identities remain independent current values.
    rows = tuple(
        row for row in index.records if row.role == "复活提示" and row.raw_value
    )
    assert {(row.semantic_field, row.raw_value) for row in rows} == {
        ("revivetip", "短提示"),
        ("reviveubertip", "长提示"),
    }
    assert all(row.is_current for row in rows)
    assert all(not row.conflict_group for row in rows)


def test_cache_role_cannot_guess_a_distinct_semantic_field() -> None:
    # Given: a role-only cache row and a placeholder in another field sharing that role.
    cache = DescriptionCache.build(
        (
            DescriptionCacheEntry(
                "单位",
                "Hpal",
                "复活提示",
                None,
                "缓存短提示",
                "缓存短提示",
                "e" * 64,
                "a" * 64,
                "owned.tsv",
            ),
        ),
    )
    index = build_text_index(
        "单位",
        "H001",
        "Hpal",
        (
            text_field(
                "ReviveUbertip",
                "提示工具 - 复活 - 扩展的",
                "-",
                "map.w3u",
                ObjectSourceKind.BINARY,
            ),
        ),
        cache=cache,
        client_text_available=True,
    )

    # When / Then: cache evidence stays on its canonical field and cannot fill the long field.
    cache_rows = tuple(
        row for row in index.records if row.source_kind == "可信描述缓存"
    )
    assert [(row.semantic_field, row.raw_value) for row in cache_rows] == [
        ("revivetip", "缓存短提示")
    ]
    long_rows = tuple(
        row for row in index.records if row.semantic_field == "reviveubertip"
    )
    assert not any(row.is_current for row in long_rows)
