"""Whole-table freshness, complete campaign JSON, and isolated GUI queries."""

from __future__ import annotations

import csv
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from gametool import gui_pack_query as gui
from gametool import pack_query_cli as queries
from gametool.pack_query_cli import execute_pack_query


@pytest.fixture(autouse=True)
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    monkeypatch.setattr(queries, "_ROWS_CACHE", {})
    monkeypatch.setattr(queries, "_LOCKED_FILES", set())
    monkeypatch.setattr(queries, "_QUERY_ROWS", None)
    monkeypatch.setattr(queries, "_QUERY_SCRIPTS", None)


def _unit_pack(pack: Path, code: str, x: int, y: int) -> None:
    (pack / "对象ID").mkdir(parents=True)
    (pack / "对象ID" / "单位.tsv").write_text(
        "分类\tID\t数值\t基础ID\t名称\t自定义\t说明\n"
        f"单位\t{code}\t1\t{code}\t目标\t是\t\n",
        encoding="utf-8",
    )
    (pack / "预放置单位.tsv").write_text(
        f"序号\t类型ID\t名称\t玩家\tX\tY\tZ\n1\t{code}\t目标\t0\t{x}\t{y}\t0\n",
        encoding="utf-8",
    )


def test_tail_change_with_preserved_size_and_mtime_invalidates_cache(
    tmp_path: Path,
) -> None:
    path = tmp_path / "table.tsv"
    prefix = "x" * 6000 + "\n"
    path.write_text(prefix + "old\tvalue\n", encoding="utf-8")
    before = path.stat()
    first = queries._read_rows(tmp_path, path.name)
    path.write_text(prefix + "new\tvalue\n", encoding="utf-8")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    second = queries._read_rows(tmp_path, path.name)
    assert first[-1][0] == "old"
    assert second[-1][0] == "new"
    assert first is not second


def test_transient_table_failure_can_recover_in_the_same_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "table.tsv"
    path.write_text("key\tvalue\n", encoding="utf-8")

    def denied(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("temporary lock")

    with monkeypatch.context() as scoped:
        scoped.setattr(queries.hashlib, "file_digest", denied)
        scoped.setattr(queries.time, "sleep", lambda _delay: None)
        assert queries._read_rows(tmp_path, path.name) == []
    assert queries._read_rows(tmp_path, path.name) == [["key", "value"]]
    assert (str(tmp_path), path.name) not in queries._LOCKED_FILES


def test_bad_encoding_does_not_leak_csv_global_limit(tmp_path: Path) -> None:
    (tmp_path / "bad.tsv").write_bytes(b"\xff\n")
    previous = csv.field_size_limit()
    assert queries._read_rows(tmp_path, "bad.tsv") == []
    assert csv.field_size_limit() == previous


def test_each_table_is_validated_once_per_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "table.tsv").write_text("one\ttwo\n", encoding="utf-8")
    calls: list[int] = []
    original = queries.hashlib.file_digest

    def counted(handle, algorithm):
        calls.append(1)
        return original(handle, algorithm)

    def repeated(pack: Path, _query: str, _limit: int) -> list[str]:
        for _ in range(40):
            assert queries._read_rows(pack, "table.tsv") == [["one", "two"]]
        return ["full result"]

    monkeypatch.setattr(queries.hashlib, "file_digest", counted)
    monkeypatch.setitem(queries._QUERIES, "stats", repeated)
    options = queries.PackQueryCliOptions(str(tmp_path), "stats", "")
    assert execute_pack_query(options).exit_code == 0
    assert len(calls) == 1
    assert execute_pack_query(options).exit_code == 0
    assert len(calls) == 2  # Validate again on the next logical query.


def test_campaign_json_is_one_document_with_all_sections_and_coordinates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for index in range(3):
        _unit_pack(tmp_path / "子地图" / f"{index:03}", f"n00{index}", index, 0)
    options = queries.PackQueryCliOptions(str(tmp_path), "near", "0 0 10", as_json=True)
    assert queries.run_pack_query_cli(options) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["section"] == "战役"
    assert len(payload["sections"]) == 3
    assert {row["code"] for row in payload["entries"]} == {"n000", "n001", "n002"}
    assert all(section["entries"] for section in payload["sections"])
    assert all(row["section"].startswith("子地图 ") for row in payload["entries"])


def test_again_keeps_campaign_aggregation_and_original_memory(tmp_path: Path) -> None:
    for index in range(2):
        _unit_pack(tmp_path / "子地图" / f"{index:03}", f"n00{index}", index, 0)
    first = execute_pack_query(
        queries.PackQueryCliOptions(str(tmp_path), "near", "0 0 10")
    )
    memo = queries._memo_dir() / queries._LAST_QUERY_FILE
    previous = memo.read_bytes()
    again = execute_pack_query(queries.PackQueryCliOptions(str(tmp_path), "again", ""))
    assert first.campaign and again.campaign
    assert len(again.sections) == len(first.sections) == 2
    assert memo.read_bytes() == previous
    assert "[重跑] near" in again.render()


def test_campaign_miss_still_emits_valid_json(tmp_path: Path) -> None:
    _unit_pack(tmp_path / "子地图" / "001", "n001", 0, 0)
    result = execute_pack_query(
        queries.PackQueryCliOptions(str(tmp_path), "item", "missing")
    )
    assert result.exit_code == 2
    assert "子地图均无结果" in json.loads(result.render(as_json=True))["lines"][0]


def test_script_items_have_structured_coordinates_and_kind_filter(
    tmp_path: Path,
) -> None:
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "war3map.j").write_text(
        "function Spawn takes nothing returns nothing\n"
        "call CreateItem('I001',10000000,-20000000)\n"
        "call CreateUnit(Player(0),'n001',10000000,-20000000,0)\nendfunction\n",
        encoding="utf-8",
    )
    (tmp_path / "脚本调用参数索引.tsv").write_text(
        "CreateItem('I001',10000000,-20000000)\n", encoding="utf-8"
    )
    result = execute_pack_query(
        queries.PackQueryCliOptions(
            str(tmp_path), "near", "10000000 -20000000 1", near_kind="物品"
        )
    )
    payload = json.loads(result.render(as_json=True))
    assert result.exit_code == 0
    assert len(payload["entries"]) == 1
    assert payload["entries"][0]["code"] == "I001"
    assert payload["entries"][0]["x"] == 10000000
    assert payload["entries"][0]["y"] == -20000000
    assert "脚本单位:" not in result.render()


def test_gui_queries_do_not_redirect_or_mix_global_streams(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    original_stdout, original_stderr = sys.stdout, sys.stderr
    windows = []
    for name in ("first", "second"):
        pack = tmp_path / name
        pack.mkdir()
        (pack / "text.tsv").write_text("target " + name + "\n", encoding="utf-8")
        windows.append(
            cast(
                gui._PackQueryWindow, cast(object, SimpleNamespace(_pack_dir=str(pack)))
            )
        )
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = [
            executor.submit(gui._PackQueryWindow._run_query, window, "text", "target")
            for window in windows
        ]
        first, second = [future.result()[0] for future in pending]
    assert "target first" in first and "target second" not in first
    assert "target second" in second and "target first" not in second
    assert sys.stdout is original_stdout and sys.stderr is original_stderr
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_all_scripts_and_object_code_forms_share_coordinate_queries(
    tmp_path: Path,
) -> None:
    _unit_pack(tmp_path, "n000", 0, 0)
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "a.j").write_text(
        "call CreateUnit(Player(0),'n001',- 1e1,0,0)\n", encoding="utf-8"
    )
    (scripts / "b.j").write_text(
        "call CreateUnit(p,$6e303032,20,0,0)\n", encoding="utf-8"
    )
    (scripts / "c.lua").write_text(
        'CreateUnit(Player(0),FourCC("n003"),30,0,0)\n'
        "CreateItem(0x49303031,40,0)\n"
        "CreateItem(1227894834,50,0)\n"
        '-- CreateUnit(p,FourCC("nBAD"),0,0,0)\n'
        '--[=[\nCreateUnit(p,FourCC("nBAD"),0,0,0)\n]=]\n'
        'local example = [=[CreateItem(FourCC("IBAD"),0,0)]=]\n'
        "local quoted = 'CreateItem(FourCC(\"IBAD\"),0,0)'\n"
        'CreateUnit(p,FourCC("nDYN"),GetUnitX(u),0,0)\n',
        encoding="utf-8",
    )
    result = execute_pack_query(
        queries.PackQueryCliOptions(str(tmp_path), "near", "0 0 100", near_kind="单位")
    )
    payload = json.loads(result.render(as_json=True))
    assert {row["code"] for row in payload["entries"]} == {
        "n000",
        "n001",
        "n002",
        "n003",
    }
    for code in ("n001", "n002", "n003", "I001", "I002"):
        where = execute_pack_query(
            queries.PackQueryCliOptions(str(tmp_path), "where", code)
        )
        assert where.exit_code == 0 and f"[{code}]" in where.render()
    assert "nBAD" not in result.render() and "nDYN" not in result.render()


def test_index_argument_rows_do_not_duplicate_source_placements(tmp_path: Path) -> None:
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    text = "call CreateItem('I001',1,2)"
    (scripts / "war3map.j").write_text(text + "\n" + text, encoding="utf-8")
    (tmp_path / "脚本调用参数索引.tsv").write_text(
        "".join(
            f"war3map.j\t{line}\tCreateItem\t{argument}\t{text}\n"
            for line in (1, 2)
            for argument in (1, 2, 3)
        ),
        encoding="utf-8",
    )
    assert queries.load_placements(tmp_path) == [("I001", 1.0, 2.0, "item")] * 2


def test_technology_query_includes_every_level_cost_and_effect(tmp_path: Path) -> None:
    objects = tmp_path / "对象ID"
    objects.mkdir()
    (objects / "科技.tsv").write_text(
        "科技\tR001\t1\tR001\t研究\t是\t\n", encoding="utf-8"
    )
    values = {"glvl": "12", "gglb": "10", "gglm": "2", "glmb": "3", "glmm": "1"}
    values.update({f"gub1:{level}": f"效果{level}" for level in range(1, 13)})
    (tmp_path / "对象字段.tsv").write_text(
        "".join(
            f"科技\tR001\t研究\t{key}\t字段\t{value}\n" for key, value in values.items()
        ),
        encoding="utf-8",
    )
    result = execute_pack_query(
        queries.PackQueryCliOptions(str(tmp_path), "tech", "R001")
    )
    text = result.render()
    assert result.exit_code == 0
    for level in range(1, 13):
        assert f"{level}级 金{10 + 2 * (level - 1)} 木{3 + level - 1}" in text
        assert f"效果({level}级): 效果{level}" in text
    assert "满级累计: 金252 木102" in text


@pytest.mark.parametrize("kind", ["", "装饰", "脚本"])
def test_script_destructables_link_coordinates_names_drops_and_json(
    tmp_path: Path, kind: str
) -> None:
    (tmp_path / "对象ID").mkdir()
    (tmp_path / "对象ID" / "可破坏物.tsv").write_text(
        "分类\tID\t数值\t基础ID\t名称\t自定义\t说明\n"
        "可破坏物\tB001\t1\tB001\t脚本宝箱\t是\t\n",
        encoding="utf-8",
    )
    (tmp_path / "掉落与获取关系.tsv").write_text(
        "分类\t序号\t关系\t物品ID\t物品名\t来源类别\t来源ID\t来源名称\n"
        "物品\t1\t可破坏物掉落\tI001\t宝石\t可破坏物\tB001\t脚本宝箱\n",
        encoding="utf-8",
    )
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "a.j").write_text(
        "call CreateDestructable('B001',20,30,0,1,0)\n"
        "call CreateDeadDestructableZ('B001',40,50,10,0,1,0)\n"
        "// call CreateDestructable('BBAD',0,0,0,1,0)\n",
        encoding="utf-8",
    )
    (scripts / "b.lua").write_text(
        'CreateDestructableZ(FourCC("B001"),60,70,20,0,1,0)\n'
        'CreateDeadDestructable(FourCC("B001"),80,90,0,1,0)\n',
        encoding="utf-8",
    )
    result = execute_pack_query(
        queries.PackQueryCliOptions(str(tmp_path), "near", "0 0 200", near_kind=kind)
    )
    entries = json.loads(result.render(as_json=True))["entries"]
    assert result.exit_code == 0
    assert [(entry["x"], entry["y"]) for entry in entries] == [
        (20, 30),
        (40, 50),
        (60, 70),
        (80, 90),
    ]
    assert all(
        entry["kind"] == "脚本可破坏物" and entry["name"] == "脚本宝箱"
        for entry in entries
    )
    assert all("宝石" in entry["drops"] for entry in entries)
    for needle in ("B001", "脚本宝箱"):
        where = execute_pack_query(
            queries.PackQueryCliOptions(str(tmp_path), "where", needle)
        )
        assert where.exit_code == 0
        assert where.render().count("(可破坏物) ->") == 4
    units = execute_pack_query(
        queries.PackQueryCliOptions(str(tmp_path), "near", "0 0 200", near_kind="单位")
    )
    assert "脚本宝箱" not in units.render()


@pytest.mark.parametrize("function", ["CreateItem", "CreateDestructable"])
def test_explicit_near_limit_discloses_script_object_truncation(
    tmp_path: Path, function: str
) -> None:
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "war3map.j").write_text(
        "\n".join(f"call {function}('I001',{x},0,0,1,0)" for x in range(8)),
        encoding="utf-8",
    )
    complete = execute_pack_query(
        queries.PackQueryCliOptions(str(tmp_path), "near", "0 0 100")
    )
    limited = execute_pack_query(
        queries.PackQueryCliOptions(str(tmp_path), "near", "0 0 100", limit=3)
    )
    assert len(json.loads(complete.render(as_json=True))["entries"]) == 8
    assert len(json.loads(limited.render(as_json=True))["entries"]) == 3
    assert "其余 5 条" in limited.render()


def test_script_created_corpse_keeps_unit_argument_layout(tmp_path: Path) -> None:
    scripts = tmp_path / "脚本可读文本"
    scripts.mkdir()
    (scripts / "war3map.j").write_text(
        "call CreateCorpse(Player(0),'n001',100,200,0)\n", encoding="utf-8"
    )
    result = execute_pack_query(
        queries.PackQueryCliOptions(
            str(tmp_path), "near", "100 200 0", near_kind="单位"
        )
    )
    entries = json.loads(result.render(as_json=True))["entries"]
    assert [(entry["code"], entry["x"], entry["y"]) for entry in entries] == [
        ("n001", 100, 200)
    ]
