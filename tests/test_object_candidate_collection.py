"""Object-source collection and WTS-resolution contracts."""

from __future__ import annotations

import struct

from w3xtool.item_relation_fields import object_field_relations
from w3xtool.item_relation_models import ItemRelationKind
from w3xtool.map_data import GameObject, MapData
from w3xtool.object_candidates import (
    ObjectCandidate,
    ObjectSourceKind,
    collect_object_candidates,
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
        self._files = {
            self._normalize(name): (name, value) for name, value in files.items()
        }

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


def _slk(
    columns: tuple[str, ...], rows: tuple[tuple[str, dict[str, str]], ...]
) -> bytes:
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


def _binary_object(
    old_id: str, new_id: str, values: tuple[tuple[str, str], ...]
) -> bytes:
    mods = b"".join(
        field_id.encode("latin-1")
        + struct.pack("<i", 3)
        + value.encode("utf-8")
        + b"\x00"
        + struct.pack("<I", 0)
        for field_id, value in values
    )
    obj = (
        old_id.encode("latin-1")
        + new_id.encode("latin-1")
        + struct.pack("<i", len(values))
        + mods
    )
    return struct.pack("<ii", 2, 0) + struct.pack("<i", 1) + obj


def test_text_and_slk_values_resolve_wts_and_westring_before_storage() -> None:
    # Given: text and SLK display fields contain WTS and editor-string references.
    archive = FakeArchive(
        {
            "Units\\HumanUnitStrings.txt": b"[H001]\nName=TRIGSTR_1\nTip=WESTRING_ABILITY\n",
            "Units\\UnitData.slk": _slk(
                ("unitID", "Name"), (("H002", {"Name": "TRIGSTR_2"}),)
            ),
        }
    )
    md = MapData(path="fixture.w3x", name="fixture")

    # When: the public pipeline loads both candidate sources.
    load_object_pipeline(md, archive, {1: "文本名称", 2: "SLK名称"}, base_objects={})

    # Then: no unresolved token is stored in the final objects.
    assert md.obj_index["H001"].name == "文本名称"
    assert dict(md.obj_index["H001"].fields)["提示"] == "技能"
    assert md.obj_index["H002"].name == "SLK名称"
    assert "TRIGSTR" not in " ".join(item.search_text for item in md.obj_index.values())


def test_map_and_campaign_prefixes_keep_distinct_wts_and_no_base_aliases() -> None:
    # Given: map and campaign binaries use the same WTS id for different objects.
    archive = FakeArchive(
        {
            "war3map.w3u": _binary_object("hfoo", "H001", (("unam", "TRIGSTR_1"),)),
            "war3campaign.w3u": _binary_object(
                "hfoo", "H002", (("unam", "TRIGSTR_1"),)
            ),
        }
    )

    # When: each prefix is collected with its own WTS table and merged once.
    candidates = (
        *collect_object_candidates(archive, {1: "地图单位"}, prefix="war3map"),
        *collect_object_candidates(archive, {1: "战役单位"}, prefix="war3campaign"),
    )
    merged = merge_object_candidates(candidates, {})
    index = build_object_index(merged)

    # Then: both rawcodes survive with the correct namespace and no base-id alias.
    assert [(item.obj_id, item.name) for item in merged] == [
        ("H001", "地图单位"),
        ("H002", "战役单位"),
    ]
    assert set(index) == {"H001", "H002"}


def test_corrupt_binary_does_not_discard_valid_text_or_slk_candidates() -> None:
    # Given: one malformed binary file beside valid text and SLK sources.
    archive = FakeArchive(
        {
            "war3map.w3u": b"corrupt",
            "Units\\HumanUnitStrings.txt": b"[H001]\nName=Text survives\n",
            "Units\\UnitData.slk": _slk(
                ("unitID", "Name"), (("H002", {"Name": "SLK survives"}),)
            ),
        }
    )
    md = MapData(path="fixture.w3x", name="fixture")

    # When: candidate collection tolerates the malformed source.
    load_object_pipeline(md, archive, {}, base_objects={})

    # Then: valid independent sources still materialize.
    assert {item.obj_id for item in md.obj_index.values()} == {"H001", "H002"}


def test_wts_resolved_field_retains_value_source_and_full_raw_body() -> None:
    # Given: a binary object field points at a WTS string with lossless whitespace.
    raw = '  "正文\t\r\n第二行  '
    archive = FakeArchive(
        {"war3map.w3t": _binary_object("ratf", "I001", (("utub", "TRIGSTR_9"),))},
    )

    # When: object candidates are collected.
    candidate = collect_object_candidates(archive, {9: raw})[0]
    field = next(value for value in candidate.fields if value.key == "utub")

    # Then: the full WTS body and both evidence locations are retained.
    assert field.value == raw
    assert field.source == "war3map.w3t"
    assert field.value_source == "war3map.wts#STRING 9"
    assert field.source_kind is ObjectSourceKind.BINARY


def test_same_text_object_from_func_and_strings_collects_deterministically() -> None:
    # Given: Func and Strings provide different fields for the same unit rawcode.
    files = (
        ("Units\\HumanUnitFunc.txt", b"[H001]\nName=Func Footman\nHP=420\n"),
        ("Units\\HumanUnitStrings.txt", b"[H001]\nName=Localized Footman\n"),
    )
    forward_archive = FakeArchive(dict(files))
    reverse_archive = FakeArchive(dict(reversed(files)))

    # When: collection observes each archive listing order.
    forward = collect_object_candidates(forward_archive, {})
    reverse = collect_object_candidates(reverse_archive, {})

    # Then: collection succeeds and has the same primitive normalized output.
    assert _candidate_normalized(forward) == _candidate_normalized(reverse)
    assert [(item.obj_id, item.ext) for item in forward] == [
        ("H001", "txt"),
        ("H001", "txt"),
    ]


def test_metadata_string_field_reaches_complete_text_index() -> None:
    # Given: metadata identifies an unlisted upgrade field as a string.
    archive = FakeArchive(
        {
            "Units\\UpgradeData.slk": _slk(
                ("upgradeid", "gco1"),
                (("R001", {"gco1": "Complete effect body"}),),
            )
        }
    )
    md = MapData(path="fixture.w3x", name="fixture")

    # When: the ordinary object pipeline collects and indexes it.
    load_object_pipeline(md, archive, {}, base_objects={})

    # Then: raw role, value, and metadata type survive end to end.
    row = next(record for record in md.object_texts.records if record.role == "gco1")
    assert (row.role, row.raw_value) == ("gco1", "Complete effect body")
    assert (
        md.obj_identity_index[("科技", "R001")].field_evidence[0].value_type == "string"
    )


def test_relation_rawcodes_survive_compatibility_display_expansion() -> None:
    # Given: a binary item ability list contains two known rawcodes.
    archive = FakeArchive(
        {"war3map.w3t": _binary_object("ratf", "I001", (("iabi", "AIa1,AIa3"),))}
    )
    item = merge_object_candidates(collect_object_candidates(archive, {}), {})[0]
    skills = (
        GameObject("技能", "base", "AIa1", "AIa1", "属性加成一", False),
        GameObject("技能", "base", "AIa3", "AIa3", "属性加成三", False),
    )
    md = MapData("fixture.w3x", "fixture")
    md.obj_identity_index = {(obj.category, obj.obj_id): obj for obj in (item, *skills)}

    # When: the compatibility object and relation index consume the same field.
    rows = tuple(
        row
        for row in object_field_relations(md)
        if row.kind is ItemRelationKind.ITEM_ABILITY
    )

    # Then: display names remain expanded while both rawcode relations survive.
    assert "能提高英雄属性的物品(AIa1)" in item.field_values["iabi"]
    assert {row.skill.object_id for row in rows if row.skill is not None} == {
        "AIa1",
        "AIa3",
    }


def _candidate_normalized(
    candidates: tuple[ObjectCandidate, ...],
) -> tuple[tuple[str, str, str, str, tuple[tuple[str, str, str, str, int], ...]], ...]:
    return tuple(
        (
            item.category,
            item.obj_id,
            item.base_id,
            item.ext,
            tuple(
                (
                    value.key,
                    value.label,
                    value.value,
                    value.source,
                    int(value.source_kind),
                )
                for value in item.fields
            ),
        )
        for item in candidates
    )
