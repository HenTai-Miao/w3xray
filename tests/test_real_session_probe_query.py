"""Probe and guide handoffs execute the selected map's real query backend."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from gametool import gui_export_actions as exports
from gametool import gui_pack_query as query_gui
from gametool import gui_topbar as topbar
from gametool.batch_tsv import format_tsv_rows
from gametool.item_relation_exports import ACQUISITION_REPORT_HEADER
from tests.test_release_gui_actions import _ActionHost


class _Selection:
    def __init__(self, text: str) -> None:
        self.text = text

    def get(self, _start: str, _end: str) -> str:
        return self.text


def _write_pack(pack: Path) -> None:
    objects = pack / "对象ID"
    objects.mkdir()
    header = ("分类", "ID", "数值", "基础ID", "名称", "自定义", "说明")
    (objects / "物品.tsv").write_text(
        format_tsv_rows(
            (
                header,
                ("物品", "I001", "1", "ratf", "当局晶石", "是", "守卫掉落"),
                ("物品", "near", "2", "ratf", "坐标原码物品", "是", "合法四码"),
                ("物品", "drop", "3", "ratf", "掉落原码物品", "是", "合法四码"),
            )
        ),
        encoding="utf-8",
    )
    (objects / "单位.tsv").write_text(
        format_tsv_rows((header, ("单位", "n001", "1", "hfoo", "当局守卫", "是", ""))),
        encoding="utf-8",
    )
    (pack / "预放置单位.tsv").write_text(
        "类型ID\t名称\tX\tY\t分类\nn001\t当局守卫\t1\t2\t单位\n",
        encoding="utf-8",
    )
    relation = [""] * len(ACQUISITION_REPORT_HEADER)
    for index, value in {
        0: "one-drop",
        1: "当局地图",
        2: "怪物直接掉落",
        3: "I001",
        4: "当局晶石",
        5: "单位",
        6: "n001",
        7: "当局守卫",
        10: "1",
        11: "2",
        19: "war3mapUnits.doo",
        23: "已确认",
        24: "完整",
    }.items():
        relation[index] = value
    (pack / "掉落与获取关系.tsv").write_text(
        format_tsv_rows((ACQUISITION_REPORT_HEADER, tuple(relation))),
        encoding="utf-8",
    )


def _query_handoffs(monkeypatch: pytest.MonkeyPatch, pack: Path):
    host = _ActionHost()
    assert host.map_data is not None
    host._current_map_pack = exports._CurrentMapPack(host.map_data, str(pack))
    results: list[dict[str, Any]] = []
    opened: list[tuple[str, str]] = []

    def open_query(_host, provider, _ensure, prefill="", prefill_command=""):
        current = provider()
        assert current == str(pack)
        worker = SimpleNamespace(_pack_dir=current)
        body, _elapsed = query_gui._PackQueryWindow._run_query(
            cast(query_gui._PackQueryWindow, cast(object, worker)),
            prefill_command,
            prefill,
            as_json=True,
        )
        results.append(json.loads(body))
        opened.append((prefill_command, prefill))

    monkeypatch.setattr(query_gui, "open_pack_query_dialog", open_query)
    probe = {}
    monkeypatch.setattr(
        topbar,
        "open_live_probe_dialog",
        lambda _host, _pack, **options: probe.update(options),
    )
    topbar._open_live_probe(host)
    return host, probe["query_callback"], results, opened


@pytest.mark.parametrize("origin", ("probe", "guide"))
@pytest.mark.parametrize("command", ("near", "where", "drop"))
def test_selected_map_handoffs_deliver_actual_query_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, origin: str, command: str
) -> None:
    _write_pack(tmp_path)
    host, callback, results, _opened = _query_handoffs(monkeypatch, tmp_path)
    try:
        if origin == "probe":
            callback("near 1 2 100" if command == "near" else f"{command} I001")
        elif command == "near":
            topbar._near_selected_coords(host, _Selection("@(1,2)"), "100")
        else:
            topbar._code_selected(host, _Selection("当局晶石 [I001]"), command)

        assert len(results) == 1
        result = results[0]
        assert result["command"] == command
        assert result["exit_code"] == 0
        assert not result["input_error"]
        if command == "near":
            assert result["query"] == "1 2 100"
            assert [
                (entry["code"], entry["positions"]) for entry in result["entries"]
            ] == [("n001", [[1.0, 2.0]])]
        else:
            assert result["query"] == "I001"
            assert any(
                "怪物直接掉落" in line and "当局晶石" in line and "n001" in line
                for line in result["lines"]
            )
    finally:
        host._shutdown_gui_worker_host(1)


@pytest.mark.parametrize("code", ("near", "drop"))
def test_probe_bare_command_spellings_remain_object_codes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, code: str
) -> None:
    _write_pack(tmp_path)
    host, callback, results, opened = _query_handoffs(monkeypatch, tmp_path)
    try:
        callback(code)

        assert opened == [("doc", code)]
        assert results[0]["exit_code"] == 0
        assert any(f"[{code}]" in line for line in results[0]["lines"])
    finally:
        host._shutdown_gui_worker_host(1)


@pytest.mark.parametrize("code", (" n01", "n01 "))
def test_probe_route_preserves_raw_code_whitespace_after_explicit_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, code: str
) -> None:
    _write_pack(tmp_path)
    host, callback, _results, opened = _query_handoffs(monkeypatch, tmp_path)
    try:
        callback("where " + code)

        assert opened == [("where", code)]
    finally:
        host._shutdown_gui_worker_host(1)
