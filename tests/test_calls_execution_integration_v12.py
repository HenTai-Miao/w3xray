"""Calls preserve source evidence across shared CLI, campaign, replay and GUI routes."""

from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_execution import PackQueryResult
from gametool.pack_query_options import PackQueryCliOptions


@pytest.fixture(autouse=True)
def isolated_query_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "query-memory")


def _source(pack: Path, text: str, name: str = "war3map.lua") -> Path:
    path = pack / "脚本原始文本" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _execute(pack: Path, query: str = "", limit: int = 0) -> PackQueryResult:
    return queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "calls", query, limit=limit)
    )


def _remember(pack: Path) -> tuple[Path, bytes]:
    queries._store_last_query(pack, "item", "previous successful query")
    path = queries._memo_dir() / queries._LAST_QUERY_FILE
    return path, path.read_bytes()


@pytest.mark.parametrize("limit", [[], ["--limit", "all"], ["--limit", "全部"]])
def test_cli_omitted_keyword_is_full_listing_and_one_json_document(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], limit: list[str]
) -> None:
    _source(tmp_path, "GetLocalPlayer()\nKillUnit(first)\nKillUnit(second)\n")
    options = queries.parse_pack_query_cli_options(
        [str(tmp_path), "calls", "--json", *limit]
    )
    assert options.query == "" and options.limit == 0 and options.as_json
    assert queries.run_pack_query_cli(options) == 0
    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert payload["command"] == "calls" and payload["query"] == ""
    assert payload["calls_total"] == len(payload["calls"]) == 3
    assert payload["calls_omitted"] == 0
    assert payload["source_stable"] and not payload["input_error"]
    assert [row["arguments"] for row in payload["calls"]] == [
        [],
        ["first"],
        ["second"],
    ]
    assert payload["checked_packs"] == [str(tmp_path)]
    assert "[耗时 " in output.err and "[耗时 " not in output.out


@pytest.mark.parametrize("campaign", [False, True])
def test_empty_calls_again_keeps_every_section_header_and_original_memory(
    tmp_path: Path, campaign: bool
) -> None:
    _source(tmp_path, "KillUnit(root)")
    if campaign:
        _source(tmp_path / "子地图" / "chapter", "KillUnit(child)")
    full = _execute(tmp_path)
    memo = queries._memo_dir() / queries._LAST_QUERY_FILE
    before = memo.read_bytes()
    assert json.loads(before)["query"] == ""
    replay = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path / "unused"), "again", "ignored")
    )
    assert replay.exit_code == 0 and replay.command == "calls" and replay.query == ""
    assert replay.checked_packs == full.checked_packs
    assert [row.calls for row in replay.sections] == [
        row.calls for row in full.sections
    ]
    assert memo.read_bytes() == before
    payload = json.loads(replay.render(as_json=True))
    header = f"[重跑] calls  (来自 {tmp_path})"
    assert payload["lines"].count(header) == 1
    assert replay.sections[0].lines[0] == header
    if campaign:
        assert [row["section"] for row in payload["sections"]] == [
            "容器级",
            "子地图 chapter",
        ]
        assert payload["sections"][0]["lines"][0] == header
        assert all(row["source_stable"] for row in payload["sections"])


def test_final_campaign_revalidation_retains_earlier_records_and_blocks_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _source(tmp_path, "KillUnit(root1)")
    early = tmp_path / "子地图" / "a"
    _source(early, "KillUnit(early)")
    late = tmp_path / "子地图" / "z"
    _source(late, "KillUnit(late)")
    memo, before = _remember(tmp_path)
    previous_stat = root.stat()
    original = queries._query_calls_result

    def query_with_later_change(pack: Path, query: str, limit: int):
        report = original(pack, query, limit)
        if pack == late:
            root.write_bytes(b"KillUnit(root2)")
            os.utime(root, ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns))
            (early / "脚本清单.txt").write_text("脚本文件：0\n", encoding="utf-8")
        return report

    monkeypatch.setattr(queries, "_query_calls_result", query_with_later_change)
    result = _execute(tmp_path)
    payload = json.loads(result.render(as_json=True))
    assert result.exit_code == 2 and payload["input_error"]
    assert payload["has_matches"] and not payload["source_stable"]
    assert payload["calls_total"] == 3 and len(payload["calls"]) == 3
    assert [row["arguments"] for row in payload["calls"]] == [
        ["root1"],
        ["early"],
        ["late"],
    ]
    assert payload["checked_packs"] == [str(tmp_path), str(early), str(late)]
    sections = payload["sections"]
    assert [row["source_stable"] for row in sections] == [False, False, True]
    assert [row["input_error"] for row in sections] == [True, True, False]
    assert all(row["has_matches"] for row in sections)
    changed = [
        row for row in payload["call_diagnostics"] if row["code"] == "snapshot.changed"
    ]
    assert {(row["pack"], row["source"]) for row in changed} >= {
        (str(tmp_path), "脚本原始文本/war3map.lua"),
        (str(early), "脚本清单.txt"),
    }
    assert memo.read_bytes() == before
    assert payload["script_coverage"]["complete"] is False


def test_again_source_change_keeps_replay_header_and_original_frozen_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _source(tmp_path, "KillUnit(before)")
    assert _execute(tmp_path).exit_code == 0
    memo = queries._memo_dir() / queries._LAST_QUERY_FILE
    before = memo.read_bytes()
    original = queries._query_calls_result

    def change_after_read(pack: Path, query: str, limit: int):
        report = original(pack, query, limit)
        path.write_text("KillUnit(after)", encoding="utf-8")
        return report

    monkeypatch.setattr(queries, "_query_calls_result", change_after_read)
    result = queries.execute_pack_query(PackQueryCliOptions("unused", "again", ""))
    payload = json.loads(result.render(as_json=True))
    assert result.command == "calls" and result.exit_code == 2
    assert payload["input_error"] and payload["has_matches"]
    assert not payload["source_stable"]
    assert payload["calls"][0]["arguments"] == ["before"]
    assert payload["lines"][0] == f"[重跑] calls  (来自 {tmp_path})"
    assert sum(line.startswith("[重跑]") for line in payload["lines"]) == 1
    assert any(row["code"] == "snapshot.changed" for row in payload["call_diagnostics"])
    assert memo.read_bytes() == before


def test_limit_keeps_all_diagnostics_with_nested_core_and_scope_provenance(
    tmp_path: Path,
) -> None:
    _source(
        tmp_path,
        "KillUnit(first)\n"
        'if gate then UnknownOuter("literal\\tfull", nested) end\n'
        "UnknownLast(second)\n",
    )
    child = tmp_path / "子地图" / "child"
    _source(child, "KillUnit(child)\nUnknownChild(last)\n")
    full = _execute(tmp_path)
    limited = _execute(tmp_path, limit=1)
    payload = json.loads(limited.render(as_json=True))
    assert payload["calls_total"] == 5 and payload["calls_omitted"] == 3
    assert len(payload["calls"]) == 2  # the public limit is per campaign scope
    assert [row.call_diagnostics for row in limited.sections] == [
        row.call_diagnostics for row in full.sections
    ]
    expected = [
        {**asdict(note), "pack": section.pack, "section": section.section}
        for section in full.sections
        for note in section.call_diagnostics
    ]
    assert payload["call_diagnostics"] == json.loads(json.dumps(expected))
    assert any(
        row["core"] and "UnknownOuter" in row["core"]["raw"]
        for row in payload["call_diagnostics"]
    )
    assert any(
        row["pack"] == str(child) and "UnknownChild" in row["raw"]
        for row in payload["call_diagnostics"]
    )


def test_diagnostic_only_campaign_scope_is_retained_and_stable_is_not_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source(tmp_path, "KillUnit(root)")
    child = tmp_path / "子地图" / "unreadable"
    unavailable = _source(child, "KillUnit(hidden)")
    original = Path.open

    def denied(path: Path, *args, **kwargs):
        if path == unavailable:
            raise PermissionError("test source remains unreadable")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    result = _execute(tmp_path, "KillUnit")
    payload = json.loads(result.render(as_json=True))
    assert result.exit_code == 0 and not payload["input_error"]
    assert payload["source_stable"] and payload["has_matches"]
    assert payload["script_coverage"]["complete"] is False
    assert payload["checked_packs"] == [str(tmp_path), str(child)]
    assert len(payload["sections"]) == 2
    failure = payload["sections"][1]
    assert not failure["has_matches"] and failure["calls_total"] == 0
    assert failure["call_diagnostics"] and failure["source_stable"]
    assert "test source remains unreadable" in "\n".join(failure["lines"])


def test_no_matching_calls_retains_all_checked_scopes_and_does_not_replace_memory(
    tmp_path: Path,
) -> None:
    _source(tmp_path, "KillUnit(root)")
    child = tmp_path / "子地图" / "child"
    _source(child, "KillUnit(child)")
    memo, before = _remember(tmp_path)
    result = _execute(tmp_path, "no-matching-evidence")
    payload = json.loads(result.render(as_json=True))
    assert result.exit_code == 2 and not payload["input_error"]
    assert payload["source_stable"] and not payload["has_matches"]
    assert payload["calls_total"] == payload["calls_omitted"] == 0
    assert payload["checked_packs"] == [str(tmp_path), str(child)]
    assert len(payload["sections"]) == 2
    assert all(not row["has_matches"] for row in payload["sections"])
    assert all("text <词>" in "\n".join(row["lines"]) for row in payload["sections"])
    assert memo.read_bytes() == before


@pytest.mark.parametrize("as_json", [False, True])
def test_gui_worker_runs_real_empty_calls_query_without_tk_or_stream_capture(
    tmp_path: Path, as_json: bool
) -> None:
    from gametool import gui_pack_query as gui

    _source(tmp_path, "SetPlayerState(player, gold, 17)\nKillUnit(unit)")
    window = cast(
        gui._PackQueryWindow, cast(object, SimpleNamespace(_pack_dir=str(tmp_path)))
    )
    text, elapsed = gui._PackQueryWindow._run_query(window, "calls", "", as_json)
    if as_json:
        payload = json.loads(text)
        assert payload["calls_total"] == 2 and payload["query"] == ""
        assert payload["calls"][0]["arguments"] == ["player", "gold", "17"]
    else:
        assert "匹配 2 条" in text and '参数 3: "17"' in text
    assert elapsed.startswith("[耗时 ")
    assert queries._load_last_query() == {
        "pack": str(tmp_path),
        "command": "calls",
        "query": "",
    }


def test_invalid_count_stops_before_source_read_and_preserves_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    memo, before = _remember(tmp_path)

    def unexpected(*_args, **_kwargs):
        pytest.fail("an invalid count must not reach source discovery or reads")

    monkeypatch.setattr(queries, "_campaign_subpacks", unexpected)
    monkeypatch.setattr(queries, "_query_calls_result", unexpected)
    result = _execute(tmp_path, limit=-1)
    payload = json.loads(result.render(as_json=True))
    assert result.exit_code == 2 and payload["input_error"]
    assert payload["calls"] == [] and payload["source_stable"] is None
    assert payload["checked_packs"] == [] and memo.read_bytes() == before


def test_missing_calls_pack_is_typed_input_error_without_touching_memory(
    tmp_path: Path,
) -> None:
    memo, before = _remember(tmp_path)
    result = _execute(tmp_path / "missing")
    payload = json.loads(result.render(as_json=True))
    assert result.exit_code == 2
    assert payload["input_error"] is True
    assert payload["calls"] == [] and payload["source_stable"] is None
    assert payload["checked_packs"] == [] and memo.read_bytes() == before


def test_app_loadout_dispatch_uses_actual_cli_without_starting_gui(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gametool import app

    path = tmp_path / "missing-loadout.json"
    monkeypatch.setattr(app.sys, "argv", ["gamexray", "loadout", str(path), "--json"])
    monkeypatch.setattr(app, "configure_cli_output", lambda: None)
    monkeypatch.setattr(app.multiprocessing, "freeze_support", lambda: None)
    with pytest.raises(SystemExit) as stopped:
        app.main()
    assert stopped.value.code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["report_type"] == "offline-loadout-inspection"
    assert payload["input_error"] and payload["exit_code"] == 2


def test_topbar_offline_menu_reaches_real_loadout_and_calls_entry_callbacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool import gui_export_actions, gui_loadout_workbench, gui_pack_query
    from gametool import gui_topbar as topbar

    class Widget:
        def __init__(self, *_args, **options):
            self.options = options

        def pack(self, *_args, **_kwargs):
            pass

        def pack_propagate(self, *_args):
            pass

        def configure(self, **options):
            self.options.update(options)

    class Menu:
        def __init__(self, *_args, **_kwargs):
            self.commands = {}

        def add_command(self, *, label, command):
            self.commands[label] = command

        def add_separator(self):
            pass

    class App(SimpleNamespace):
        def __getattr__(self, name):
            if name.startswith("on_"):
                return lambda *_args, **_kwargs: None
            raise AttributeError(name)

    for name in ("CTkFrame", "CTkLabel", "CTkButton"):
        monkeypatch.setattr(topbar.ctk, name, Widget)
    monkeypatch.setattr(topbar.tk, "Menu", Menu)
    monkeypatch.setattr(topbar, "_attach_tooltip", lambda *_args: None)
    app = App(map_data=None)
    loadout_hosts = []
    opened = []
    monkeypatch.setattr(
        gui_loadout_workbench, "open_loadout_workbench", loadout_hosts.append
    )
    monkeypatch.setattr(
        gui_pack_query,
        "open_pack_query_dialog",
        lambda host, provider, _missing, **kwargs: opened.append(
            (host, provider(), kwargs)
        ),
    )
    monkeypatch.setattr(
        topbar.filedialog, "askdirectory", lambda **_kwargs: str(tmp_path)
    )
    monkeypatch.setattr(gui_export_actions, "load_last_pack_dir", lambda: "")
    monkeypatch.setattr(gui_export_actions, "save_last_pack_dir", lambda _path: None)
    topbar.build_topbar(app)
    assert app.pack_query_button.options["state"] == "disabled"
    app.data_tools_menu.commands["离线装备方案"]()
    app.data_tools_menu.commands["打开本地资料包查询（离线）"]()
    assert loadout_hosts == [app]
    assert opened == [(app, str(tmp_path), {"prefill": "", "prefill_command": ""})]
    assert topbar._open_local_pack_query(
        app, pack_dir=str(tmp_path), prefill="", prefill_command="calls"
    ) == str(tmp_path)
    assert opened[-1] == (
        app,
        str(tmp_path),
        {"prefill": "", "prefill_command": "calls"},
    )
