"""Completeness, numeric boundaries, cache ownership, and shared again regressions."""

from __future__ import annotations

import csv
import json
import threading
from collections.abc import Callable, Sequence
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from gametool import gui_pack_query as gui
from gametool import pack_query_cli as pq


@pytest.fixture(autouse=True)
def isolated_query_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Never read/write the user's query memory or retain synthetic cached rows."""
    monkeypatch.setattr(pq, "_memo_dir", lambda: tmp_path / "memo")
    monkeypatch.setattr(gui, "_memo_dir", lambda: str(tmp_path / "memo"))
    monkeypatch.setattr(pq, "_ROWS_CACHE", {})
    monkeypatch.setattr(pq, "_LOCKED_FILES", set())
    monkeypatch.setattr(gui, "_HISTORY", [])
    monkeypatch.setattr(gui, "_PINNED", [])
    monkeypatch.setattr(gui, "_WINDOW_GEOMETRY", {})
    monkeypatch.setattr(gui, "_LAST_KEYWORD", "")
    monkeypatch.setattr(gui, "_LAST_MODE", "doc")


def _write_tsv(path: Path, rows: Sequence[Sequence[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t", lineterminator="\n").writerows(rows)


def _objects(pack: Path, category: str, entries: Sequence[tuple[str, str]]) -> None:
    _write_tsv(
        pack / "对象ID" / f"{category}.tsv",
        [["分类", "ID", "10进制", "基础ID", "名称", "自定义", "说明"]]
        + [[category, code, "1", code, name, "是", ""] for code, name in entries],
    )


@pytest.mark.parametrize("limit", [None, 0, 1, 20, 40, 41])
def test_text_lists_every_matching_row_across_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], limit: int | None
) -> None:
    expected: list[str] = []
    for name, count in (("a.tsv", 37), ("b.tsv", 3)):
        rows = [f"命中-{name}-{i}-" + "长文本" * 100 for i in range(count)]
        (tmp_path / name).write_text("\n".join(rows) + "\n", encoding="utf-8")
        expected.extend(f"{name}: {row}" for row in rows)
    args = [str(tmp_path), "text", "命中", "--json"]
    if limit is not None:
        args.extend(["--limit", str(limit)])
    assert pq.run_pack_query_cli(pq.parse_pack_query_cli_options(args)) == 0
    lines = json.loads(capsys.readouterr().out)["lines"]
    shown = min(limit, len(expected)) if limit else len(expected)
    assert lines[:shown] == expected[:shown]
    if shown < len(expected):
        assert len(lines) == shown + 1
        assert f"--limit {limit}" in lines[-1]
        assert f"其余 {len(expected) - shown} 条" in lines[-1]
    else:
        assert lines == expected  # Reaching exactly --limit is not truncation.


def test_text_miss_keeps_recovery_guidance(tmp_path: Path) -> None:
    (tmp_path / "a.tsv").write_text("无匹配\n", encoding="utf-8")
    lines = pq._query_text(tmp_path, "不存在", 0)
    assert lines[0].startswith("未找到文本")
    assert "search <词>" in lines[1]


def _same_named_drop_pack(pack: Path, category: str) -> list[str]:
    units: list[tuple[str, str]] = []
    items: list[tuple[str, str]] = []
    candidates: list[str] = []
    script: list[str] = []
    for i in range(1, 7):
        if category in ("单位", "混合"):
            unit, reward = f"n{i:03}", f"J{i:03}"
            units.append((unit, "同名目标"))
            items.append((reward, f"奖励{i}"))
            candidates.append(unit)
            script.append(
                f"function Unit{i}Actions takes nothing returns nothing\n"
                f"if GetUnitTypeId(GetDyingUnit()) == '{unit}' then\n"
                f"call CreateItem('{reward}', 0, 0)\nendif\nendfunction\n"
            )
        if category in ("物品", "混合"):
            source, item = f"e{i:03}", f"I{i:03}"
            units.append((source, f"独立来源{i}"))
            items.append((item, "同名目标"))
            candidates.append(item)
            script.append(
                f"function Item{i}Actions takes nothing returns nothing\n"
                f"if GetUnitTypeId(GetDyingUnit()) == '{source}' then\n"
                f"call CreateItem('{item}', 0, 0)\nendif\nendfunction\n"
            )
    _objects(pack, "单位", units)
    _objects(pack, "物品", items)
    script_dir = pack / "脚本可读文本"
    script_dir.mkdir()
    (script_dir / "war3map.j").write_text("\n".join(script), encoding="utf-8")
    # Resolution is in object-table order: units first, then items.
    return sorted(candidates, key=lambda code: (code.startswith("I"), code))


@pytest.mark.parametrize("category", ["单位", "物品", "混合"])
@pytest.mark.parametrize("limit", [0, 2, 6, 12])
def test_drop_enumerates_all_same_named_script_candidates(
    tmp_path: Path, category: str, limit: int
) -> None:
    candidates = _same_named_drop_pack(tmp_path, category)
    lines = pq._query_drop(tmp_path, "同名目标", limit)
    headers = [line for line in lines if line.startswith("同名目标 [")]
    shown = candidates[:limit] if limit else candidates
    assert [line.split("[", 1)[1].split("]", 1)[0] for line in headers] == shown
    assert all("⚠" in line for line in headers)  # Keep script-evidence attribution.
    if len(shown) < len(candidates):
        assert f"其余 {len(candidates) - len(shown)} 条" in lines[-1]
        assert f"--limit {limit}" in lines[-1]
    else:
        assert not any("--limit" in line for line in lines)


@pytest.mark.parametrize("category,code", [("单位", "n004"), ("物品", "I004")])
def test_drop_explicit_fourcc_does_not_broaden_to_same_named_objects(
    tmp_path: Path, category: str, code: str
) -> None:
    _same_named_drop_pack(tmp_path, category)
    lines = pq._query_drop(tmp_path, code, 0)
    headers = [line for line in lines if line.startswith("同名目标 [")]
    assert len(headers) == 1
    assert f"[{code}]" in headers[0]


def test_drop_finds_evidence_after_four_empty_name_candidates(tmp_path: Path) -> None:
    _same_named_drop_pack(tmp_path, "单位")
    _objects(
        tmp_path,
        "单位",
        [(f"x{i:03}", "同名目标") for i in range(4)] + [("n006", "同名目标")],
    )
    text = "\n".join(pq._query_drop(tmp_path, "同名目标", 0))
    assert "同名目标 [n006]" in text
    assert "奖励6 [J006]" in text


def test_drop_without_evidence_lists_all_same_named_units(tmp_path: Path) -> None:
    codes = [f"n{i:03}" for i in range(6)]
    _objects(tmp_path, "单位", [(code, "同名目标") for code in codes])
    lines = pq._query_drop(tmp_path, "同名目标", 0)
    for code in codes:
        assert any(f"[{code}] 同名目标 无死亡触发" in line for line in lines)
    assert "where <词>" in lines[-1]


@pytest.mark.parametrize("query", ["I001", "敌军"])
@pytest.mark.parametrize("limit", [2, 5, 6])
def test_drop_relation_limit_discloses_only_actual_truncation(
    tmp_path: Path, query: str, limit: int
) -> None:
    _write_tsv(
        tmp_path / "掉落与获取关系.tsv",
        [
            [
                "关系ID",
                "地图",
                "关系类型",
                "装备ID",
                "装备名称",
                "分类",
                "来源ID",
                "来源名称",
            ]
        ]
        + [
            [str(i), "图", "单位掉落", "I001", "物品", "单位", f"n{i:03}", f"敌军{i}"]
            for i in range(5)
        ],
    )
    lines = pq._query_drop(tmp_path, query, limit)
    assert len([line for line in lines if "单位掉落" in line]) == min(limit, 5)
    if limit < 5:
        assert "其余 3 条" in lines[-1]
    else:
        assert not any("--limit" in line for line in lines)


def _radius_pack(pack: Path) -> None:
    _write_tsv(
        pack / "预放置单位.tsv",
        [["序号", "类型ID", "名称", "玩家", "X", "Y", "Z"]]
        + [
            [str(i), code, code, "敌对", str(x), "0", "0"]
            for i, (code, x) in enumerate(
                [
                    ("n000", 0),
                    ("n025", 25),
                    ("n200", 20000),
                    ("n250", 25000),
                    ("n251", 25001),
                ]
            )
        ],
    )


@pytest.mark.parametrize(
    "query,expected_radius,codes",
    [
        ("0 0", "3000", ["n000", "n025"]),
        ("0 0 0", "0", ["n000"]),
        ("0 0 0.5", "0.5", ["n000"]),
        ("0 0 25", "25", ["n000", "n025"]),
        ("0 0 25000", "25000", ["n000", "n025", "n200", "n250"]),
        ("0 0 50000", "50000", ["n000", "n025", "n200", "n250", "n251"]),
    ],
)
def test_near_honors_zero_small_and_large_finite_radii(
    tmp_path: Path, query: str, expected_radius: str, codes: list[str]
) -> None:
    _radius_pack(tmp_path)
    lines = pq._query_near(tmp_path, query + " --kind 单位", 0)
    assert lines[0] == f"== 坐标 (0, 0) 半径 {expected_radius} =="
    assert [
        line.split("[", 1)[1].split("]", 1)[0]
        for line in lines
        if line.startswith("  单位:")
    ] == codes
    assert "钳制" not in "\n".join(lines)


_INVALID_NEAR = [
    " ".join([token if i == pos else "0" for i in range(3)])
    for pos in range(3)
    for token in ("nan", "inf", "-Infinity", "1e309")
] + ["0 0 -1", "0 0 -0.0001", "bad 0 1", "0 bad 1", "0 0 bad"]


@pytest.mark.parametrize("query", _INVALID_NEAR)
@pytest.mark.parametrize("as_json", [False, True])
def test_near_rejects_invalid_numbers_before_reading_pack_or_remembering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    query: str,
    as_json: bool,
) -> None:
    pq._store_last_query(tmp_path, "text", "原查询")
    original = pq._load_last_query()

    def unexpected_read(_pack: Path) -> dict[str, str]:
        pytest.fail("Invalid numeric input must be rejected before reading sources")

    monkeypatch.setattr(pq, "_source_drop_map", unexpected_read)
    options = pq.PackQueryCliOptions(str(tmp_path), "near", query, as_json=as_json)
    assert pq.run_pack_query_cli(options) == 2
    output = capsys.readouterr().out
    if as_json:
        payload = json.loads(output)
        assert payload["entries"] == []
        output = "\n".join(payload["lines"])
    assert output.startswith("坐标与半径必须")
    assert pq._load_last_query() == original


@pytest.mark.parametrize("shifted_header", [False, True])
def test_near_repeated_queries_do_not_mutate_cached_source_rows(
    tmp_path: Path, shifted_header: bool
) -> None:
    header = ["序号", "类型ID", "名称", "玩家", "X", "Y", "Z"]
    row = ["1", "p001", "原放置", "中立", "10", "20", "0"]
    if shifted_header:
        header = ["序号", "类型ID", "名称", "X", "备注", "Y", "Z"]
        row = ["1", "p001", "原放置", "10", "备注", "20", "0"]
    path = tmp_path / "预放置单位.tsv"
    _write_tsv(path, [[], header, row])
    (tmp_path / "脚本调用参数索引.tsv").write_text(
        "set u=CreateUnit(p, 's001', 100, 200, 270)\n", encoding="utf-8"
    )
    cached = pq._read_rows(tmp_path, path.name)
    original_rows = deepcopy(cached)
    original_bytes = path.read_bytes()
    results = [pq._query_near(tmp_path, "100 200 500 --kind 单位", 0) for _ in range(4)]
    assert results == [results[0]] * 4
    assert any("[s001] ×1 @(100,200)" in line for line in results[0])
    assert pq._read_rows(tmp_path, path.name) is cached
    assert cached == original_rows
    assert path.read_bytes() == original_bytes


@pytest.mark.parametrize("limit", [2, 5])
def test_near_limit_still_reports_exact_remaining_hits(
    tmp_path: Path, limit: int
) -> None:
    _radius_pack(tmp_path)
    lines = pq._query_near(tmp_path, "0 0 50000 --kind 单位", limit)
    assert len([line for line in lines if line.startswith("  单位:")]) == limit
    if limit == 2:
        assert "其余 3 条" in lines[-1]
    else:
        assert not any("--limit" in line for line in lines)


@pytest.mark.parametrize("category", ["物品", "单位", "技能", "英雄"])
@pytest.mark.parametrize("summary_changed", [False, True])
def test_diff_reads_root_field_table_not_a_nested_decoy(
    tmp_path: Path, category: str, summary_changed: bool
) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    for pack, price in ((old, "100"), (new, "200")):
        name = "新名称" if pack == new and summary_changed else "原名称"
        _objects(pack, category, [("X001", name)])
        _write_tsv(
            pack / "对象字段.tsv",
            [["来源", "值", "分类", "字段键", "ID", "名称"]]
            + [
                ["map", price, category, "cost", "X001", name],
                ["map", "unchanged", category, "stable", "X001", name],
                ["map", price, "无关分类", "unrelated", "X001", name],
                ["map", price, category, "unrelated", "X999", name],
                ["short"],
            ]
            + [["map", "old", category, "removed", "X001", name]] * (pack == old)
            + [["map", "new", category, "added", "X001", name]] * (pack == new),
        )
        _write_tsv(
            pack / "对象ID" / "对象字段.tsv",
            [["分类", "ID", "字段键", "值"], [category, "X001", "cost", "decoy"]],
        )
    text = "\n".join(pq._query_diff(new, "", 0, str(old)))
    assert "变更 1" in text
    assert "cost: 100 -> 200" in text
    # The short root record makes absence uncertain; shared values still compare.
    assert "added:" not in text
    assert "removed:" not in text
    assert "字段表不完整" in text
    assert "decoy" not in text
    assert "unrelated:" not in text


class _InlineThread:
    def __init__(self, *, target: Callable[[], None], daemon: bool) -> None:
        self.target = target
        assert daemon

    def start(self) -> None:
        self.target()


def _headless_gui_run(
    pack: Path,
    command: str,
    keyword: str,
    as_json: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    """Execute the real GUI worker/poll path without Tk or background timing."""
    monkeypatch.setattr(threading, "Thread", _InlineThread)
    results: list[str] = []
    window = SimpleNamespace(
        _pack_dir=str(pack),
        _query_generation=0,
        _keyword=SimpleNamespace(get=lambda: keyword),
        _var_json=SimpleNamespace(get=lambda: as_json),
        _history=SimpleNamespace(configure=lambda **_kw: None, set=lambda _v: None),
        _output=SimpleNamespace(delete=lambda *_a: None, insert=lambda *_a: None),
        _find_state={"start": "1.0"},
        configure=lambda **_kw: None,
        winfo_exists=lambda: True,
        after=lambda _delay, callback: callback(),
        _finish=lambda text, _elapsed: results.append(text),
    )
    typed_window = cast(gui._PackQueryWindow, cast(object, window))
    window._run_query = lambda cmd, word, use_json: gui._PackQueryWindow._run_query(
        typed_window, cmd, word, use_json
    )
    gui._PackQueryWindow._run(typed_window, command)
    assert len(results) == 1
    return results[0]


@pytest.mark.parametrize("as_json", [False, True])
def test_gui_repeated_again_keeps_original_pack_command_and_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, as_json: bool
) -> None:
    original_pack, current_pack = tmp_path / "original", tmp_path / "current"
    original_pack.mkdir()
    current_pack.mkdir()
    (original_pack / "a.tsv").write_text("原查询 命中原包\n", encoding="utf-8")
    pq._store_last_query(original_pack, "text", "原查询")
    original = pq._load_last_query()
    memo_bytes = (pq._memo_dir() / pq._LAST_QUERY_FILE).read_bytes()
    calls: list[str] = []
    real_store = pq._store_last_query

    def record_store(pack: Path, command: str, query: str) -> None:
        calls.append(command)
        real_store(pack, command, query)

    monkeypatch.setattr(pq, "_store_last_query", record_store)
    for _ in range(3):
        text = _headless_gui_run(current_pack, "again", "", as_json, monkeypatch)
        assert "命中原包" in text
        assert "[重跑] text 原查询" in text
        assert pq._load_last_query() == original
        assert (pq._memo_dir() / pq._LAST_QUERY_FILE).read_bytes() == memo_bytes
    assert calls == []  # GUI must not even attempt to store the wrapper command.


@pytest.mark.parametrize("as_json", [False, True])
def test_gui_normal_query_still_updates_shared_again_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, as_json: bool
) -> None:
    (tmp_path / "a.tsv").write_text("普通查询 命中\n", encoding="utf-8")
    text = _headless_gui_run(tmp_path, "text", "普通查询", as_json, monkeypatch)
    assert "命中" in text
    assert pq._load_last_query() == {
        "pack": str(tmp_path),
        "command": "text",
        "query": "普通查询",
    }


@pytest.mark.parametrize("has_previous", [False, True])
def test_store_again_never_creates_or_replaces_a_query(
    tmp_path: Path, has_previous: bool
) -> None:
    if has_previous:
        pq._store_last_query(tmp_path, "text", "原查询")
    original = pq._load_last_query()
    pq._store_last_query(tmp_path, "again", "")
    assert pq._load_last_query() == original
    assert (pq._memo_dir() / pq._LAST_QUERY_FILE).exists() == has_previous


def test_again_rejects_legacy_recursive_memo_without_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    memo = pq._memo_dir()
    memo.mkdir()
    (memo / pq._LAST_QUERY_FILE).write_text(
        json.dumps({"pack": str(tmp_path), "command": "again", "query": ""}),
        encoding="utf-8",
    )

    def recursive_dispatch(_pack: Path, _query: str, _limit: int) -> list[str]:
        pytest.fail("A stored again must never be dispatched recursively")

    monkeypatch.setitem(pq._QUERIES, "again", recursive_dispatch)
    assert pq._load_last_query() is None
    assert (
        pq.run_pack_query_cli(pq.PackQueryCliOptions(str(tmp_path), "again", "")) == 0
    )
    assert "无最近查询记录" in capsys.readouterr().out


@pytest.mark.parametrize(
    "payload", [None, [], 42, "text", {}, {"pack": 1, "command": "text", "query": "x"}]
)
def test_again_malformed_memo_fails_open(tmp_path: Path, payload: object) -> None:
    memo = pq._memo_dir()
    memo.mkdir()
    (memo / pq._LAST_QUERY_FILE).write_text(json.dumps(payload), encoding="utf-8")
    assert pq._load_last_query() is None
    assert pq._query_again(tmp_path, "", 0)[0].startswith("无最近查询记录")


@pytest.mark.parametrize("query", ["nan 0 1", "0 0 -1"])
@pytest.mark.parametrize("as_json", [False, True])
def test_campaign_near_rejects_invalid_numbers_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], query: str, as_json: bool
) -> None:
    sub = tmp_path / "子地图" / "001"
    sub.mkdir(parents=True)
    (sub / "掉落与获取关系.tsv").write_text("", encoding="utf-8")
    options = pq.PackQueryCliOptions(str(tmp_path), "near", query, as_json=as_json)
    assert pq.run_pack_query_cli(options) == 2
    output = capsys.readouterr().out
    if as_json:
        output = "\n".join(json.loads(output)["lines"])
    assert output.count("坐标与半径必须") == 1
    assert "子地图" not in output


@pytest.mark.parametrize("kind", ["", " --kind 单位"])
def test_large_radius_miss_does_not_suggest_a_smaller_clamped_radius(
    tmp_path: Path, kind: str
) -> None:
    lines = pq._query_near(tmp_path, "0 0 50000" + kind, 0)
    text = "\n".join(lines)
    assert "半径 50000" in text
    assert "20000" not in text
    assert "加大半径参数" in text


def test_near_accepts_negative_finite_coordinates_and_negative_zero_radius(
    tmp_path: Path,
) -> None:
    _write_tsv(
        tmp_path / "预放置单位.tsv",
        [
            ["序号", "类型ID", "名称", "玩家", "X", "Y", "Z"],
            ["1", "n001", "定位单位", "中立", "-100", "-200", "0"],
        ],
    )
    text = "\n".join(pq._query_near(tmp_path, "-100 -200 -0 --kind 单位", 0))
    assert "定位单位 [n001] ×1 @(-100,-200) 距0" in text


def test_again_dispatch_refuses_recursive_command_even_with_a_custom_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        pq,
        "_load_last_query",
        lambda: {"pack": str(tmp_path), "command": "again", "query": ""},
    )
    assert pq._query_again(tmp_path, "", 0)[0].startswith("无最近查询记录")
