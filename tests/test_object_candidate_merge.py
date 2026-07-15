"""Deterministic object candidate merge and evidence contracts."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import FrozenInstanceError

import pytest

from w3xtool.object_candidates import (
    ObjectCandidate,
    ObjectFieldValue,
    ObjectSourceKind,
)
from w3xtool.object_pipeline import build_object_index, merge_object_candidates


def field(
    key: str,
    label: str,
    value: str,
    source_kind: ObjectSourceKind,
    source: str = "fixture",
    value_type: str = "",
) -> ObjectFieldValue:
    return ObjectFieldValue(
        key,
        label,
        value,
        source,
        source_kind,
        value_type=value_type,
    )


def candidate(
    obj_id: str,
    source_kind: ObjectSourceKind,
    fields: Iterable[ObjectFieldValue],
    *,
    category: str = "单位",
    base_id: str = "hfoo",
    ext: str = "txt",
    refs: tuple[tuple[str, tuple[str, ...]], ...] = (),
) -> ObjectCandidate:
    return ObjectCandidate(category, obj_id, base_id, True, ext, tuple(fields), refs)


def test_candidate_values_are_immutable() -> None:
    # Given: a directly constructed candidate value.
    value = field("display:name", "名称", "步兵", ObjectSourceKind.TEXT_STRINGS)
    item = candidate("H001", ObjectSourceKind.TEXT_STRINGS, (value,))

    # When/Then: neither value can be mutated after construction.
    with pytest.raises(FrozenInstanceError):
        setattr(value, "value", "骑士")
    with pytest.raises(FrozenInstanceError):
        setattr(item, "obj_id", "H002")


def test_text_and_binary_candidates_coexist_without_category_suppression() -> None:
    # Given: text and binary candidates in the same category with different ids.
    candidates = (
        candidate(
            "H001",
            ObjectSourceKind.TEXT_STRINGS,
            (field("Name", "名称", "文本步兵", ObjectSourceKind.TEXT_STRINGS),),
        ),
        candidate(
            "H002",
            ObjectSourceKind.BINARY,
            (field("binary:uhpm", "生命上限", "2500", ObjectSourceKind.BINARY),),
            ext="w3u",
        ),
    )

    # When: all candidates enter the same merge.
    merged = merge_object_candidates(candidates, {})

    # Then: neither source suppresses the other.
    assert {obj.obj_id for obj in merged} == {"H001", "H002"}


def test_priority_canonicalizes_display_aliases_without_collapsing_levels() -> None:
    # Given: every source writes the same display field and two leveled data fields.
    candidates = (
        candidate(
            "H001",
            ObjectSourceKind.SLK,
            (field("Name", "名称", "SLK名", ObjectSourceKind.SLK),),
        ),
        candidate(
            "H001",
            ObjectSourceKind.TEXT_FUNC,
            (
                field("Name", "名称", "Func名", ObjectSourceKind.TEXT_FUNC),
                field("DataA1", "数据A (等级1)", "10", ObjectSourceKind.TEXT_FUNC),
            ),
        ),
        candidate(
            "H001",
            ObjectSourceKind.BINARY,
            (
                field("unam", "名称", "二进制名", ObjectSourceKind.BINARY),
                field("DataA2", "数据A (等级2)", "20", ObjectSourceKind.BINARY),
            ),
            ext="w3u",
        ),
        candidate(
            "H001",
            ObjectSourceKind.TEXT_STRINGS,
            (field("display:name", "名称", "本地化名", ObjectSourceKind.TEXT_STRINGS),),
        ),
    )

    # When: aliases and source priorities are applied.
    merged = merge_object_candidates(candidates, {})[0]

    # Then: Strings wins display only and levels remain separate non-display fields.
    assert merged.name == "本地化名"
    assert dict(merged.fields)["数据A (等级1)"] == "10"
    assert dict(merged.fields)["数据A (等级2)"] == "20"
    assert [label for label, _value in merged.fields].count("名称") == 1


def test_binary_beats_func_and_slk_supplements_missing_fields() -> None:
    # Given: three sources conflict on health while SLK alone provides speed.
    candidates = (
        candidate(
            "H001",
            ObjectSourceKind.SLK,
            (
                field("HP", "生命上限", "1000", ObjectSourceKind.SLK),
                field("spd", "移动速度", "270", ObjectSourceKind.SLK),
            ),
        ),
        candidate(
            "H001",
            ObjectSourceKind.TEXT_FUNC,
            (field("HP", "生命上限", "1800", ObjectSourceKind.TEXT_FUNC),),
        ),
        candidate(
            "H001",
            ObjectSourceKind.BINARY,
            (field("uhpm", "生命上限", "2500", ObjectSourceKind.BINARY),),
            ext="w3u",
        ),
    )

    # When: the object is merged.
    merged = merge_object_candidates(candidates, {})[0]

    # Then: binary wins its explicit field and SLK fills only the missing field.
    assert dict(merged.fields)["生命上限"] == "2500"
    assert dict(merged.fields)["移动速度"] == "270"
    assert merged.field_sources["uhpm"] == "fixture"


def test_custom_object_inherits_base_without_aliasing_base_id() -> None:
    # Given: a custom object modifies only its display name.
    candidates = (
        candidate(
            "H001",
            ObjectSourceKind.BINARY,
            (field("unam", "名称", "强化步兵", ObjectSourceKind.BINARY),),
            ext="w3u",
        ),
    )

    # When: base fields are inherited and the index is built.
    merged = merge_object_candidates(
        candidates,
        {"hfoo": ("单位", [("生命上限", "420"), ("移动速度", "270")])},
    )
    index = build_object_index(merged)

    # Then: inherited fields exist but the base id is not an alias.
    assert dict(merged[0].fields)["生命上限"] == "420"
    assert index["H001"] is merged[0]
    assert "hfoo" not in index


def test_duplicate_candidates_and_fields_are_deterministic() -> None:
    # Given: duplicate candidates and equal-priority conflicts in opposite orders.
    first = candidate(
        "H001",
        ObjectSourceKind.BINARY,
        (field("uhpm", "生命上限", "2400", ObjectSourceKind.BINARY, "b.w3u"),),
        ext="w3u",
    )
    second = candidate(
        "H001",
        ObjectSourceKind.BINARY,
        (field("uhpm", "生命上限", "2500", ObjectSourceKind.BINARY, "c.w3u"),),
        ext="w3u",
    )
    candidates = (first, first, second)

    # When: both orders are merged.
    forward = merge_object_candidates(candidates, {})
    reverse = merge_object_candidates(tuple(reversed(candidates)), {})

    # Then: duplicates disappear and every materialized field is identical.
    assert forward == reverse
    assert dict(forward[0].fields)["生命上限"] == "2500"


def test_references_are_unioned_by_label_and_code() -> None:
    # Given: overlapping references from binary and SLK candidates.
    candidates = (
        candidate(
            "H001", ObjectSourceKind.SLK, (), refs=(("技能列表", ("A001", "A002")),)
        ),
        candidate(
            "H001",
            ObjectSourceKind.BINARY,
            (),
            ext="w3u",
            refs=(("技能列表", ("A002", "A001")), ("建造", ("hbar",))),
        ),
    )

    # When: references are merged.
    merged = merge_object_candidates(candidates, {})[0]

    # Then: each label/code edge occurs once in deterministic order.
    assert merged.ref_fields == [("建造", ["hbar"]), ("技能列表", ["A001", "A002"])]


def test_derived_state_is_rebuilt_only_from_final_fields() -> None:
    # Given: a losing name/icon and winning localized display values.
    candidates = (
        candidate(
            "H001",
            ObjectSourceKind.BINARY,
            (
                field("unam", "名称", "内部名", ObjectSourceKind.BINARY),
                field("uico", "图标", "old.blp", ObjectSourceKind.BINARY),
            ),
            ext="w3u",
        ),
        candidate(
            "H001",
            ObjectSourceKind.TEXT_STRINGS,
            (
                field(
                    "Name",
                    "名称",
                    "最终名称",
                    ObjectSourceKind.TEXT_STRINGS,
                    "strings.txt",
                ),
                field(
                    "Art",
                    "图标",
                    "new.blp,replaceable",
                    ObjectSourceKind.TEXT_STRINGS,
                    "strings.txt",
                    "icon",
                ),
            ),
        ),
    )

    # When: final fields and derived values are materialized.
    merged = merge_object_candidates(candidates, {})[0]

    # Then: provenance, search, name and icon describe only the winning state.
    assert merged.name == "最终名称"
    assert merged.icon == "new.blp"
    assert "内部名" not in merged.search_text
    assert "最终名称" in merged.search_text
    assert merged.field_values["display:name"] == "最终名称"
    assert merged.field_sources["display:name"] == "strings.txt"
    assert "unam" not in merged.field_values


def test_final_display_values_and_provenance_use_canonical_keys() -> None:
    # Given: source-specific aliases for the four public display concepts.
    candidates = (
        candidate(
            "H001",
            ObjectSourceKind.TEXT_STRINGS,
            (
                field("Name", "名称", "步兵", ObjectSourceKind.TEXT_STRINGS),
                field("Propernames", "名字", "阿尔法", ObjectSourceKind.TEXT_STRINGS),
                field("Ubertip", "说明", "单位说明", ObjectSourceKind.TEXT_STRINGS),
                field(
                    "Art",
                    "图标",
                    "footman.blp",
                    ObjectSourceKind.TEXT_STRINGS,
                    value_type="icon",
                ),
                field("uhpm", "生命上限", "420", ObjectSourceKind.TEXT_STRINGS),
            ),
        ),
    )

    # When: the aliases are materialized into the public object.
    merged = merge_object_candidates(candidates, {})[0]

    # Then: display values and provenance use stable canonical keys only.
    assert merged.field_values["display:name"] == "步兵"
    assert merged.field_values["display:propernames"] == "阿尔法"
    assert merged.field_values["display:description"] == "单位说明"
    assert merged.field_values["display:icon"] == "footman.blp"
    assert merged.field_sources["display:name"] == "fixture"
    assert {"Name", "Propernames", "Ubertip", "Art"}.isdisjoint(merged.field_values)
    assert merged.field_values["uhpm"] == "420"
