"""Exact object-text identity and source-priority selection contracts."""

from __future__ import annotations

from tests.object_text_priority_fixture import (
    build_text_index,
    index_with_binary_conflict_and_slk_value,
    index_with_name_sources,
    text_field,
)
from w3xtool.client_object_data import ClientBaseObject
from w3xtool.description_cache import DescriptionCache, DescriptionCacheEntry
from w3xtool.object_candidates import ObjectSourceKind
from w3xtool.object_text_models import (
    ObjectTextState,
    TextSelectionReason,
    TextSourcePriority,
)


def test_text_strings_win_over_binary_and_slk_without_losing_originals() -> None:
    # Given / When: one name has three map-source variants.
    rows = index_with_name_sources().for_object("单位", "H001")

    # Then: Strings is current and every unique lower-priority row survives.
    current = tuple(row for row in rows if row.is_current)
    assert [(row.raw_value, row.source_priority) for row in current] == [
        ("地图文本名称", int(TextSourcePriority.MAP_TEXT_STRINGS))
    ]
    assert current[0].selection_reason is TextSelectionReason.HIGHEST_PRIORITY_VALUE
    assert {row.raw_value for row in rows if row.raw_value} == {
        "地图文本名称",
        "地图二进制名称",
        "地图SLK名称",
    }
    assert all(
        row.selection_reason is TextSelectionReason.LOWER_PRIORITY
        for row in rows
        if row.raw_value and not row.is_current
    )
    assert all(
        row.selection_reason is TextSelectionReason.NO_SOURCE
        for row in rows
        if not row.raw_value
    )


def test_only_same_field_level_and_priority_can_conflict() -> None:
    # Given / When: binary peers conflict above one older SLK value.
    rows = index_with_binary_conflict_and_slk_value().records

    # Then: only the exact binary identity/priority group is a conflict.
    conflicts = tuple(
        row for row in rows if row.state is ObjectTextState.SOURCE_CONFLICT
    )
    assert {row.raw_value for row in conflicts} == {"二进制甲", "二进制乙"}
    assert {row.source_priority for row in conflicts} == {
        int(TextSourcePriority.MAP_BINARY)
    }
    assert {row.selection_reason for row in conflicts} == {
        TextSelectionReason.SAME_PRIORITY_CONFLICT
    }
    slk = next(row for row in rows if row.raw_value == "SLK旧值")
    assert slk.conflict_group == ""
    assert not slk.is_current
    assert slk.selection_reason is TextSelectionReason.LOWER_PRIORITY


def test_highest_map_explicit_empty_blocks_every_lower_value() -> None:
    # Given: Strings clears a field above binary and SLK values.
    index = build_text_index(
        "物品",
        "I001",
        "ratf",
        (
            text_field(
                "utub",
                "提示工具 - 扩展的",
                "",
                "map.txt",
                ObjectSourceKind.TEXT_STRINGS,
            ),
            text_field(
                "utub",
                "提示工具 - 扩展的",
                "二进制",
                "map.w3t",
                ObjectSourceKind.BINARY,
            ),
            text_field(
                "utub", "提示工具 - 扩展的", "SLK", "ItemData.slk", ObjectSourceKind.SLK
            ),
        ),
    )

    # When / Then: the clear is current, non-placeholder, and lower rows remain evidence.
    rows = tuple(row for row in index.records if row.semantic_field == "ubertip")
    current = tuple(row for row in rows if row.is_current)
    assert len(current) == 1
    assert current[0].raw_value == ""
    assert current[0].state is ObjectTextState.MAP_EXPLICIT_EMPTY
    assert current[0].selection_reason is TextSelectionReason.EXPLICIT_EMPTY
    assert not current[0].placeholder
    assert {row.raw_value for row in rows} == {"", "二进制", "SLK"}


def test_fixed_nonempty_placeholder_falls_through_to_lower_map_source() -> None:
    # Given: binary has only an author-undefined placeholder above a usable SLK value.
    index = build_text_index(
        "物品",
        "I001",
        "ratf",
        (
            text_field(
                "utub", "提示工具 - 扩展的", "-", "map.w3t", ObjectSourceKind.BINARY
            ),
            text_field(
                "utub",
                "提示工具 - 扩展的",
                "SLK说明",
                "ItemData.slk",
                ObjectSourceKind.SLK,
            ),
        ),
    )

    # When / Then: the placeholder is skipped and the lower source becomes current.
    placeholder = next(row for row in index.records if row.raw_value == "-")
    current = next(row for row in index.records if row.is_current and row.raw_value)
    assert not placeholder.is_current
    assert placeholder.selection_reason is TextSelectionReason.PLACEHOLDER_SKIPPED
    assert (current.raw_value, current.source_priority) == (
        "SLK说明",
        int(TextSourcePriority.MAP_SLK),
    )


def test_function_text_beats_slk_and_anonymous_rows() -> None:
    # Given: function text is the highest of three otherwise equal identities.
    index = build_text_index(
        "物品",
        "I001",
        "ratf",
        (
            text_field(
                "utub",
                "提示工具 - 扩展的",
                "函数文本",
                "func.txt",
                ObjectSourceKind.TEXT_FUNC,
            ),
            text_field(
                "utub",
                "提示工具 - 扩展的",
                "SLK文本",
                "ItemData.slk",
                ObjectSourceKind.SLK,
            ),
            text_field(
                "utub",
                "提示工具 - 扩展的",
                "匿名文本",
                "anonymous:7",
                ObjectSourceKind.TEXT_ANONYMOUS,
            ),
        ),
    )

    # When / Then: exact priorities select function text and retain lower rows.
    rows = tuple(row for row in index.records if row.raw_value)
    assert [(row.raw_value, row.source_priority) for row in rows if row.is_current] == [
        ("函数文本", int(TextSourcePriority.MAP_FUNCTION_TEXT))
    ]
    assert {row.source_priority for row in rows} == {
        int(TextSourcePriority.MAP_FUNCTION_TEXT),
        int(TextSourcePriority.MAP_SLK),
        int(TextSourcePriority.MAP_ANONYMOUS),
    }


def test_anonymous_map_value_retains_client_and_cache_evidence() -> None:
    # Given: anonymous map, client, and cache evidence share one exact identity.
    client = ClientBaseObject(
        "ratf",
        "物品",
        (("说明", "客户端文本"),),
        (
            text_field(
                "utub",
                "提示工具 - 扩展的",
                "客户端文本",
                "ItemStrings.txt",
                ObjectSourceKind.TEXT_STRINGS,
            ),
        ),
    )
    cache = DescriptionCache.build(
        (
            DescriptionCacheEntry(
                "物品",
                "ratf",
                "扩展提示",
                None,
                "缓存文本",
                "缓存文本",
                "e" * 64,
                "a" * 64,
                "owned.tsv",
            ),
        ),
    )
    index = build_text_index(
        "物品",
        "I001",
        "ratf",
        (
            text_field(
                "utub",
                "提示工具 - 扩展的",
                "匿名文本",
                "anonymous:7",
                ObjectSourceKind.TEXT_ANONYMOUS,
            ),
        ),
        client_objects=(client,),
        cache=cache,
        client_text_available=True,
    )

    # When / Then: anonymous is current while all lower evidence remains lossless.
    rows = tuple(row for row in index.records if row.raw_value)
    assert {row.raw_value for row in rows} == {"匿名文本", "客户端文本", "缓存文本"}
    assert {(row.raw_value, row.source_priority) for row in rows} == {
        ("匿名文本", int(TextSourcePriority.MAP_ANONYMOUS)),
        ("客户端文本", int(TextSourcePriority.CLIENT)),
        ("缓存文本", int(TextSourcePriority.TRUSTED_CACHE)),
    }
    assert [row.raw_value for row in rows if row.is_current] == ["匿名文本"]
