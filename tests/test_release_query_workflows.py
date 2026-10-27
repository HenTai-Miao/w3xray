"""Release workflows through the shared query API and the query window."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from gametool import gui_pack_query as gui
from gametool import pack_query_cli as queries
from gametool.pack_query_options import PackQueryCliOptions


@pytest.fixture(autouse=True)
def isolated_query_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    monkeypatch.setattr(gui, "_memo_dir", lambda: str(tmp_path / "gui-memo"))
    monkeypatch.setattr(gui, "_HISTORY", [])
    monkeypatch.setattr(gui, "_PINNED", [])
    monkeypatch.setattr(gui, "_WINDOW_GEOMETRY", {})
    monkeypatch.setattr(gui, "_save_memo", lambda: None)


def _pack(pack: Path) -> None:
    objects = pack / "对象ID"
    scripts = pack / "脚本可读文本"
    objects.mkdir(parents=True)
    scripts.mkdir()
    (objects / "单位.tsv").write_text(
        "分类\tID\t数值\t基础ID\t名称\t自定义\t说明\n单位\tn001\t1\tn001\t商人\t是\t\n",
        encoding="utf-8",
    )
    (objects / "物品.tsv").write_text(
        "分类\tID\t数值\t基础ID\t名称\t自定义\t说明\n物品\tI001\t1\tI001\t宝石\t是\t\n",
        encoding="utf-8",
    )
    (pack / "对象字段.tsv").write_text(
        "单位\tn001\t商人\tusei\t货架\tI001\n", encoding="utf-8"
    )
    (scripts / "war3map.j").write_text(
        "function Init takes nothing returns nothing\n"
        "local trigger t = CreateTrigger()\n"
        'call TriggerRegisterPlayerChatEvent(t,Player(0),"-one",true)\n'
        'call TriggerRegisterPlayerChatEvent(t,Player(1),"-two",false)\n'
        'call TriggerRegisterPlayerChatEvent(t,Player(2),"-",true)\n'
        'call TriggerRegisterPlayerChatEvent(t,Player(3),"",false)\n'
        "endfunction\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("command", ["cmd", "shop"])
def test_empty_listing_is_shared_by_cli_gui_and_again(
    tmp_path: Path, command: str
) -> None:
    pack = tmp_path / "pack"
    _pack(pack)
    options = queries.parse_pack_query_cli_options([str(pack), command])
    full = queries.execute_pack_query(options)
    window = cast(
        gui._PackQueryWindow, cast(object, SimpleNamespace(_pack_dir=str(pack)))
    )
    text, _ = gui._PackQueryWindow._run_query(window, command, "")
    assert full.exit_code == 0 and full.render() in text
    assert queries._load_last_query() == {
        "pack": str(pack),
        "command": command,
        "query": "",
    }
    replay = queries.execute_pack_query(PackQueryCliOptions(str(pack), "again", ""))
    assert replay.exit_code == 0 and full.render() in replay.render()
    if command == "cmd":
        assert all(f'指令 "{value}"' in text for value in ("-one", "-two", "-", ""))
        limited = queries.execute_pack_query(
            PackQueryCliOptions(str(pack), "cmd", "", limit=1)
        )
        assert limited.render().count('指令 "') == 1
        assert "其余 3 条" in limited.render()


def test_chat_miss_with_anonymous_listener_does_not_replace_successful_replay(
    tmp_path: Path,
) -> None:
    _pack(tmp_path / "pack")
    pack = str(tmp_path / "pack")
    success = queries.execute_pack_query(PackQueryCliOptions(pack, "item", "I001"))
    memo = queries._memo_dir() / queries._LAST_QUERY_FILE
    before = memo.read_bytes()
    missed = queries.execute_pack_query(PackQueryCliOptions(pack, "cmd", "missing"))
    assert success.exit_code == 0 and missed.exit_code == 2
    assert "空串聊天事件" in missed.render()
    assert memo.read_bytes() == before


def test_successful_relative_pack_replays_from_another_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pack(tmp_path / "first" / "pack")
    second = tmp_path / "second"
    second.mkdir()
    monkeypatch.chdir(tmp_path / "first")
    assert (
        queries.execute_pack_query(
            PackQueryCliOptions("pack", "item", "I001")
        ).exit_code
        == 0
    )
    monkeypatch.chdir(second)
    again = queries.execute_pack_query(PackQueryCliOptions("", "again", ""))
    assert again.exit_code == 0 and "宝石" in again.render()


@pytest.mark.parametrize(
    "bad_history", [{"unexpected": 1}, [1, ["doc"], ["item", None]], None]
)
def test_bad_history_does_not_block_independent_favorites_and_geometry(
    tmp_path: Path, bad_history: object
) -> None:
    memo = tmp_path / "gui-memo"
    memo.mkdir()
    (memo / "history.json").write_text(json.dumps(bad_history), encoding="utf-8")
    (memo / "pinned.json").write_text(
        json.dumps([["宝石", "已保存内容"]]), encoding="utf-8"
    )
    (memo / "geometry.json").write_text(
        json.dumps({"pack-query": "760x560+20+30"}), encoding="utf-8"
    )
    gui._load_memo()
    assert gui._HISTORY == []
    assert gui._PINNED == [("宝石", "已保存内容")]
    assert gui._WINDOW_GEOMETRY == {"pack-query": "760x560+20+30"}


def _window(monkeypatch: pytest.MonkeyPatch):
    """Drive real window callbacks with an explicitly ordered event queue."""
    workers = []
    polls = []
    delivered = []
    keyword = SimpleNamespace(value="first")
    keyword.get = lambda: keyword.value
    widget = SimpleNamespace(configure=lambda **_kwargs: None, set=lambda _value: None)
    output = SimpleNamespace(delete=lambda *_args: None, insert=lambda *_args: None)
    window = SimpleNamespace(
        _keyword=keyword,
        _history=widget,
        _output=output,
        _find_state={"start": "1.0"},
        _var_json=SimpleNamespace(get=lambda: False),
        configure=lambda **_kwargs: None,
        winfo_exists=lambda: True,
        after=lambda _milliseconds, callback: polls.append(callback),
        _finish=lambda *values: delivered.append(values),
        _run_query=lambda _command, word, _json: (word, "elapsed"),
    )
    monkeypatch.setattr(
        "threading.Thread",
        lambda *, target, daemon: SimpleNamespace(start=lambda: workers.append(target)),
    )
    return window, workers, polls, delivered


def test_new_query_owns_delivery_even_if_the_older_worker_finishes_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, workers, polls, delivered = _window(monkeypatch)
    gui._PackQueryWindow._run(cast(gui._PackQueryWindow, cast(object, window)), "text")
    window._keyword.value = "second"
    gui._PackQueryWindow._run(cast(gui._PackQueryWindow, cast(object, window)), "text")
    workers[1]()
    polls[1]()
    workers[0]()
    polls[0]()
    assert delivered == [("second", "elapsed")]


def test_worker_failure_is_delivered_instead_of_polling_forever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, workers, polls, delivered = _window(monkeypatch)

    def failure(*_args):
        raise ValueError("broken saved comparison path")

    window._run_query = failure
    gui._PackQueryWindow._run(cast(gui._PackQueryWindow, cast(object, window)), "text")
    workers[0]()
    polls[0]()
    assert len(delivered) == 1 and "broken saved comparison path" in delivered[0][0]
    assert "查询失败" in delivered[0][0]


def test_closed_query_window_never_receives_a_late_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, workers, polls, delivered = _window(monkeypatch)
    gui._PackQueryWindow._run(cast(gui._PackQueryWindow, cast(object, window)), "text")
    workers[0]()
    window.winfo_exists = lambda: False
    polls[0]()
    assert delivered == []


def test_delayed_initial_query_never_replaces_an_explicit_user_request() -> None:
    calls = []
    window = SimpleNamespace(
        winfo_exists=lambda: True,
        _query_generation=1,
        _switch_mode=lambda command: calls.append(command),
        _run=lambda command: calls.append(command),
    )
    gui._PackQueryWindow._run_initial(
        cast(gui._PackQueryWindow, cast(object, window)), "stats"
    )
    assert calls == []


def test_exported_original_script_preserves_offsets_and_localized_mirrors(
    tmp_path: Path,
) -> None:
    from gametool.knowledge_pack import write_knowledge_pack
    from gametool.map_data import MapData

    text = (
        'function Id(s) return FourCC("I001") end;\r\n'
        'CreateItem(Id("TRIGSTR_1"),1,2)\r\n'
    )
    md = MapData(
        path="synthetic.w3x",
        name="原始脚本来源",
        scripts={"war3map.lua": text},
        ui_strings={1: "已解析且长度不同的任务文本"},
    )
    write_knowledge_pack(md, str(tmp_path))
    assert queries.load_script_sources(tmp_path) == (("war3map.lua", text),)
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "1 2 0")
    )
    payload = json.loads(result.render(as_json=True))
    assert result.exit_code == 0
    assert len(payload["entries"]) == 1 and payload["entries"][0]["code"] == "I001"
    assert payload["spatial_diagnostics"] == []


def test_legacy_pack_without_original_scripts_keeps_readable_source_fallback(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "脚本可读文本"
    directory.mkdir()
    text = "call CreateItem('I001',1,2)\r\n"
    (directory / "war3map.j").write_bytes(text.encode("utf-8"))
    assert queries.load_script_sources(tmp_path) == (
        ("war3map.j", text.replace("\r\n", "\n")),
    )
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "1 2 0")
    )
    assert result.exit_code == 0 and "I001" in result.render()


@pytest.mark.parametrize("original_state", ["missing", "bad-encoding"])
def test_unavailable_original_never_uses_a_localized_copy_or_unbound_index_as_native(
    tmp_path: Path, original_state: str
) -> None:
    from gametool.script_call_argument_index import (
        build_script_call_argument_index,
        format_script_call_argument_index_tsv,
    )
    from gametool.map_data import MapData

    original = tmp_path / "脚本原始文本"
    readable = tmp_path / "脚本可读文本"
    original.mkdir()
    readable.mkdir()
    text = "call CreateItem('I001',1,2)\r\n"
    (readable / "war3map.j").write_bytes(text.encode("utf-8"))
    if original_state == "bad-encoding":
        (original / "war3map.j").write_bytes(b"\xff")
    md = MapData(path="synthetic.w3x", name="不完整源码", scripts={"war3map.j": text})
    (tmp_path / "脚本调用参数索引.tsv").write_text(
        format_script_call_argument_index_tsv(build_script_call_argument_index(md)),
        encoding="utf-8",
    )
    result = queries.execute_pack_query(
        PackQueryCliOptions(str(tmp_path), "near", "1 2 0")
    )
    payload = json.loads(result.render(as_json=True))
    assert result.exit_code == 2 and not payload["entries"]
    assert any("脚本原始文本" in warning for warning in payload["warnings"])
    assert any("原始脚本" in note["message"] for note in payload["spatial_diagnostics"])


@pytest.mark.parametrize(
    ("selection", "expected"),
    [
        ("hfoo", "hfoo"),
        ("I!é?", "I!é?"),
        (" a01", " a01"),
        ("[n001] 商人", "n001"),
        ("宝石(I!é?)", "I!é?"),
        ("'I001'", "I001"),
        ("[I001] / [n001]", None),
        ("SOMEWORD", None),
        ("无四码证据", None),
        ('{"units": [{"code": "n001", "items": []}]}', None),
        ('{"units": [{"a": 1}]}', None),
        ('{"selected": {"code": "I001"}}', None),
        ('["ab"]', None),
    ],
)
def test_query_code_handoff_preserves_runtime_identities_and_rejects_ambiguity(
    selection: str, expected: str | None
) -> None:
    from gametool.query_object_codes import code_from_text

    assert code_from_text(selection) == expected


@pytest.mark.parametrize(
    "command", ["doc", "export", "where", "drop", "recipe", "locate"]
)
def test_required_keyword_is_validated_by_the_shared_query_api(
    tmp_path: Path, command: str
) -> None:
    result = queries.execute_pack_query(PackQueryCliOptions(str(tmp_path), command, ""))
    assert result.exit_code == 2 and result.sections[0].input_error
    assert json.loads(result.render(as_json=True))["input_error"] is True
    assert not (queries._memo_dir() / queries._LAST_QUERY_FILE).exists()
