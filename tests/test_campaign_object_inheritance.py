"""Explicit campaign base chains reach map fields, queries and raw evidence."""

from __future__ import annotations

import json
from pathlib import Path

from gametool.knowledge_object_exports import format_object_fields, write_object_ids
from gametool.map_loader import load_map
from gametool.pack_query_cli import execute_pack_query, load_item_tooltips
from gametool.pack_query_options import PackQueryCliOptions
from gametool.reference_catalog import load_reference_catalog
from tests.skin_layers_fixture import mpq, object_file, slk


def _pack(md, path: Path) -> None:
    path.mkdir()
    write_object_ids(md, str(path / "对象ID"))
    (path / "对象字段.tsv").write_text(
        format_object_fields(md), encoding="utf-8", newline=""
    )


def test_explicit_shared_base_crosses_ids_and_categories_without_reviving_old_values(
    tmp_path: Path,
) -> None:
    child = mpq(
        {
            "war3map.w3t": object_file(
                "w3t", (("ides", "", 0, 0),), code="I002", base="I001"
            )
        }
    )
    path = tmp_path / "cross.w3n"
    path.write_bytes(
        mpq(
            {
                "war3campaign.w3t": object_file(
                    "w3t",
                    (
                        ("unam", "shared original", 0, 0),
                        ("ides", "older text", 0, 0),
                        ("igol", 99, 0, 0),
                    ),
                    code="I001",
                ),
                "war3campaignSkin.w3t": object_file(
                    "w3t",
                    (
                        ("unam", "shared skin", 0, 0),
                        ("ides", "current parent text", 0, 0),
                        ("igol", 17, 0, 0),
                    ),
                    code="I001",
                ),
                "war3campaign.w3u": object_file(
                    "w3u",
                    (("unam", "same code unit", 0, 0), ("usei", "ratf", 0, 0)),
                    code="I001",
                    base="hfoo",
                ),
                "Chapter.w3x": child,
            }
        )
    )
    md = load_map(str(path))
    try:
        chapter = md.sub_maps[0]
        item = chapter.obj_identity_index[("物品", "I002")]
        assert item.base_id == "I001" and item.name == "shared skin"
        assert item.field_values["igol"] == "17" and item.field_values["ides"] == ""
        assert "same code unit" not in {row.value for row in item.field_evidence}
        assert any(
            row.value == "99" and row.state.value == "overridden"
            for row in item.field_evidence
        )
        assert item.field_sources["igol"] == f"{path}!war3campaignSkin.w3t"
        pack = tmp_path / "pack"
        _pack(chapter, pack)
        assert load_item_tooltips(pack)["I002"] == ""
        result = execute_pack_query(PackQueryCliOptions(str(pack), "price", "I002"))
        assert (
            result.exit_code == 0
            and "17" in result.render()
            and "冲突" not in result.render()
        )
        detail = execute_pack_query(
            PackQueryCliOptions(str(pack), "item", "older text")
        )
        assert detail.exit_code == 0 and "overridden" in detail.render()
        current_names = [
            row
            for row in chapter.object_texts.for_object("物品", "I002")
            if row.semantic_field == "name" and row.is_current
        ]
        assert [row.raw_value for row in current_names] == ["shared skin"]
    finally:
        md.close()
    catalog = load_reference_catalog(map_path=path)
    record = next(
        row
        for row in catalog.records
        if row.id == "I002" and row.scope.endswith("!Chapter.w3x")
    )
    assert record.label == "shared skin"
    assert any(
        value.value == "17" and value.state == "campaign-inherited"
        for value in record.values
    )


def test_transitive_child_definition_overrides_higher_skin_parent_layer(
    tmp_path: Path,
) -> None:
    child = mpq(
        {
            "war3map.w3t": object_file(
                "w3t", (("igol", 7, 0, 0),), code="I003", base="I002"
            )
        }
    )
    path = tmp_path / "chain.w3n"
    path.write_bytes(
        mpq(
            {
                "war3campaign.w3t": object_file(
                    "w3t", (("unam", "ancestor", 0, 0), ("igol", 99, 0, 0)), code="I001"
                ),
                "war3campaignSkin.w3t": object_file(
                    "w3t", (("ides", "middle", 0, 0),), code="I002", base="I001"
                ),
                "Chapter.w3x": child,
            }
        )
    )
    md = load_map(str(path))
    try:
        item = md.sub_maps[0].obj_identity_index[("物品", "I003")]
        assert item.name == "ancestor" and item.field_values["ides"] == "middle"
        assert item.field_values["igol"] == "7"
        gold = [row for row in item.field_evidence if row.key == "igol"]
        assert {(row.value, row.source_priority) for row in gold} == {
            ("7", 40),
            ("99", 12),
        }
        for row in item.field_evidence:
            if row.source.endswith("war3campaign.w3t"):
                evidence = json.loads(row.encoded_evidence)
                assert len(evidence["gamexray_inheritance"]) == 2
                assert "raw_bytes_base64" in evidence
    finally:
        md.close()


def test_missing_and_cyclic_shared_bases_keep_confirmed_fields_and_diagnostics(
    tmp_path: Path,
) -> None:
    first = object_file(
        "w3t", (("unam", "cycle first", 0, 0),), code="C001", base="C002"
    )
    second = object_file(
        "w3t", (("ides", "cycle second", 0, 0),), code="C002", base="C001"
    )
    missing = object_file(
        "w3t", (("unam", "known own name", 0, 0),), code="M001", base="MISS"
    )
    root = (
        first[:8] + (3).to_bytes(4, "little") + first[12:] + second[12:] + missing[12:]
    )
    child = mpq({"war3map.w3t": object_file("w3t", (), code="M002", base="M001")})
    path = tmp_path / "unknown.w3n"
    path.write_bytes(mpq({"war3campaign.w3t": root, "Chapter.w3x": child}))
    md = load_map(str(path))
    try:
        assert "ides" not in md.obj_identity_index[("物品", "C001")].field_values
        item = md.sub_maps[0].obj_identity_index[("物品", "M002")]
        assert item.name == "known own name" and "igol" not in item.field_values
        notes = md.sub_maps[0].diagnostics
        assert any(
            note.component == "object-inheritance" and "循环" in note.message
            for note in notes
        )
        assert any(
            note.component == "object-inheritance"
            and "M002" in note.message
            and "MISS" in note.message
            for note in notes
        )
        assert not any(note.component == "object-binary" for note in notes)
    finally:
        md.close()


def test_same_tier_conflicting_base_ids_do_not_choose_an_inherited_value(
    tmp_path: Path,
) -> None:
    left = object_file("w3t", (("unam", "own", 0, 0),), code="X001", base="ratf")
    right = object_file("w3t", (), code="X001", base="rat9")
    raw = left[:8] + (2).to_bytes(4, "little") + left[12:] + right[12:]
    path = tmp_path / "conflict.w3n"
    path.write_bytes(mpq({"war3campaign.w3t": raw}))
    md = load_map(str(path))
    try:
        item = md.obj_identity_index[("物品", "X001")]
        assert item.name == "own" and item.base_id == ""
        assert not any(row.source.startswith("base:") for row in item.field_evidence)
        assert any("声明冲突" in note.message for note in md.diagnostics)
    finally:
        md.close()


def test_client_text_columns_remain_separate_identities() -> None:
    from gametool.client_object_data import ClientBaseObject
    from gametool.object_candidate_models import ObjectFieldValue, ObjectSourceKind
    from gametool.object_text_evidence import collect_client_text_evidence

    fields = tuple(
        ObjectFieldValue(
            f"aub1:5:column:{column}",
            "",
            text,
            "war3mapSkin.w3a",
            ObjectSourceKind.BINARY,
            value_type="string",
        )
        for column, text in ((1, "one"), (2, "two"))
    )
    evidence = collect_client_text_evidence(
        (ClientBaseObject("A001", "技能", (), fields),)
    )
    assert set(evidence) == {
        ("技能", "A001", "ubertip:column:1", "扩展提示", 5),
        ("技能", "A001", "ubertip:column:2", "扩展提示", 5),
    }


def test_deep_explicit_chain_has_no_recursion_limit_or_nested_json_growth() -> None:
    from gametool.object_candidate_models import (
        ObjectCandidate,
        ObjectFieldValue,
        ObjectSourceKind,
    )
    from gametool.object_inheritance import inherit_campaign_candidates
    from gametool.object_materialization import merge_object_candidates

    count = 1200
    source = "war3campaign.w3t"
    candidates = tuple(
        ObjectCandidate(
            "物品",
            f"{number:04x}",
            f"{number - 1:04x}" if number else "BASE",
            True,
            "w3t",
            (
                ObjectFieldValue(
                    "unam", "名称", "ancestor", source, ObjectSourceKind.BINARY
                ),
            )
            if not number
            else (),
            (),
            source,
        )
        for number in range(count)
    )
    inherited, diagnostics = inherit_campaign_candidates(
        reversed(candidates), {"BASE": ("物品", ())}
    )
    assert not diagnostics
    last = tuple(row for row in inherited if row.obj_id == f"{count - 1:04x}")
    obj = merge_object_candidates(last, {})[0]
    assert obj.name == "ancestor"
    evidence = json.loads(
        next(row.encoded_evidence for row in obj.field_evidence if row.key == "unam")
    )
    assert len(evidence["gamexray_inheritance"]) == count - 1
    assert all(isinstance(entry, dict) for entry in evidence["gamexray_inheritance"])


def test_shared_slk_base_and_strings_reach_chapter_without_outranking_local_binary(
    tmp_path: Path,
) -> None:
    child = mpq(
        {
            "war3map.w3t": object_file(
                "w3t", (("unam", "chapter binary", 0, 0),), code="I001", base="s000"
            )
        }
    )
    path = tmp_path / "shared-tables.w3n"
    path.write_bytes(
        mpq(
            {
                "Units\\ItemData.slk": slk(
                    ("itemID", "Name", "goldcost"), (("s000", "shared base", "41"),)
                ),
                "Units\\ItemStrings.txt": b"[I001]\nName=root localized name\n",
                "war3campaignSkin.w3t": object_file(
                    "w3t", (("unam", "root skin", 0, 0),), code="I001", base="s000"
                ),
                "Chapter.w3x": child,
            }
        )
    )
    md = load_map(str(path))
    try:
        assert md.obj_identity_index[("物品", "I001")].name == "root localized name"
        chapter = md.sub_maps[0]
        item = chapter.obj_identity_index[("物品", "I001")]
        assert item.name == "chapter binary" and item.field_values["goldcost"] == "41"
        assert not any(
            note.component == "object-inheritance" for note in chapter.diagnostics
        )
        assert item.field_sources["goldcost"] == f"{path}!Units\\ItemData.slk"
        assert chapter.obj_identity_index[("物品", "s000")].name == "shared base"
        names = [
            row
            for row in chapter.object_texts.for_object("物品", "I001")
            if row.semantic_field == "name"
        ]
        assert [row.raw_value for row in names if row.is_current] == ["chapter binary"]
    finally:
        md.close()
    catalog = load_reference_catalog(map_path=path)
    assert catalog.complete, catalog.diagnostics


def test_chapter_slk_and_strings_empty_values_override_shared_same_source_kinds(
    tmp_path: Path,
) -> None:
    child = mpq(
        {
            "Units\\ItemData.slk": slk(("itemID", "Name"), (("s001", ""),)),
            "Units\\ItemStrings.txt": b"[I001]\nName=\n",
        }
    )
    path = tmp_path / "table-overrides.w3n"
    path.write_bytes(
        mpq(
            {
                "Units\\ItemData.slk": slk(
                    ("itemID", "Name"),
                    (("s001", "root SLK name"), ("s002", "untouched shared")),
                ),
                "Units\\ItemStrings.txt": b"[I001]\nName=root Strings name\n",
                "Chapter.w3x": child,
            }
        )
    )
    md = load_map(str(path))
    try:
        chapter = md.sub_maps[0]
        for code in ("s001", "I001"):
            obj = chapter.obj_identity_index[("物品", code)]
            assert obj.name == code and obj.field_values["display:name"] == ""
            names = [
                row
                for row in chapter.object_texts.for_object("物品", code)
                if row.semantic_field == "name"
            ]
            assert [row.raw_value for row in names if row.is_current] == [""]
            assert all(not row.conflict_group for row in names)
        untouched = chapter.obj_identity_index[("物品", "s002")]
        assert untouched.name == "untouched shared" and untouched.ext == "campaign"
        assert untouched.field_sources["display:name"] == f"{path}!Units\\ItemData.slk"
    finally:
        md.close()
