"""Relation queries share declared columns and complete source evidence."""

from __future__ import annotations

import csv
from importlib import import_module
import json
import os
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.item_relation_exports import ACQUISITION_REPORT_HEADER
from gametool.pack_query_options import PackQueryCliOptions


@pytest.fixture(autouse=True)
def isolated_memo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _row(kind: str = "商店出售", code: str = "I001") -> list[str]:
    row = [""] * len(ACQUISITION_REPORT_HEADER)
    for index, value in {
        0: "relation-1",
        1: "关卡",
        2: kind,
        3: code,
        4: "货物",
        5: "单位",
        6: "u001",
        7: "来源单位",
        8: "17",
        10: "10.25",
        11: "-20.5",
        17: "I002",
        18: "材料×3",
        19: "war3map.w3u",
        20: "Owner",
        21: "field @0x40",
        22: "完整原文\n下一行",
        23: "已确认",
        24: "完整",
    }.items():
        row[index] = value
    return row


def _pack(pack: Path, header: list[str], rows: list[list[str]]) -> None:
    objects = pack / "对象ID"
    objects.mkdir(parents=True, exist_ok=True)
    (objects / "物品.tsv").write_text(
        "ID\t名称\nI001\t货物\nI002\t材料\n", encoding="utf-8"
    )
    (objects / "单位.tsv").write_text("ID\t名称\nu001\t来源单位\n", encoding="utf-8")
    (pack / "预放置单位.tsv").write_text(
        "序号\t类型ID\t名称\t玩家\tX\tY\tZ\n17\tu001\t来源单位\t0\t10.25\t-20.5\t0\n",
        encoding="utf-8",
    )
    with (pack / "掉落与获取关系.tsv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        csv.writer(stream, delimiter="\t").writerows(
            ([header] if header else []) + rows
        )


def _query(pack: Path, command: str, query: str = "I001", limit: int = 0):
    return queries.execute_pack_query(
        PackQueryCliOptions(str(pack), command, query, limit=limit)
    )


@pytest.mark.parametrize("command", ["where", "drop", "shop"])
@pytest.mark.parametrize("english", [False, True])
def test_reordered_relations_keep_identity_provenance_and_extension_fields(
    tmp_path: Path, command: str, english: bool
) -> None:
    header: list[str] = list(ACQUISITION_REPORT_HEADER)
    if english:
        aliases = {
            2: "relation_type",
            3: "item_id",
            4: "item_name",
            5: "source_category",
            6: "source_id",
            7: "source_name",
            10: "x",
            11: "y",
            19: "evidence_file",
            21: "evidence_position",
        }
        for index, value in aliases.items():
            header[index] = value
    header.append("额外说明")
    row = [*_row(), "扩展完整\n第二行"]
    _pack(tmp_path, header[::-1], [row[::-1]])
    result = _query(tmp_path, command, "u001" if command == "shop" else "I001", limit=1)
    output = result.render()
    assert result.exit_code == 0 and "货物" in output
    assert "war3map.w3u" in output and "field @0x40" in output
    assert "额外说明" in output and "扩展完整" in output and "第二行" in output
    assert "完整原文" in output and "下一行" in output


@pytest.mark.parametrize("command", ["recipe", "synth"])
@pytest.mark.parametrize("english", [False, True])
def test_recipe_queries_accept_declared_product_and_material_columns(
    tmp_path: Path, command: str, english: bool
) -> None:
    header = [
        "关系类型",
        "装备ID",
        "装备名称",
        "合成材料ID",
        "合成材料名称与数量",
        "额外说明",
    ]
    if english:
        header = [
            "kind",
            "product_id",
            "product_name",
            "material_ids",
            "material_text",
            "extra",
        ]
    _pack(
        tmp_path, header, [["合成", "I001", "货物", "I002", "材料×3", "全部配方证据"]]
    )
    output = _query(tmp_path, command).render()
    assert "货物" in output and "材料×3" in output and "全部配方证据" in output


@pytest.mark.parametrize("command", ["where", "drop", "shop"])
def test_missing_optional_names_do_not_erase_confirmed_identities(
    tmp_path: Path, command: str
) -> None:
    _pack(
        tmp_path,
        ["来源ID", "装备ID", "来源分类", "关系类型"],
        [["u001", "I001", "单位", "商店出售"]],
    )
    output = _query(tmp_path, command, "u001" if command == "shop" else "I001").render()
    assert "I001" in output and "u001" in output and "未找到" not in output


def test_near_reads_reordered_category_qualified_drop_evidence(tmp_path: Path) -> None:
    _pack(
        tmp_path,
        ["来源ID", "关系类型", "装备名称", "装备ID", "来源分类"],
        [["u001", "怪物直接掉落", "货物", "I001", "unit"]],
    )
    result = _query(tmp_path, "near", "10.25 -20.5 1")
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 0 and data["entries"][0]["drops"] == "货物[I001]"


@pytest.mark.parametrize("code", ["I001", "i001", "i!é?"])
def test_headerless_first_record_and_all_encoded_extra_cells_are_preserved(
    code: str,
) -> None:
    parser = import_module("gametool.pack_query_relation_records")
    raw = [*_row(code=code), "extra-one", "", "extra-three"]
    index = parser.acquisition_index((tuple(raw),))
    assert len(index.records) == 1 and index.records[0][3] == code
    assert index.records[0].raw == tuple(raw) and index.records[0].ordinal == 1
    assert [value for _key, value in index.records[0].extensions] == raw[28:]


def test_sparse_row_never_pads_to_declared_header_width() -> None:
    parser = import_module("gametool.pack_query_relation_records")
    raw = (
        ("关系类型", "装备ID", *("扩展" + str(i) for i in range(20000))),
        ("脚本奖励", "I001"),
    )
    index = parser.acquisition_index(raw)
    assert len(index.records) == 1 and len(index.records[0]) == 28
    assert index.records[0].raw == raw[1] and not index.records[0].extensions
    assert not index.diagnostics


def test_duplicate_roles_keep_full_source_diagnostics_without_guessing(
    tmp_path: Path,
) -> None:
    raw = ["商店出售", "I001", "I002", "u001", "原始保留" * 1000]
    header = ["关系类型", "装备ID", "item_id", "来源ID", "扩展"]
    _pack(tmp_path, header, [raw])
    result = _query(tmp_path, "shop", "u001", limit=1)
    data = json.loads(result.render(as_json=True))
    assert data["warnings"] and "重复" in data["warnings"][0]
    assert json.dumps(raw, ensure_ascii=False) in "\n".join(data["warnings"])
    assert str(tmp_path) in "\n".join(data["warnings"]) and "text" in result.render()
    assert "制造 货物" not in result.render()


def test_invalid_rows_do_not_hide_valid_rows_and_diagnostics_are_not_limited(
    tmp_path: Path,
) -> None:
    bad = [["商店出售", "too-long", "u001", "bad-" + str(i)] for i in range(30)]
    _pack(
        tmp_path,
        ["关系类型", "装备ID", "来源ID", "扩展"],
        [["商店出售", "I001", "u001", "confirmed"], *bad],
    )
    data = json.loads(_query(tmp_path, "shop", "u001", limit=1).render(as_json=True))
    assert "I001" in "\n".join(data["lines"])
    assert all(
        json.dumps(row, ensure_ascii=False) in "\n".join(data["warnings"])
        for row in bad
    )


def test_normalization_preserves_raw_cache_and_content_fingerprints(
    tmp_path: Path,
) -> None:
    header = ["装备ID", "关系类型", "来源ID", "来源名称"]
    _pack(tmp_path, header, [["I001", "商店出售", "u001", "source-A"]])
    original = [
        row.copy() for row in queries._read_rows(tmp_path, "掉落与获取关系.tsv")
    ]
    assert "source-A" in _query(tmp_path, "shop", "u001").render()
    assert queries._read_rows(tmp_path, "掉落与获取关系.tsv") == original
    path = tmp_path / "掉落与获取关系.tsv"
    info = path.stat()
    path.write_bytes(path.read_bytes().replace(b"source-A", b"source-B"))
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
    assert "source-B" in _query(tmp_path, "shop", "u001").render()


def test_diagnostic_only_campaign_relation_scope_is_retained(tmp_path: Path) -> None:
    child = tmp_path / "子地图" / "001"
    _pack(child, ["关系类型", "装备ID", "item_id"], [["怪物直接掉落", "I001", "I002"]])
    (child / "预放置单位.tsv").unlink()
    result = _query(tmp_path, "near", "0 0 1")
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 2 and not data["entries"]
    assert str(child) in data["checked_packs"]
    assert any(section["pack"] == str(child) for section in data["sections"])
    assert data["spatial_diagnostics"] and "重复" in result.render()


def test_large_relation_set_has_no_record_or_extension_ceiling() -> None:
    parser = import_module("gametool.pack_query_relation_records")
    raw = (
        ("装备ID", "关系类型", "扩展"),
        *(("I001", "脚本奖励", "证据-" + str(i)) for i in range(4000)),
    )
    index = parser.acquisition_index(raw)
    assert len(index.records) == 4000 and index.records[-1].ordinal == 4001
    assert index.records[-1].extensions == (("扩展", "证据-3999"),)


@pytest.mark.parametrize("command", ["recipe", "synth"])
def test_recipe_mirrors_keep_every_independent_source_under_one_result(
    tmp_path: Path, command: str
) -> None:
    first, second = _row("合成"), _row("合成")
    second[19], second[22] = "other.lua", "不同来源的完整配方证据"
    _pack(tmp_path, list(ACQUISITION_REPORT_HEADER), [first, second, first])
    output = _query(tmp_path, command, limit=1).render()
    assert "war3map.w3u" in output and "other.lua" in output
    assert "不同来源的完整配方证据" in output and "其余" not in output


def test_different_material_ids_are_separate_complete_recipe_records(
    tmp_path: Path,
) -> None:
    first, second = _row("合成"), _row("合成")
    second[17] = "I003"
    _pack(tmp_path, list(ACQUISITION_REPORT_HEADER), [first, second])
    result = _query(tmp_path, "recipe", limit=1)
    assert "其余 1 条" in result.render() and "I003" not in result.render()
    assert "I003" in _query(tmp_path, "recipe").render()


@pytest.mark.parametrize("command", ["recipe", "synth"])
def test_material_ids_without_quantity_text_keep_query_recovery(
    tmp_path: Path, command: str
) -> None:
    _pack(
        tmp_path,
        ["relation_type", "product_id", "material_ids"],
        [["recipe", "I001", "I002"]],
    )
    output = _query(tmp_path, command).render()
    assert "I001" in output and "I002" in output and "数量未记录" in output


def test_known_legacy_prefix_keeps_encoded_tail_without_padding_raw_rows() -> None:
    parser = import_module("gametool.pack_query_relation_records")
    row = _row("脚本/触发奖励")[:26]
    row[5:8] = ["", "", ""]
    result = parser.acquisition_index(
        (tuple(ACQUISITION_REPORT_HEADER[:20]), tuple(row))
    )
    assert len(result.records) == 1 and result.records[0][20:23] == tuple(row[20:23])
    assert result.records[0].raw == tuple(row) and not result.diagnostics


def test_english_candidate_state_never_becomes_confirmed_near_drop(
    tmp_path: Path,
) -> None:
    _pack(
        tmp_path,
        [
            "kind",
            "item_id",
            "source_id",
            "source_category",
            "confidence",
            "completeness",
        ],
        [["unit_drop", "I001", "u001", "unit", "clue", "conflict"]],
    )
    result = _query(tmp_path, "near", "10.25 -20.5 1")
    data = json.loads(result.render(as_json=True))
    assert data["entries"][0]["drops"] is None and data["warnings"]


def test_embedded_bom_and_quoted_newlines_keep_original_contents() -> None:
    parser = import_module("gametool.pack_query_relation_records")
    raw = (
        ("item_id", "kind", "extra"),
        ("I001", "script_grant", 'embedded\ufeff"quote"\r\nnext'),
    )
    record = parser.acquisition_index(raw).records[0]
    assert record.raw == raw[1] and record.extensions[0][1] == raw[1][2]


def test_embedded_bom_in_declared_role_is_not_erased_or_guessed() -> None:
    parser = import_module("gametool.pack_query_relation_records")
    raw = (("\ufeffkind", "item_id"), ("recipe", "I001"))
    index = parser.acquisition_index(raw)
    assert not index.records and index.diagnostic_ordinals == (1, 2)
    assert json.dumps(raw[0], ensure_ascii=False) in index.diagnostics[0]


def test_recipe_diff_uses_same_columns_and_preserves_incomplete_diagnostics(
    tmp_path: Path,
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    _pack(
        old,
        ["product_id", "kind", "material_ids", "materials"],
        [["I001", "recipe", "I002", "材料×3"]],
    )
    _pack(
        new,
        ["materials", "material_ids", "kind", "product_id"],
        [["材料×4", "I002", "recipe", "I001"]],
    )
    result = _query(new, "diff", str(old))
    assert (
        result.exit_code == 0
        and "材料×3" in result.render()
        and "材料×4" in result.render()
    )
