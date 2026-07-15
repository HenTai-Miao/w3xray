"""Complete object-text resolution and precedence contracts."""

from __future__ import annotations

from w3xtool.client_object_data import ClientBaseObject
from w3xtool.description_cache import DescriptionCache, DescriptionCacheEntry
from w3xtool.map_data import GameObject
from w3xtool.object_candidates import (
    ObjectCandidate,
    ObjectFieldValue,
    ObjectSourceKind,
)
from w3xtool.object_text_index import build_object_text_index
from w3xtool.object_text_models import ObjectTextRecord, ObjectTextState


def test_resolution_preserves_all_roles_levels_long_values_and_named_conflicts() -> (
    None
):
    # Given: one ability has every special role and two conflicting level-two descriptions.
    long_raw = "  |cffffcc00" + ('全文\t带引号"\r\n' * 500) + "|r  "
    fields = (
        _field("aret", "提示工具 - 学习", "学习"),
        _field("arut:2", "提示工具 - 学习 - 扩展的 (等级2)", long_raw),
        _field("aut1:2", "提示工具 - 关闭 (等级2)", "关闭"),
        _field("auu1:2", "提示工具 - 关闭 - 扩展的 (等级2)", "关闭全文"),
    )
    candidates = (
        _candidate("技能", "A001", "AHbz", fields),
        _candidate(
            "技能",
            "A001",
            "AHbz",
            (_field("arut:2", "提示工具 - 学习 - 扩展的 (等级2)", "冲突值"),),
        ),
    )

    # When: source evidence is resolved.
    index = build_object_text_index(
        (_object("技能", "A001", "AHbz"),),
        candidates,
        (),
        DescriptionCache.build(()),
        client_text_available=False,
    )

    # Then: all roles/levels survive and both top-tier variants are explicit conflicts.
    rows = index.for_object("技能", "A001")
    assert {row.role for row in rows} >= {
        "学习提示",
        "学习扩展提示",
        "关闭提示",
        "关闭扩展提示",
    }
    conflicts = tuple(
        row
        for row in rows
        if row.role == "学习扩展提示" and row.level == 2 and not row.placeholder
    )
    assert {row.raw_value for row in conflicts} == {long_raw, "冲突值"}
    assert {row.level for row in conflicts} == {2}
    assert {row.state for row in conflicts} == {ObjectTextState.SOURCE_CONFLICT}
    assert len({row.conflict_group for row in conflicts}) == 1
    long_row = next(row for row in conflicts if row.raw_value == long_raw)
    assert long_row.readable_value == "  " + ('全文\t带引号"\r\n' * 500) + "  "


def test_named_placeholder_allows_anonymous_fill_but_explicit_empty_blocks_all_fills() -> (
    None
):
    # Given: named map fields contain a placeholder and an explicit clear.
    named = _candidate(
        "物品",
        "I001",
        "ratf",
        (
            _field("utip", "提示工具 - 基础", "-"),
            _field("utub", "提示工具 - 扩展的", ""),
        ),
    )
    anonymous = _candidate(
        "物品",
        "I001",
        "I001",
        (
            ObjectFieldValue(
                "Tip",
                "提示工具 - 基础",
                "匿名提示",
                "anonymous:block:000007",
                ObjectSourceKind.TEXT_ANONYMOUS,
            ),
            ObjectFieldValue(
                "Ubertip",
                "提示工具 - 扩展的",
                "匿名说明",
                "anonymous:block:000007",
                ObjectSourceKind.TEXT_ANONYMOUS,
            ),
        ),
    )
    client = _client_item("客户端提示", "客户端说明")
    cache = _cache("缓存提示", "缓存说明")

    # When: all four tiers are resolved.
    rows = build_object_text_index(
        (_object("物品", "I001", "ratf"),),
        (anonymous, named),
        (client,),
        cache,
        client_text_available=True,
    ).for_object("物品", "I001")

    # Then: anonymous fills the placeholder while named empty prevents every lower description.
    base = tuple(row for row in rows if row.role == "基础提示")
    assert any(row.raw_value == "-" and row.placeholder for row in base)
    assert any(
        row.raw_value == "匿名提示"
        and row.state is ObjectTextState.MAP_VALUE
        and row.source_kind == "地图匿名文本块"
        for row in base
    )
    extended = tuple(row for row in rows if row.role == "扩展提示")
    assert len(extended) == 1
    assert (extended[0].raw_value, extended[0].state) == (
        "",
        ObjectTextState.MAP_EXPLICIT_EMPTY,
    )


def test_client_cache_undefined_and_unavailable_states_are_distinct() -> None:
    # Given: four items respectively need client, cache, a present source miss, and an absent source.
    objects = tuple(
        _object("物品", object_id, base_id)
        for object_id, base_id in (
            ("I001", "ratf"),
            ("I002", "rde1"),
            ("I003", "rde2"),
            ("I004", "rde3"),
        )
    )
    client = _client_item("客户端提示", "客户端说明")
    cache = DescriptionCache.build(
        (
            DescriptionCacheEntry(
                "物品",
                "rde1",
                "扩展提示",
                None,
                "缓存说明",
                "缓存说明",
                "f" * 64,
                "a" * 64,
                "owned.tsv",
            ),
        ),
    )

    # When: client availability is known for the first three objects.
    available_index = build_object_text_index(
        objects[:3],
        (),
        (client,),
        cache,
        client_text_available=True,
    )
    unavailable_index = build_object_text_index(
        (objects[3],),
        (),
        (),
        DescriptionCache.build(()),
        client_text_available=False,
    )

    # Then: each lower-tier outcome has its exact state.
    assert (
        _selected(available_index.for_object("物品", "I001"), "扩展提示").state
        is ObjectTextState.CLIENT_FILL
    )
    assert (
        _selected(available_index.for_object("物品", "I002"), "扩展提示").state
        is ObjectTextState.CACHE_FILL
    )
    assert (
        _selected(available_index.for_object("物品", "I003"), "扩展提示").state
        is ObjectTextState.AUTHOR_UNDEFINED
    )
    assert (
        _selected(unavailable_index.for_object("物品", "I004"), "扩展提示").state
        is ObjectTextState.SOURCE_UNAVAILABLE
    )


def _selected(
    rows: tuple[ObjectTextRecord, ...],
    role: str,
) -> ObjectTextRecord:
    return next(row for row in rows if row.role == role and not row.placeholder)


def _object(category: str, object_id: str, base_id: str) -> GameObject:
    return GameObject(
        category=category,
        ext="w3t" if category == "物品" else "w3a",
        obj_id=object_id,
        base_id=base_id,
        name=object_id,
        is_custom=True,
    )


def _field(key: str, label: str, value: str) -> ObjectFieldValue:
    return ObjectFieldValue(key, label, value, "war3map.w3a", ObjectSourceKind.BINARY)


def _candidate(
    category: str,
    object_id: str,
    base_id: str,
    fields: tuple[ObjectFieldValue, ...],
) -> ObjectCandidate:
    return ObjectCandidate(category, object_id, base_id, True, "w3a", fields, ())


def _client_item(tip: str, description: str) -> ClientBaseObject:
    return ClientBaseObject(
        obj_id="ratf",
        category="物品",
        fields=(("提示", tip), ("说明", description)),
        evidence_fields=(
            ObjectFieldValue(
                "utip",
                "提示工具 - 基础",
                tip,
                "Units\\ItemStrings.txt",
                ObjectSourceKind.TEXT_STRINGS,
            ),
            ObjectFieldValue(
                "utub",
                "提示工具 - 扩展的",
                description,
                "Units\\ItemStrings.txt",
                ObjectSourceKind.TEXT_STRINGS,
            ),
        ),
    )


def _cache(tip: str, description: str) -> DescriptionCache:
    return DescriptionCache.build(
        (
            DescriptionCacheEntry(
                "物品",
                "ratf",
                "基础提示",
                None,
                tip,
                tip,
                "e" * 64,
                "a" * 64,
                "owned.tsv",
            ),
            DescriptionCacheEntry(
                "物品",
                "ratf",
                "扩展提示",
                None,
                description,
                description,
                "e" * 64,
                "a" * 64,
                "owned.tsv",
            ),
        ),
    )
