"""Field reference parsing keeps real four-byte identities across map and query."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.batch_tsv import decode_tsv_cell, format_tsv_rows
from gametool.doo import Unit
from gametool.guide_report import _shop_lines
from gametool.item_relation_builder import build_item_relation_index
from gametool.item_relation_field_variants import split_relation_codes
from gametool.item_relation_models import ItemRelationKind, RelationCompleteness
from gametool.item_relation_exports import ACQUISITION_REPORT_HEADER
from gametool.knowledge_pack import write_knowledge_pack
from gametool.knowledge_object_exports import format_object_fields, write_object_ids
from gametool.map_data import GameObject, GameObjectFieldEvidence, MapData
from gametool.pack_query_options import PackQueryCliOptions
from gametool.pack_query_objects import object_field_table, object_table
from gametool.pack_query_relation_records import acquisition_index
from io import StringIO

_CODES = ("1234", "0000", "____", "----", "i!é?", "i|!?", "a(b?", "a)b?")
_ROLES = {
    "Sellitems": ItemRelationKind.SHOP_SELL,
    "Makeitems": ItemRelationKind.SHOP_MAKE,
    "iabi": ItemRelationKind.ITEM_ABILITY,
    "icid": ItemRelationKind.COOLDOWN_ABILITY,
}


@pytest.fixture(autouse=True)
def isolated_memo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _object(category: str, code: str, name: str) -> GameObject:
    return GameObject(
        category,
        "w3t" if category == "物品" else "w3a" if category == "技能" else "w3u",
        code,
        code,
        name,
        True,
    )


def _map(
    code: str = "1234",
    key: str = "Sellitems",
    *,
    evidence: bool = True,
    raw: str | None = None,
) -> MapData:
    item = _object("物品", code, "目标物品")
    skill = _object("技能", code, "目标技能")
    carrier = _object("物品", "Isrc", "携带物品")
    shop = _object("单位", "n001", "目标商店")
    owner = shop if key in ("Sellitems", "Makeitems") else carrier
    value = raw if raw is not None else "名称(含括号)尾部(" + code + ")"
    owner.fields = [(key, value)]
    owner.field_values = {key: value}
    owner.field_sources = {key: "war3map.w3u" if owner is shop else "war3map.w3t"}
    owner.field_labels = {key: "完整字段"}
    if evidence:
        owner.field_evidence = (
            GameObjectFieldEvidence(
                key,
                "完整字段",
                "展开后的名称",
                owner.field_sources[key],
                100,
                raw_value=value,
            ),
        )
    md = MapData("read-only-input.w3x", "完整四码关系")
    md.objects = {"物品": [item, carrier], "技能": [skill], "单位": [shop]}
    values = [obj for objects in md.objects.values() for obj in objects]
    md.obj_identity_index = {(obj.category, obj.obj_id): obj for obj in values}
    md.obj_index = {obj.obj_id: obj for obj in values}
    md.units = [
        Unit("n001", 0, 1.25, -2.5, 3.0, 0.0, serial=7, source_offset=64),
        Unit("n001", 0, 10.25, -20.5, 4.0, 0.0, serial=8, source_offset=128),
    ]
    return md


@pytest.mark.parametrize("code", _CODES)
@pytest.mark.parametrize("named", [False, True])
def test_native_and_query_field_references_share_every_four_byte_identity(
    code: str, named: bool
) -> None:
    value = "旧名(前缀括号)(" + code + ")" if named else code
    assert split_relation_codes(value) == (code,)
    assert queries._field_object_codes(value) == [code]


@pytest.mark.parametrize("code", ["1234", "0000", "i|!?", "i!é?"])
@pytest.mark.parametrize("key", tuple(_ROLES))
@pytest.mark.parametrize("evidence", [False, True])
def test_map_relations_keep_named_numeric_and_punctuation_endpoints(
    code: str, key: str, evidence: bool
) -> None:
    md = _map(code, key, evidence=evidence)
    records = build_item_relation_index(md).for_kind(_ROLES[key])
    assert len(records) == (2 if key in ("Sellitems", "Makeitems") else 1)
    assert all(
        (record.skill.object_id if record.skill is not None else record.item.object_id)
        == code
        for record in records
    )
    assert all(
        record.completeness == RelationCompleteness.COMPLETE for record in records
    )
    assert all(
        record.evidence.raw == "名称(含括号)尾部(" + code + ")" for record in records
    )
    assert all(record.evidence.source.startswith("war3map.") for record in records)


@pytest.mark.parametrize("value", ["物品甲乙", "😀abc", "Ａ001", "α001"])
def test_non_latin1_text_cannot_become_a_four_byte_object_identity(value: str) -> None:
    assert split_relation_codes(value) == ()
    assert queries._field_object_codes(value) == []


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1234,名称(i!é?),i|!?", ("1234", "i!é?", "i|!?")),
        ("1234|i!é?|I001", ("1234", "i!é?", "I001")),
        ("甲(1234)|乙(i!é?)", ("1234", "i!é?")),
        ("带,逗号名称(1234),I001", ("1234", "I001")),
        ("i,01,I002", ("i,01", "I002")),
        ("名称(i,01),I002", ("i,01", "I002")),
        ("|cffff0000红色|r(I001),i|!?", ("I001", "i|!?")),
    ],
)
def test_lists_keep_terminal_names_delimiters_inside_identities_and_legacy_pipes(
    raw: str, expected: tuple[str, ...]
) -> None:
    assert split_relation_codes(raw) == expected
    assert queries._field_object_codes(raw) == list(expected)


def test_case_sensitive_codes_and_duplicate_policy_remain_explicit() -> None:
    value = "I001,i001,I001,名称(i001)"
    assert split_relation_codes(value) == ("I001", "i001")
    assert queries._field_object_codes(value) == ["I001", "i001", "I001", "i001"]


def test_long_names_do_not_limit_or_rescan_complete_source_prefixes() -> None:
    value = ("名称," * 40000) + "尾部(1234),i|!?"
    assert split_relation_codes(value) == ("1234", "i|!?")
    assert queries._field_object_codes(value) == ["1234", "i|!?"]


def test_complete_list_has_no_count_ceiling_and_deduplicates_in_source_order() -> None:
    codes = tuple(f"{i:04X}" for i in range(1, 2001))
    raw = ",".join((*codes, *codes))
    assert split_relation_codes(raw) == codes
    assert queries._field_object_codes(raw) == [*codes, *codes]


@pytest.mark.parametrize("code", ["1234", "i!é?", "i|!?", "i,01"])
def test_relation_export_and_queries_preserve_the_same_identity_and_instances(
    tmp_path: Path, code: str
) -> None:
    md = _map(code)
    md.item_relations = build_item_relation_index(md)
    pack = tmp_path / "pack"
    write_knowledge_pack(md, str(pack))
    with (pack / "掉落与获取关系.tsv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    sells = [row for row in rows if row["关系类型"] == "商店出售"]
    assert len(sells) == 2 and all(row["装备ID"] == code for row in sells)
    assert {
        (decode_tsv_cell(row["X"]), decode_tsv_cell(row["Y"])) for row in sells
    } == {
        ("1.25", "-2.5"),
        ("10.25", "-20.5"),
    }
    for command, query in (("where", code), ("shop", "n001"), ("near", "1.25 -2.5 1")):
        result = queries.execute_pack_query(
            PackQueryCliOptions(str(pack), command, query)
        )
        assert result.exit_code == 0 and code in result.render(), (
            command,
            result.render(),
        )
    guide = "\n".join(_shop_lines(md))
    assert "目标商店" in guide and "目标物品" in guide
    assert all(value in guide for value in ("1.25", "-2.5", "10.25", "-20.5"))


@pytest.mark.parametrize("code", ["1234", "i!é?", "i|!?"])
def test_missing_definitions_keep_field_evidence_as_unresolved_relations(
    code: str,
) -> None:
    md = _map(code)
    md.objects["物品"] = [obj for obj in md.objects["物品"] if obj.obj_id != code]
    md.obj_identity_index.pop(("物品", code))
    if md.obj_index.get(code) is not None and md.obj_index[code].category == "物品":
        md.obj_index.pop(code)
    rows = build_item_relation_index(md).for_kind(ItemRelationKind.SHOP_SELL)
    assert len(rows) == 2 and all(row.item.object_id == code for row in rows)
    assert all(row.completeness == RelationCompleteness.UNRESOLVED for row in rows)
    assert all(code in row.evidence.raw for row in rows)


@pytest.mark.parametrize("code", ["-123", "+123", "=123", "@123", "----"])
def test_spreadsheet_escaped_identities_survive_export_and_query(
    tmp_path: Path, code: str
) -> None:
    md = _map(code)
    md.item_relations = build_item_relation_index(md)
    pack = tmp_path / "pack"
    write_knowledge_pack(md, str(pack))
    for command, query in (
        ("where", code),
        ("price", '="' + code + '"'),
        ("shop", "n001"),
        ("near", "1.25 -2.5 1"),
    ):
        result = queries.execute_pack_query(
            PackQueryCliOptions(str(pack), command, query)
        )
        assert result.exit_code == 0 and code in result.render(), (
            command,
            result.render(),
        )
        assert not any("不是有效四字节" in line for line in result.diagnostics)


def _serialized(rows: list[tuple[str, ...]]) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(row)
        for row in csv.reader(
            StringIO(format_tsv_rows(rows), newline=""), delimiter="\t"
        )
    )


@pytest.mark.parametrize("headerless", [False, True])
def test_shared_tables_decode_each_safe_cell_once_without_changing_raw_rows(
    headerless: bool,
) -> None:
    literal = "'\u2060literal"
    ids = [
        ("分类", "ID", "数值", "基础ID", "名称", "自定义", "说明"),
        ("物品", "-123", "1", "@123", literal, "是", "说明"),
    ]
    raw_ids = _serialized(ids[1:] if headerless else ids)
    view = object_table("物品", raw_ids)
    assert view.complete and view.rows[1][1] == "-123"
    assert view.rows[1][3] == "@123" and view.rows[1][4] == literal
    fields = [
        ("分类", "ID", "名称", "字段键", "字段名", "值", "来源", "扩展"),
        ("单位", "-src", "店名", "usei", "货架", "=123", "@source", literal),
    ]
    raw_fields = _serialized(fields[1:] if headerless else fields)
    table = object_field_table(raw_fields)
    assert table.complete and table.rows[1][1] == "-src"
    assert table.rows[1][5:] == ("=123", "@source", literal)
    assert queries._field_object_codes(table.rows[1][5]) == ["=123"]
    assert raw_fields == _serialized(fields[1:] if headerless else fields)
    assert raw_ids == _serialized(ids[1:] if headerless else ids)


def _relation_cells() -> list[str]:
    row = [""] * len(ACQUISITION_REPORT_HEADER)
    for index, value in {
        0: "id",
        2: "商店出售",
        3: "-123",
        4: "货物",
        5: "单位",
        6: "@src",
        7: "店名",
        10: "1.25",
        11: "-2.5",
        19: "war3map.w3u",
        22: "'\u2060原始证据",
        23: "已确认",
        24: "完整",
    }.items():
        row[index] = value
    return row


def test_acquisition_values_decode_once_while_full_encoded_evidence_is_retained() -> (
    None
):
    row = (*_relation_cells(), "=extra")
    raw = _serialized([(*ACQUISITION_REPORT_HEADER, "扩展"), row])
    result = acquisition_index(raw)
    assert not result.diagnostics and len(result.records) == 1
    record = result.records[0]
    assert record[3] == "-123" and record[6] == "@src" and record[11] == "-2.5"
    assert record[22] == "'\u2060原始证据"
    assert record.raw == raw[1]
    assert record.extensions == (("扩展", raw[1][-1]),)
    assert (ACQUISITION_REPORT_HEADER[22], raw[1][22]) in record.evidence


def test_literal_safety_prefix_cannot_be_decoded_twice_into_a_coordinate() -> None:
    row = _relation_cells()
    row[10] = "'\u20601.25"
    raw = _serialized([ACQUISITION_REPORT_HEADER, tuple(row)])
    record = acquisition_index(raw).records[0]
    assert record[10] == row[10]
    label, detail, invalid = queries._shop_position_label(record)
    assert invalid and label == "坐标诊断" and "原始坐标未确认" in detail


def test_literal_safety_prefix_cannot_mint_a_field_reference(tmp_path: Path) -> None:
    literal = "'\u2060I001"
    raw = _serialized(
        [
            ("分类", "ID", "名称", "字段键", "字段名", "值", "来源"),
            ("单位", "n001", "店名", "usei", "货架", literal, "map"),
        ]
    )
    view = object_field_table(raw)
    assert (
        view.rows[1][5] == literal
        and queries._field_object_codes(view.rows[1][5]) == []
    )


def test_object_export_round_trips_complete_cells_with_one_reversible_envelope(
    tmp_path: Path,
) -> None:
    md = _map("-123", raw="-123")
    item = md.objects["物品"][0]
    item.name = '名称\t引号"\r\n第二行'
    shop = md.objects["单位"][0]
    original = "'\u2060完整\t字段\r\n第二行\ufeff末尾"
    shop.field_values["LongField"] = original
    shop.field_labels["LongField"] = "完整\t标签"
    shop.field_sources["LongField"] = "@source"
    serialized = tuple(
        tuple(row)
        for row in csv.reader(
            StringIO(format_object_fields(md), newline=""), delimiter="\t"
        )
    )
    table = object_field_table(serialized)
    row = next(row for row in table.rows[1:] if row[3] == "LongField")
    assert row[4:7] == ("完整\t标签", original, "@source")
    shelf = next(row for row in table.rows[1:] if row[3] == "Sellitems")
    assert shelf[5] == "-123" and queries._field_object_codes(shelf[5]) == ["-123"]
    write_object_ids(md, str(tmp_path / "对象ID"))
    with (tmp_path / "对象ID/物品.tsv").open(encoding="utf-8", newline="") as stream:
        raw = tuple(tuple(row) for row in csv.reader(stream, delimiter="\t"))
    view = object_table("物品", raw)
    target = next(row for row in view.rows[1:] if row[1] == "-123")
    assert target[4] == item.name


def test_legacy_single_quote_safety_is_decoded_only_in_four_byte_id_roles() -> None:
    raw = (
        ("分类", "ID", "数值", "基础ID", "名称", "自定义", "说明"),
        ("物品", "'-123", "1", "'@123", "保留 '-123 文字", "是", "说明"),
        ("物品", "'=12", "2", "'=12", "四字节原生引号", "是", ""),
    )
    table = object_table("物品", raw)
    assert table.complete
    assert table.rows[1][1] == "-123" and table.rows[1][3] == "@123"
    assert table.rows[1][4] == "保留 '-123 文字"
    assert table.rows[2][1] == "'=12" and table.rows[2][3] == "'=12"


@pytest.mark.parametrize(
    "header",
    [("关系类型", "装备ID", "装备ID", "=扩展"), ("关系类型", "来源ID", "=扩展")],
)
def test_schema_diagnostics_keep_original_encoded_header_cells(
    header: tuple[str, ...],
) -> None:
    raw = _serialized([header])
    result = acquisition_index(raw)
    assert not result.records and result.diagnostics
    assert json.dumps(raw[0], ensure_ascii=False) in result.diagnostics[0]
