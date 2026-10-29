"""Skin files and campaign layers retain complete current and raw evidence."""

from __future__ import annotations

import base64
import csv
import io
import json
from pathlib import Path

import pytest

from gametool.batch_tsv import format_tsv_rows
from gametool.knowledge_object_exports import format_object_fields, write_object_ids
from gametool.map_loader import load_map
from gametool.mpq_files import STATIC_MAP_FILES
from gametool.object_layers import binary_object_members
from gametool.pack_query_cli import (
    execute_pack_query,
    load_item_equipped_effects,
    load_item_tooltips,
    load_tech_fields,
)
from gametool.pack_query_options import PackQueryCliOptions
from gametool.reference_catalog import load_reference_catalog
from gametool.w3obj import EXT_CATEGORY
from tests.skin_layers_fixture import mpq, object_file


_NAME_FIELDS = dict(
    zip(
        EXT_CATEGORY,
        ("unam", "unam", "anam", "gnam", "bnam", "dnam", "fnam"),
        strict=True,
    )
)


def _rows(md):
    return tuple(
        csv.DictReader(
            io.StringIO(format_object_fields(md), newline=""), delimiter="\t"
        )
    )


def _pack(md, root: Path) -> None:
    root.mkdir()
    write_object_ids(md, str(root / "对象ID"))
    (root / "对象字段.tsv").write_text(
        format_object_fields(md), encoding="utf-8", newline=""
    )


@pytest.mark.parametrize("active_conflict", (False, True))
def test_overridden_stock_remains_searchable_without_becoming_a_shop_blocker(
    tmp_path: Path, active_conflict: bool
) -> None:
    ids = tmp_path / "对象ID"
    ids.mkdir()
    (ids / "单位.tsv").write_text(
        format_tsv_rows(
            (
                ("分类", "ID", "10进制", "基础ID", "名称", "自定义", "说明"),
                ("单位", "n001", "", "n001", "Known shop", "是", ""),
            )
        ),
        encoding="utf-8",
    )
    fields = [
        ("分类", "ID", "名称", "字段键", "字段名", "值", "来源", "证据状态"),
        (
            "单位",
            "n001",
            "Known shop",
            "base:Sellitems",
            "出售物品",
            "I000",
            "base:n001",
            "overridden",
        ),
    ]
    if active_conflict:
        fields.extend(
            (
                "单位",
                "n001",
                "Known shop",
                "Sellitems",
                "出售物品",
                code,
                "UnitData.slk",
                "conflict",
            )
            for code in ("I001", "I002")
        )
    (tmp_path / "对象字段.tsv").write_text(format_tsv_rows(fields), encoding="utf-8")

    shop = execute_pack_query(PackQueryCliOptions(str(tmp_path), "shop", "n001"))
    assert "I000" not in shop.render()
    assert ("货架字段未确认" in shop.render()) is active_conflict
    details = execute_pack_query(PackQueryCliOptions(str(tmp_path), "units", "I000"))
    assert details.exit_code == 0
    assert "I000" in details.render() and "overridden" in details.render()


@pytest.mark.parametrize("prefix", ("war3map", "war3campaign"))
@pytest.mark.parametrize("ext", tuple(EXT_CATEGORY))
def test_all_skin_categories_discover_without_listfile(
    tmp_path: Path, prefix: str, ext: str
) -> None:
    member = f"{prefix}Skin.{ext}"
    field = _NAME_FIELDS[ext]
    path = tmp_path / ("fixture.w3n" if prefix == "war3campaign" else "fixture.w3x")
    path.write_bytes(
        mpq({member: object_file(ext, ((field, "Skin only", 0, 0),))}, listed=False)
    )
    before = path.read_bytes(), path.stat().st_mtime_ns
    md = load_map(str(path))
    try:
        item = md.obj_identity_index[(EXT_CATEGORY[ext], "S001")]
        assert item.name == "Skin only"
        assert member in md.all_files
        assert item.field_sources["display:name"] == member
        assert all(name in STATIC_MAP_FILES for name in binary_object_members(prefix))
    finally:
        md.close()
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_skin_overlay_exports_lower_layers_but_price_uses_current_value(
    tmp_path: Path,
) -> None:
    files = {
        "war3map.w3t": object_file(
            "w3t",
            (
                ("unam", "Base item", 0, 0),
                ("igol", 90, 0, 0),
                ("ides", "old description", 0, 0),
            ),
        ),
        "war3mapSkin.w3t": object_file(
            "w3t", (("unam", "TRIGSTR_1", 0, 0), ("igol", 12, 0, 0), ("ides", "", 0, 0))
        ),
        "war3map.wts": b"STRING 1\n{\nSkin item\n}\n",
        "war3mapSkin.wts": b"STRING 1\n{\nwrong scope\n}\n",
    }
    path = tmp_path / "overlay.w3x"
    path.write_bytes(mpq(files))
    md = load_map(str(path))
    try:
        obj = md.obj_identity_index[("物品", "S001")]
        assert obj.name == "Skin item" and obj.field_values["igol"] == "12"
        assert obj.field_values["ides"] == ""
        rows = [row for row in _rows(md) if row["ID"] == "S001"]
        assert any(
            row["值"] == "90" and row["证据状态"] == "overridden" for row in rows
        )
        assert any(row["值"] == "12" and row["证据状态"] == "confirmed" for row in rows)
        assert any(
            row["值"] == "old description" and row["证据状态"] == "overridden"
            for row in rows
        )
        pack = tmp_path / "pack"
        _pack(md, pack)
        price = execute_pack_query(PackQueryCliOptions(str(pack), "price", "S001"))
        assert price.exit_code == 0
        assert "地图价 12" in price.render() or "12" in price.render()
        assert "冲突" not in price.render()
        detail = execute_pack_query(
            PackQueryCliOptions(str(pack), "item", "old description")
        )
        assert detail.exit_code == 0 and "overridden" in detail.render()
        assert load_item_tooltips(pack)["S001"] == ""
        texts = [
            row
            for row in md.object_texts.for_object("物品", "S001")
            if row.semantic_field == "name"
        ]
        assert {row.raw_value for row in texts} == {"Base item", "Skin item"}
        assert [row.raw_value for row in texts if row.is_current] == ["Skin item"]
    finally:
        md.close()
    catalog = load_reference_catalog(map_path=path)
    record = next(
        row for row in catalog.records if row.id == "S001" and row.scope == str(path)
    )
    assert record.label == "Skin item"
    assert f"{path}!war3map.wts" in record.sources
    assert f"{path}!war3mapSkin.wts" not in record.sources
    assert any(
        row.value == "Base item" and row.state == "overridden" for row in record.values
    )


def test_campaign_four_layers_inherit_without_losing_scopes(tmp_path: Path) -> None:
    root_fields = (
        ("unam", "Shared base", 0, 0),
        ("ides", "shared survives", 0, 0),
        ("igol", 1, 0, 0),
    )
    child = mpq(
        {
            "war3map.w3t": object_file(
                "w3t", (("unam", "Chapter base", 0, 0), ("igol", 3, 0, 0))
            ),
            "war3mapSkin.w3t": object_file(
                "w3t", (("unam", "TRIGSTR_1", 0, 0), ("igol", 4, 0, 0))
            ),
            "war3map.wts": b"STRING 1\n{\nChapter skin\n}\n",
        }
    )
    shared_only = object_file("w3t", (("unam", "Only shared", 0, 0),), code="S002")
    path = tmp_path / "layers.w3n"
    path.write_bytes(
        mpq(
            {
                "war3campaign.w3t": object_file("w3t", root_fields),
                "war3campaignSkin.w3t": object_file(
                    "w3t", (("unam", "TRIGSTR_1", 0, 0), ("igol", 2, 0, 0))
                ),
                "war3campaign.wts": b"STRING 1\n{\nShared skin\n}\n",
                "war3campaignSkin.w3u": shared_only,
                "Chapter.w3x": child,
            }
        )
    )
    md = load_map(str(path))
    try:
        assert md.obj_index["S001"].name == "Shared skin"
        chapter = md.sub_maps[0]
        obj = chapter.obj_identity_index[("物品", "S001")]
        assert (
            obj.name == "Chapter skin" and obj.field_values["ides"] == "shared survives"
        )
        assert obj.field_sources["ides"] == f"{path}!war3campaign.w3t"
        gold = [row for row in obj.field_evidence if row.key == "igol"]
        assert {(row.value, row.source_priority) for row in gold} == {
            ("1", 11),
            ("2", 12),
            ("3", 40),
            ("4", 45),
        }
        assert chapter.obj_identity_index[("单位", "S002")].ext == "campaign"
        pack = tmp_path / "chapter-pack"
        _pack(chapter, pack)
        answer = execute_pack_query(
            PackQueryCliOptions(str(pack), "item", "shared survives")
        )
        assert answer.exit_code == 0 and str(path) in answer.render()
    finally:
        md.close()
    catalog = load_reference_catalog(map_path=path)
    record = next(
        row
        for row in catalog.records
        if row.id == "S001" and row.scope.endswith("!Chapter.w3x")
    )
    assert record.label == "Chapter skin"
    assert f"{path}!war3campaign.w3t" in record.sources
    assert f"{path}!war3campaign.wts" in record.sources
    assert any(
        value.value == "shared survives" and value.source == f"{path}!war3campaign.w3t"
        for value in record.values
    )
    assert (
        len(
            [
                row
                for row in catalog.records
                if row.id == "S002" and row.scope != "builtin"
            ]
        )
        == 1
    )


def test_levels_and_columns_preserve_raw_bytes_and_do_not_collapse(
    tmp_path: Path,
) -> None:
    fields = (
        ("Data", "column one", 2, 1),
        ("Data", "column two", 2, 2),
        ("Data", "next level", 3, 1),
    )
    raw = object_file("w3a", fields, base="AHbz")
    path = tmp_path / "columns.w3x"
    path.write_bytes(mpq({"war3mapSkin.w3a": raw}))
    md = load_map(str(path))
    try:
        obj = md.obj_identity_index[("技能", "S001")]
        assert all(
            obj.field_values[f"Data:{level}:column:{pointer}"] == value
            for _key, value, level, pointer in fields
        )
        for field in (
            row for row in obj.field_evidence if row.source == "war3mapSkin.w3a"
        ):
            evidence = json.loads(field.encoded_evidence)
            assert (
                base64.b64decode(evidence["raw_bytes_base64"])
                == raw[evidence["offset"] : evidence["end_offset"]]
            )
            assert evidence["data_pointer"] in {1, 2}
    finally:
        md.close()


def test_empty_skin_name_and_truncated_layer_keep_evidence_and_diagnostics(
    tmp_path: Path,
) -> None:
    path = tmp_path / "empty.w3x"
    path.write_bytes(
        mpq(
            {
                "war3map.w3t": object_file(
                    "w3t", (("unam", "Prior searchable name", 0, 0),)
                ),
                "war3mapSkin.w3t": object_file("w3t", (("unam", "", 0, 0),)),
                "war3mapSkin.w3u": b"truncated",
            }
        )
    )
    md = load_map(str(path))
    try:
        item = md.obj_identity_index[("物品", "S001")]
        assert item.name == "S001" and item.field_values["display:name"] == ""
        assert any(note.source == "war3mapSkin.w3u" for note in md.diagnostics)
        pack = tmp_path / "pack"
        _pack(md, pack)
        result = execute_pack_query(
            PackQueryCliOptions(str(pack), "item", "Prior searchable name")
        )
        assert result.exit_code == 0 and "S001" in result.render()
    finally:
        md.close()
    catalog = load_reference_catalog(map_path=path)
    assert not catalog.complete and any(
        "war3mapSkin.w3u" in note for note in catalog.diagnostics
    )


def test_item_skill_columns_keep_independent_levels_and_current_summaries(
    tmp_path: Path,
) -> None:
    path = tmp_path / "skills.w3x"
    path.write_bytes(
        mpq(
            {
                "war3map.w3t": object_file(
                    "w3t", (("unam", "Item", 0, 0), ("iabi", "A001", 0, 0))
                ),
                "war3map.w3a": object_file(
                    "w3a",
                    (
                        ("Istr", 2, 1, 1),
                        ("Istr", 3, 1, 2),
                        ("aub1", "first column", 1, 1),
                        ("aub1", "second column", 1, 2),
                    ),
                    code="A001",
                    base="AIa1",
                ),
                "war3mapSkin.w3a": object_file(
                    "w3a", (("Istr", 4, 1, 1),), code="A001", base="AIa1"
                ),
            }
        )
    )
    md = load_map(str(path))
    try:
        pack = tmp_path / "pack"
        _pack(md, pack)
        summaries = load_item_equipped_effects(pack)["S001"]
        assert any(
            value.startswith("+4 力量") and "等级 1，数据列 1" in value
            for value in summaries
        )
        assert any(
            value.startswith("+3 力量") and "等级 1，数据列 2" in value
            for value in summaries
        )
        assert not any(value.startswith("+2 力量") for value in summaries)
        texts = [
            row
            for row in md.object_texts.for_object("技能", "A001")
            if row.semantic_field.startswith("ubertip:column:")
        ]
        assert {
            (row.level, row.semantic_field, row.raw_value)
            for row in texts
            if row.is_current
        } == {
            (1, "ubertip:column:1", "first column"),
            (1, "ubertip:column:2", "second column"),
        }
    finally:
        md.close()


def test_tech_columns_and_overrides_are_current_in_cost_and_effects(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tech.w3x"
    path.write_bytes(
        mpq(
            {
                "war3map.w3q": object_file(
                    "w3q",
                    (
                        ("gnam", "Tech", 0, 0),
                        ("glvl", 3, 0, 0),
                        ("gglb", 100, 0, 1),
                        ("gglm", 5, 0, 0),
                        ("glmb", 0, 0, 0),
                        ("glmm", 0, 0, 0),
                        ("gub1", "old effect", 2, 1),
                    ),
                    code="R001",
                    base="Rhme",
                ),
                "war3mapSkin.w3q": object_file(
                    "w3q",
                    (("gglb", 200, 0, 1), ("gub1", "new effect", 2, 1)),
                    code="R001",
                    base="Rhme",
                ),
            }
        )
    )
    md = load_map(str(path))
    try:
        pack = tmp_path / "pack"
        _pack(md, pack)
        result = execute_pack_query(PackQueryCliOptions(str(pack), "tech", "R001"))
        assert result.exit_code == 0
        text = result.render()
        assert "2级 金205 木0" in text
        assert "效果(2级，数据列 1): new effect" in text
        assert "效果(2级，数据列 1): old effect" not in text
        assert "old effect" in text and "overridden" in text
        assert load_tech_fields(pack)["R001"]["gglb:column:1"] == "200"
    finally:
        md.close()


def test_pack_diff_and_reference_do_not_promote_overridden_values(
    tmp_path: Path,
) -> None:
    packs = []
    for current in (12, 13):
        path = tmp_path / f"price-{current}.w3x"
        path.write_bytes(
            mpq(
                {
                    "war3map.w3t": object_file(
                        "w3t", (("unam", "Same name", 0, 0), ("igol", 90, 0, 0))
                    ),
                    "war3mapSkin.w3t": object_file("w3t", (("igol", current, 0, 0),)),
                }
            )
        )
        md = load_map(str(path))
        try:
            pack = tmp_path / f"pack-{current}"
            _pack(md, pack)
            packs.append(pack)
        finally:
            md.close()
    result = execute_pack_query(
        PackQueryCliOptions(str(packs[1]), "diff", "", pack_dir_b=str(packs[0]))
    )
    assert result.has_changes and "12" in result.render() and "13" in result.render()
    assert "igol" in result.render()
    catalog = load_reference_catalog(pack_dir=packs[1])
    record = next(
        row for row in catalog.records if row.id == "S001" and row.scope != "builtin"
    )
    assert any(row.value == "90" and row.state == "overridden" for row in record.values)
    assert any(
        row.value == "13" and row.state == "map-evidence" for row in record.values
    )


def test_column_marker_never_misreads_a_level_or_invalid_signed_column() -> None:
    from gametool.object_layers import split_field_column
    from gametool.object_text_roles import classify_text_field

    assert split_field_column("Istr:5:column:2") == ("Istr:5", "2")
    assert split_field_column("Istr:5:column:-+2") == ("Istr:5:column:-+2", None)
    column = "9" * 5000
    assert split_field_column("Istr:5:column:" + column) == ("Istr:5", column)
    role = classify_text_field("技能", "aub1:5:column:2", "")
    assert role is not None and role.level == 5
