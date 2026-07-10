"""Deterministic object candidate collection and merge contracts."""

from __future__ import annotations

import struct
from collections.abc import Iterable
from dataclasses import FrozenInstanceError

import pytest

from w3xtool.map_data import MapData
from w3xtool.object_candidates import (
    ObjectCandidate,
    ObjectFieldValue,
    ObjectSourceKind,
)
from w3xtool.object_pipeline import (
    build_object_index,
    load_object_pipeline,
    merge_object_candidates,
)


class FakeArchive:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.path = "fixture.w3x"
        self._data = b""
        self._files = {self._normalize(name): (name, value) for name, value in files.items()}

    def has_file(self, name: str) -> bool:
        return self._normalize(name) in self._files

    def read_file(self, name: str) -> bytes:
        return self._files[self._normalize(name)][1]

    def list_files(self) -> list[str]:
        return [name for name, _value in self._files.values()]

    def close(self) -> None:
        return None

    @staticmethod
    def _normalize(name: str) -> str:
        return name.replace("/", "\\").casefold()


def field(
    key: str,
    label: str,
    value: str,
    source_kind: ObjectSourceKind,
    source: str = "fixture",
) -> ObjectFieldValue:
    return ObjectFieldValue(key, label, value, source, source_kind)


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


def _slk(columns: tuple[str, ...], rows: tuple[tuple[str, dict[str, str]], ...]) -> bytes:
    lines = ["ID;P", f"B;X{len(columns)};Y{len(rows) + 1}"]
    for x, column in enumerate(columns, 1):
        lines.append(f'C;X{x};Y1;K"{column}"')
    for y, (code, values) in enumerate(rows, 2):
        lines.append(f'C;X1;Y{y};K"{code}"')
        for x, column in enumerate(columns, 1):
            if column in values:
                lines.append(f'C;X{x};Y{y};K"{values[column]}"')
    lines.append("E")
    return "\n".join(lines).encode("latin-1")


def _binary_object(old_id: str, new_id: str, values: tuple[tuple[str, str], ...]) -> bytes:
    mods = b"".join(
        field_id.encode("latin-1")
        + struct.pack("<i", 3)
        + value.encode("utf-8")
        + b"\x00"
        + struct.pack("<I", 0)
        for field_id, value in values
    )
    obj = old_id.encode("latin-1") + new_id.encode("latin-1") + struct.pack("<i", len(values)) + mods
    return struct.pack("<ii", 2, 0) + struct.pack("<i", 1) + obj


def _normalized(objects: tuple) -> tuple:
    return tuple(
        (
            obj.category,
            obj.obj_id,
            obj.base_id,
            obj.name,
            obj.icon,
            tuple(obj.fields),
            tuple(sorted(obj.field_values.items())),
            tuple(sorted(obj.field_sources.items())),
            tuple((label, tuple(codes)) for label, codes in obj.ref_fields),
        )
        for obj in objects
    )


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
        candidate("H001", ObjectSourceKind.TEXT_STRINGS, (field("Name", "名称", "文本步兵", ObjectSourceKind.TEXT_STRINGS),)),
        candidate("H002", ObjectSourceKind.BINARY, (field("binary:uhpm", "生命上限", "2500", ObjectSourceKind.BINARY),), ext="w3u"),
    )

    # When: all candidates enter the same merge.
    merged = merge_object_candidates(candidates, {})

    # Then: neither source suppresses the other.
    assert {obj.obj_id for obj in merged} == {"H001", "H002"}


def test_priority_canonicalizes_display_aliases_without_collapsing_levels() -> None:
    # Given: every source writes the same display field and two leveled data fields.
    candidates = (
        candidate("H001", ObjectSourceKind.SLK, (field("Name", "名称", "SLK名", ObjectSourceKind.SLK),)),
        candidate("H001", ObjectSourceKind.TEXT_FUNC, (field("Name", "名称", "Func名", ObjectSourceKind.TEXT_FUNC), field("DataA1", "数据A (等级1)", "10", ObjectSourceKind.TEXT_FUNC))),
        candidate("H001", ObjectSourceKind.BINARY, (field("unam", "名称", "二进制名", ObjectSourceKind.BINARY), field("DataA2", "数据A (等级2)", "20", ObjectSourceKind.BINARY)), ext="w3u"),
        candidate("H001", ObjectSourceKind.TEXT_STRINGS, (field("display:name", "名称", "本地化名", ObjectSourceKind.TEXT_STRINGS),)),
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
        candidate("H001", ObjectSourceKind.SLK, (field("HP", "生命上限", "1000", ObjectSourceKind.SLK), field("spd", "移动速度", "270", ObjectSourceKind.SLK))),
        candidate("H001", ObjectSourceKind.TEXT_FUNC, (field("HP", "生命上限", "1800", ObjectSourceKind.TEXT_FUNC),)),
        candidate("H001", ObjectSourceKind.BINARY, (field("uhpm", "生命上限", "2500", ObjectSourceKind.BINARY),), ext="w3u"),
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
        candidate("H001", ObjectSourceKind.BINARY, (field("unam", "名称", "强化步兵", ObjectSourceKind.BINARY),), ext="w3u"),
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
    first = candidate("H001", ObjectSourceKind.BINARY, (field("uhpm", "生命上限", "2400", ObjectSourceKind.BINARY, "b.w3u"),), ext="w3u")
    second = candidate("H001", ObjectSourceKind.BINARY, (field("uhpm", "生命上限", "2500", ObjectSourceKind.BINARY, "c.w3u"),), ext="w3u")
    candidates = (first, first, second)

    # When: both orders are merged.
    forward = merge_object_candidates(candidates, {})
    reverse = merge_object_candidates(tuple(reversed(candidates)), {})

    # Then: duplicates disappear and normalized output is byte-for-byte equivalent.
    assert _normalized(forward) == _normalized(reverse)
    assert dict(forward[0].fields)["生命上限"] == "2500"


def test_references_are_unioned_by_label_and_code() -> None:
    # Given: overlapping references from binary and SLK candidates.
    candidates = (
        candidate("H001", ObjectSourceKind.SLK, (), refs=(("技能列表", ("A001", "A002")),)),
        candidate("H001", ObjectSourceKind.BINARY, (), ext="w3u", refs=(("技能列表", ("A002", "A001")), ("建造", ("hbar",)))),
    )

    # When: references are merged.
    merged = merge_object_candidates(candidates, {})[0]

    # Then: each label/code edge occurs once in deterministic order.
    assert merged.ref_fields == [("建造", ["hbar"]), ("技能列表", ["A001", "A002"])]


def test_derived_state_is_rebuilt_only_from_final_fields() -> None:
    # Given: a losing name/icon and winning localized display values.
    candidates = (
        candidate("H001", ObjectSourceKind.BINARY, (field("unam", "名称", "内部名", ObjectSourceKind.BINARY), field("uico", "图标", "old.blp", ObjectSourceKind.BINARY)), ext="w3u"),
        candidate("H001", ObjectSourceKind.TEXT_STRINGS, (field("Name", "名称", "最终名称", ObjectSourceKind.TEXT_STRINGS, "strings.txt"), field("Art", "图标", "new.blp,replaceable", ObjectSourceKind.TEXT_STRINGS, "strings.txt"))),
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
                field("Art", "图标", "footman.blp", ObjectSourceKind.TEXT_STRINGS),
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


def test_binary_and_slk_coexist_in_pipeline_without_duplicate_codes() -> None:
    # Given: binary, text and SLK all describe the same custom object.
    archive = FakeArchive(
        {
            "war3map.w3u": _binary_object("hfoo", "H001", (("unam", "Binary Footman"),)),
            "Units\\HumanUnitStrings.txt": b"[H001]\nName=Localized Footman\n",
            "Units\\UnitData.slk": _slk(("unitID", "Name", "race"), (("H001", {"Name": "SLK Footman", "race": "human"}),)),
        }
    )
    md = MapData(path="fixture.w3x", name="fixture")

    # When: one deterministic pipeline assembles the category.
    load_object_pipeline(md, archive, {}, base_objects={})

    # Then: one rawcode remains, text supplies display, and SLK supplies missing data.
    codes = [obj.obj_id for values in md.objects.values() for obj in values]
    assert codes == ["H001"]
    assert list(md.obj_index) == ["H001"]
    assert md.obj_index["H001"].name == "Localized Footman"
    assert dict(md.obj_index["H001"].fields)["种族"] == "human"
    assert md.obj_index["H001"].ext == "w3u"


def test_load_map_impl_merges_map_and_campaign_candidates_once() -> None:
    # Given: text, binary, SLK, and campaign sources have distinct WTS scopes.
    from w3xtool import api
    from w3xtool.load_context import MapLoadContext

    archive = FakeArchive(
        {
            "war3map.wts": "STRING 1\n{\n地图文本单位\n}\n".encode(),
            "Units\\HumanUnitStrings.txt": b"[H001]\nName=TRIGSTR_1\n",
            "war3map.w3u": _binary_object(
                "hfoo", "H002", (("uhpm", "2500"), ("uabi", "A001"))
            ),
            "Units\\UnitData.slk": _slk(
                ("unitID", "race", "abilList"),
                (("H002", {"race": "human", "abilList": "A002"}),),
            ),
            "war3campaign.wts": "STRING 1\n{\n战役共享单位\n}\n".encode(),
            "war3campaign.w3u": _binary_object("hfoo", "H003", (("unam", "TRIGSTR_1"),)),
        }
    )

    # When: the high-level loader collects both namespaces before one materialization.
    md = api._load_map_impl(archive, archive.path, 0, None, MapLoadContext())

    # Then: every source survives without aliases or category-wide suppression.
    assert {"H001", "H002", "H003"}.issubset(md.obj_index)
    assert md.obj_index["H001"].name == "地图文本单位"
    assert md.obj_index["H003"].name == "战役共享单位"
    h002 = md.obj_index["H002"]
    assert dict(h002.fields)["生命上限"] == "2500"
    assert dict(h002.fields)["种族"] == "human"
    assert ("uabi", ["A001"]) in h002.ref_fields
    assert ("abilList", ["A002"]) in h002.ref_fields
    rawcodes = [item.obj_id for bucket in md.objects.values() for item in bucket]
    assert len(rawcodes) == len(set(rawcodes))
    assert all(code == item.obj_id for code, item in md.obj_index.items())
    assert md.obj_index["hfoo"].obj_id == "hfoo"
    assert md.obj_index["hfoo"] is not h002
