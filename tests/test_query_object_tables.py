"""Header-aware object identities, complete legacy rows and attributable diagnostics."""

import csv
import json
import os
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_options import PackQueryCliOptions

_TABLES = ("物品", "单位", "技能", "英雄", "增益", "科技", "装饰物", "可破坏物")
_HEADER = ["分类", "ID", "10进制", "基础ID", "名称", "自定义", "说明"]


@pytest.fixture(autouse=True)
def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _write(pack: Path, table: str, rows: list[list[str]]) -> Path:
    folder = pack / "对象ID"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{table}.tsv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t", lineterminator="\n").writerows(rows)
    return path


def _layout(table: str, layout: str) -> list[list[str]]:
    row = [table, "n001", "123", "hfoo", "真实目标", "是", "完整效果末尾"]
    if layout == "canonical":
        return [_HEADER, row]
    if layout == "reordered":
        order = [4, 6, 5, 1, 2, 0, 3]
        return [[_HEADER[i] for i in order], [row[i] for i in order]]
    if layout == "english":
        categories: dict[str, str] = dict(
            zip(
                _TABLES,
                (
                    "items",
                    "units",
                    "abilities",
                    "heroes",
                    "buffs",
                    "tech",
                    "doodads",
                    "destructables",
                ),
            )
        )
        row[0] = categories[table]
        return [
            ["NAME", "DESCRIPTION", "ID", "BASE_ID", "DECIMAL", "CATEGORY", "CUSTOM"],
            [row[i] for i in [4, 6, 1, 3, 2, 0, 5]],
        ]
    if layout == "six":
        return [[*_HEADER[:5], "说明"], [*row[:5], row[6]]]
    if layout == "minimal":
        return [["ID", "名称"], [row[1], row[4]]]
    if layout == "headerless7":
        return [row]
    if layout == "headerless5":
        return [row[:5]]
    if layout == "legacy_named":
        return [[table, "四码", "数值", "四码2", "名称", "英雄", "描述"], row]
    if layout == "legacy_reordered":
        return [
            [table, "NAME", "DECIMAL", "ID", "四码2", "描述"],
            [table, row[4], row[2], row[1], row[3], row[6]],
        ]
    return [[], [" ", "\t"], ["\ufeff"], ["\ufeff 分类 ", " ID ", *_HEADER[2:]], [*row]]


@pytest.mark.parametrize("table", _TABLES)
@pytest.mark.parametrize(
    "layout",
    [
        "canonical",
        "reordered",
        "english",
        "six",
        "minimal",
        "headerless7",
        "headerless5",
        "legacy_named",
        "legacy_reordered",
        "bom",
    ],
)
def test_all_tables_keep_the_first_correct_identity_across_supported_layouts(
    tmp_path: Path, table: str, layout: str
) -> None:
    _write(tmp_path, table, _layout(table, layout))
    for command, query in [("search", table + ":n001"), ("list", table)]:
        result = queries.execute_pack_query(
            PackQueryCliOptions(str(tmp_path), command, query)
        )
        assert (
            result.exit_code == 0
            and "n001" in result.render()
            and "真实目标" in result.render()
        )
        assert not json.loads(result.render(as_json=True))["warnings"]
    commands = {"单位": "units", "技能": "skills", "英雄": "heroes", "增益": "buffs"}
    if table in commands:
        result = queries.execute_pack_query(
            PackQueryCliOptions(str(tmp_path), commands[table], "n001")
        )
        assert result.exit_code == 0 and "[n001] 真实目标" in result.render()
        if layout not in {"minimal", "headerless5"}:
            assert "完整效果末尾" in result.render()
    if table == "物品":
        assert queries.load_items(tmp_path)["n001"][0] == "真实目标"
        assert queries.load_item_bases(tmp_path).get("n001", "") == (
            "" if layout == "minimal" else "hfoo"
        )
    if table == "单位":
        assert queries.load_units(tmp_path) == {"n001": "真实目标"}
    if table == "可破坏物":
        assert queries.load_destructables(tmp_path) == {"n001": "真实目标"}
    if table == "科技":
        assert queries.load_techs(tmp_path) == {
            "n001": ("真实目标", "" if layout == "minimal" else "hfoo")
        }


@pytest.mark.parametrize("command", ["search", "units", "list"])
@pytest.mark.parametrize(
    "header", [["分类", "ID", "ID", "名称"], ["分类", "名称"], ["分类", "ID"]]
)
def test_ambiguous_or_missing_key_columns_are_diagnostics_not_fake_objects(
    tmp_path: Path, command: str, header: list[str]
) -> None:
    _write(tmp_path, "单位", [header, ["单位", "n001", "n002", "真实目标"]])
    query = "单位" if command == "list" else "n001"
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), command, query)
    )
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 2 and data["warnings"]
    assert "对象ID/单位.tsv" in data["warnings"][0]
    assert "未猜测列身份" in result.render()
    assert not queries.load_units(tmp_path)


def test_optional_blank_and_duplicate_extra_headers_retain_field_boundaries(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "单位",
        [
            [*_HEADER, "", "证据", "证据"],
            [
                "单位",
                "n001",
                "123",
                "hfoo",
                "真实目标",
                "是",
                "说明",
                "空名扩展",
                "证据甲",
                "证据乙",
            ],
        ],
    )
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "search", "空名扩展 && 证据甲 && 证据乙")
    )
    text = result.render()
    assert result.exit_code == 0 and "扩展字段8: 空名扩展" in text
    assert "证据 (第9列): 证据甲" in text and "证据 (第10列): 证据乙" in text
    assert (
        queries.execute_pack_query(
            PackQueryCliOptions(str(tmp_path), "search", '="证据甲 证据乙"')
        ).exit_code
        == 2
    )


def test_invalid_records_do_not_inflate_counts_or_become_unicode_rawcodes(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "单位",
        [
            _HEADER,
            ["单位", "n001", "1", "hfoo", "真实目标", "是", "说明"],
            ["单位", "bad"],
            ["单位", "汉字四码", "1", "hfoo", "伪对象"],
            ["物品", "n002", "1", "hfoo", "错分类"],
        ],
    )
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "list", "单位")
    )
    assert "== 单位 (1) ==" in result.render() and "[n001]" in result.render()
    assert "3 行字段不完整" in result.render() and "3, 4, 5" in result.render()
    assert queries.load_units(tmp_path) == {"n001": "真实目标"}


def test_header_change_with_preserved_identity_metadata_invalidates_the_view(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, "单位", _layout("单位", "reordered"))
    before = path.stat()
    first = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "units", "n001")
    )
    original = path.read_bytes()
    updated = original.replace("真实目标".encode(), "更新目标".encode())
    assert len(original) == len(updated)
    path.write_bytes(updated)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    second = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "units", "n001")
    )
    assert "真实目标" in first.render() and "更新目标" in second.render()


def test_reordered_names_feed_near_and_original_columns_remain_unchanged(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, "单位", _layout("单位", "reordered"))
    before = path.read_bytes()
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "war3map.lua").write_text(
        "CreateUnit(Player(0),FourCC('n001'),1,2,0)", encoding="utf-8"
    )
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "1 2 0")
    )
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 0 and data["entries"][0]["name"] == "真实目标"
    assert data["entries"][0]["code"] == "n001" and path.read_bytes() == before


def test_5000_legacy_objects_and_the_last_malformed_record_are_all_consumed(
    tmp_path: Path,
) -> None:
    rows = [
        ["单位", chr(ord("n") + i // 4096) + f"{i % 4096:03x}", "1", "hfoo", f"目标{i}"]
        for i in range(5000)
    ]
    rows.append(["单位", "bad"])
    _write(tmp_path, "单位", rows)
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "units", "", limit=1)
    )
    assert result.exit_code == 0 and "其余 4999 条未显示" in result.render()
    assert "记录序号: 5001" in result.render()


def test_key_columns_after_2000_extra_columns_have_no_scan_ceiling(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "单位",
        [
            [*(f"字段{i}" for i in range(2000)), "ID", "名称"],
            [*(f"值{i}" for i in range(2000)), "n001", "真实目标"],
        ],
    )
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "search", "n001", limit=1)
    )
    assert (
        result.exit_code == 0
        and "真实目标" in result.render()
        and "字段1999: 值1999" in result.render()
    )


def test_object_diagnostics_are_restored_and_do_not_leak_to_other_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = {"preserve": ["old"]}
    monkeypatch.setattr(queries, "_QUERY_OBJECT_WARNINGS", sentinel)
    _write(tmp_path, "单位", [["ID", "ID", "名称"], ["n001", "n002", "冲突"]])
    first = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "search", "n001")
    )
    assert first.exit_code == 2 and queries._QUERY_OBJECT_WARNINGS is sentinel
    _write(tmp_path, "单位", _layout("单位", "canonical"))
    second = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "search", "n001")
    )
    assert (
        second.exit_code == 0
        and not json.loads(second.render(as_json=True))["warnings"]
    )
    assert queries._QUERY_OBJECT_WARNINGS is sentinel


def test_diagnostics_are_displayed_once_but_remain_structured(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path, "单位", [["ID", "ID", "名称"], ["n001", "n002", "冲突"]])
    options = PackQueryCliOptions(str(tmp_path), "search", "n001")
    result = queries.execute_pack_query(options)
    assert json.loads(result.render(as_json=True))["warnings"]
    assert not any(note.startswith("[⚠") for note in result.extra_diagnostics)
    assert queries.run_pack_query_cli(options) == 2
    captured = capsys.readouterr()
    assert (captured.out + captured.err).count("重复语义列") == 1


def test_sparse_rows_do_not_materialize_unencoded_extra_cells(tmp_path: Path) -> None:
    rows = [["ID", "名称", *(f"字段{i}" for i in range(2000))]]
    rows.extend([[f"n{i:03x}", "真实目标"] for i in range(1000)])
    _write(tmp_path, "单位", rows)
    result = queries.execute_pack_query(PackQueryCliOptions(str(tmp_path), "units", ""))
    normalized = queries._object_rows(tmp_path, "单位")
    assert result.exit_code == 0 and result.render().count("真实目标") == 1000
    assert sum(map(len, normalized)) <= sum(map(len, rows)) + len(rows) * 7


def test_column_reordering_is_not_reported_as_an_object_value_change(
    tmp_path: Path,
) -> None:
    row = [
        "单位",
        "n001",
        "123",
        "hfoo",
        "真实目标",
        "是",
        "完整说明",
        "English Name",
        "source",
    ]
    header = [*_HEADER, "英文名", "来源证据"]
    _write(tmp_path / "old", "单位", [header, row])
    order = [7, 4, 6, 5, 1, 8, 2, 0, 3]
    _write(
        tmp_path / "new", "单位", [[header[i] for i in order], [row[i] for i in order]]
    )
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path / "new"), "diff", str(tmp_path / "old"))
    )
    assert result.exit_code == 0 and result.render() == "两包对象表无差异"


def test_header_like_rawcode_never_makes_a_fake_first_object(tmp_path: Path) -> None:
    _write(tmp_path, "单位", [["单位", "NAME", "123", "hfoo", "ID"]])
    result = queries.execute_pack_query(PackQueryCliOptions(str(tmp_path), "units", ""))
    assert result.exit_code == 2 and "未猜测对象身份" in result.render()
    assert "[NAME]" not in result.render()


def test_generated_labels_do_not_hide_a_named_extra_column(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "单位",
        [
            [*_HEADER, "", "扩展字段8"],
            [
                "单位",
                "n001",
                "1",
                "hfoo",
                "真实目标",
                "是",
                "说明",
                "无名证据",
                "有名证据",
            ],
        ],
    )
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "search", "无名证据 && 有名证据")
    )
    assert result.exit_code == 0
    assert "扩展字段8 (原列8): 无名证据" in result.render()
    assert "扩展字段8 (原列9): 有名证据" in result.render()


def test_campaign_schema_diagnostics_keep_their_own_map_section(tmp_path: Path) -> None:
    good = tmp_path / "子地图" / "001"
    bad = tmp_path / "子地图" / "002"
    _write(good, "单位", _layout("单位", "headerless7"))
    _write(bad, "单位", [["ID", "ID", "名称"], ["n001", "n002", "冲突"]])
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "search", "n001")
    )
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 0 and result.campaign and len(data["sections"]) == 2
    assert (
        data["sections"][1]["pack"] == str(bad)
        and data["sections"][1]["section"] == "子地图 002"
    )
    assert "重复语义列" not in "\n".join(data["sections"][0]["lines"])
    assert "重复语义列" in "\n".join(data["sections"][1]["lines"])


def test_diagnostic_only_campaign_never_overwrites_successful_memory(
    tmp_path: Path,
) -> None:
    good = tmp_path / "good"
    _write(good, "单位", _layout("单位", "canonical"))
    assert (
        queries.execute_pack_query(
            PackQueryCliOptions(str(good), "search", "n001")
        ).exit_code
        == 0
    )
    memo = queries._memo_dir() / queries._LAST_QUERY_FILE
    before = memo.read_bytes()
    campaign = tmp_path / "campaign"
    for name in ["001", "002"]:
        _write(
            campaign / "子地图" / name,
            "单位",
            [["ID", "ID", "名称"], ["n001", "n002", "冲突"]],
        )
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(campaign), "search", "n001")
    )
    data = json.loads(result.render(as_json=True))
    assert result.exit_code == 2 and result.campaign and len(data["warnings"]) == 2
    assert len(data["sections"]) == 3 and memo.read_bytes() == before


def test_concurrent_queries_do_not_share_object_schema_warnings(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    good, bad = tmp_path / "good", tmp_path / "bad"
    _write(good, "单位", _layout("单位", "reordered"))
    _write(bad, "单位", [["ID", "ID", "名称"], ["n001", "n002", "冲突"]])

    def run(pack: Path):
        result = queries.execute_pack_query(
            PackQueryCliOptions(str(pack), "search", "n001")
        )
        return result.exit_code, json.loads(result.render(as_json=True))["warnings"]

    paths = [good, bad] * 10
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(run, paths))
    assert all(
        (code == 0 and not warnings)
        if pack == good
        else (code == 2 and len(warnings) == 1)
        for pack, (code, warnings) in zip(paths, results)
    )


@pytest.mark.parametrize("layout", ["canonical", "legacy_named"])
def test_legacy_category_labels_are_not_reinterpreted_as_extra_text(
    tmp_path: Path, layout: str
) -> None:
    _write(tmp_path, "单位", _layout("单位", layout))
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "search", "单位")
    )
    assert (
        result.exit_code == 2
        and not json.loads(result.render(as_json=True))["warnings"]
    )


def test_multibyte_text_is_never_promoted_to_a_base_object_code(tmp_path: Path) -> None:
    for table in ("物品", "科技"):
        _write(
            tmp_path,
            table,
            [_HEADER, [table, "n001", "123", "基础对象", "真实目标", "是", "说明"]],
        )
    assert queries.load_item_bases(tmp_path) == {}
    assert queries.load_techs(tmp_path) == {"n001": ("真实目标", "")}
