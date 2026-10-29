"""Drive query-window controls without constructing a Tcl/Tk interpreter."""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from gametool import gui_pack_query as gui
from gametool.gui_pack_query_modes import MODE_ROWS, mode_row_labels
from gametool.gui_shell_object_panel import _pack_query_selected


class Widget:
    def __init__(self, *_args: object, **options: object) -> None:
        self.options = dict(options)
        self.value = ""
        self.bindings: dict[str, Callable[..., object]] = {}
        self.visible = False

    def pack(self, **_kwargs: object) -> None:
        self.visible = True

    def pack_forget(self) -> None:
        self.visible = False

    def configure(self, **options: object) -> None:
        self.options.update(options)

    def set(self, value: str) -> None:
        self.value = value

    def get(self, *_args: object) -> str:
        return self.value

    def insert(self, index: object, value: str, *_tags: object) -> None:
        self.value = self.value + value if index == "end" else value + self.value

    def delete(self, *_args: object) -> None:
        self.value = ""

    def bind(self, event: str, callback: Callable[..., object]) -> None:
        self.bindings[event] = callback

    def focus_set(self) -> None:
        return None

    def tag_config(self, *_args: object, **_kwargs: object) -> None:
        return None

    def tag_delete(self, *_args: object) -> None:
        return None

    def tag_bind(self, *_args: object) -> None:
        return None

    @property
    def selected(self) -> str | None:
        values = cast(list[str], self.options.get("values", []))
        return self.value if self.value in values else None

    def click(self, value: str) -> None:
        assert value in cast(list[str], self.options["values"])
        self.set(value)
        cast(Callable[[str], None], self.options["command"])(value)


class Menu:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.commands: list[dict[str, object]] = []

    def add_command(self, **options: object) -> None:
        self.commands.append(options)

    def add_separator(self) -> None:
        return None


@pytest.fixture
def window_factory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Execute the real constructor and callbacks with inert widget ports."""
    monkeypatch.setattr(gui, "_memo_dir", lambda: str(tmp_path / "memo"))
    monkeypatch.setattr(gui, "_HISTORY", [])
    monkeypatch.setattr(gui, "_PINNED", [])
    monkeypatch.setattr(gui, "_WINDOW_GEOMETRY", {})
    monkeypatch.setattr(gui, "_LAST_MODE", "doc")
    monkeypatch.setattr(gui, "_LAST_KEYWORD", "previous keyword")
    monkeypatch.setattr(gui, "_LAST_RESULT", "previous result")
    monkeypatch.setattr(gui, "bind_geometry_memory", lambda *_args: None)
    monkeypatch.setattr(gui.ctk.CTkToplevel, "__init__", lambda *_args: None)
    for name in (
        "title",
        "configure",
        "transient",
        "grab_set",
        "bind",
        "bind_all",
    ):
        monkeypatch.setattr(gui._PackQueryWindow, name, lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gui._PackQueryWindow, "winfo_exists", lambda _self: True)
    monkeypatch.setattr(gui._PackQueryWindow, "after", lambda *_args: None)
    monkeypatch.setattr(
        gui._PackQueryWindow,
        "clipboard_clear",
        lambda self: setattr(self, "_test_clipboard", ""),
    )
    monkeypatch.setattr(
        gui._PackQueryWindow,
        "clipboard_append",
        lambda self, value: setattr(self, "_test_clipboard", value),
    )
    for name in (
        "CTkFrame",
        "CTkLabel",
        "CTkOptionMenu",
        "CTkButton",
        "CTkEntry",
        "CTkSegmentedButton",
        "CTkTextbox",
        "CTkCheckBox",
        "StringVar",
        "BooleanVar",
    ):
        monkeypatch.setattr(gui.ctk, name, Widget)
    monkeypatch.setattr(gui.tk, "Menu", Menu)

    def create(command: str = "", keyword: str = "") -> gui._PackQueryWindow:
        return gui._PackQueryWindow(None, str(tmp_path / "pack"), keyword, command)

    return create


def _rows(window: gui._PackQueryWindow) -> tuple[Widget, ...]:
    return cast(
        tuple[Widget, ...],
        (window._mode, window._mode_extra, window._mode_extra2),
    )


@pytest.mark.parametrize(
    ("commands", "row_index"),
    [
        (
            "doc search list buffs export synth skills units locate near where drop",
            0,
        ),
        ("again stats shop tech item heroes", 1),
        ("price quest cmd text refs affixes registered diff calls", 2),
    ],
)
def test_every_mode_selects_only_its_actual_row_after_restore_and_click(
    window_factory, commands: str, row_index: int
) -> None:
    for command in commands.split():
        label = "脚本调用" if command == "calls" else command
        window = window_factory(command)
        rows = _rows(window)
        expected: list[str | None] = [None, None, None]
        expected[row_index] = label
        assert window._mode.get() == command
        assert [row.selected for row in rows] == expected
        # A real click on another row must clear the previous active control.
        rows[(row_index + 1) % len(rows)].click(
            mode_row_labels((row_index + 1) % len(rows))[0]
        )
        rows[row_index].click(label)
        assert window._mode.get() == command
        assert [row.selected for row in rows] == expected
        assert cast(Widget, window._near_kind).visible == (command == "near")


def test_explicit_empty_calls_prefill_does_not_inherit_previous_keyword(
    window_factory,
) -> None:
    window = window_factory("calls")
    assert window._keyword.get() == ""
    assert cast(Widget, window._keyword).options["placeholder_text"] == (
        "API / 四码 / 参数… 支持 &&、||、%、括号；空词=全部脚本调用"
    )
    requests: list[tuple[str, str]] = []
    window._run = lambda command: requests.append((command, window._keyword.get()))
    window._run_initial("calls")
    assert requests == [("calls", "")]


def test_calls_display_label_dispatches_canonical_command(window_factory) -> None:
    window = window_factory("doc")
    requests: list[str] = []
    window._run = requests.append
    _rows(window)[2].click("脚本调用")
    window._run_clicked()
    assert requests == ["calls"]
    assert window._mode.get() == "calls"


def test_last_session_calls_mode_restores_its_own_row_and_keyword(
    window_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gui, "_LAST_MODE", "calls")
    window = window_factory()
    assert window._keyword.get() == "previous keyword"
    assert window._mode.get() == "calls"
    assert [row.selected for row in _rows(window)] == [None, None, "脚本调用"]


def test_history_restores_calls_and_other_rows_with_exact_query(
    window_factory,
) -> None:
    window = window_factory("calls")
    requests: list[tuple[str, str]] = []
    window._run = lambda command: requests.append((command, window._keyword.get()))
    gui._HISTORY[:] = [
        ("calls", ""),
        ("calls", "SetPlayerState && gold"),
        ("price", "I001"),
        ("item", "I002"),
        ("doc", "I003"),
    ]
    for command, keyword in gui._HISTORY:
        window._on_history_pick(f"{command} {keyword}".strip())
        assert window._mode.get() == command
        assert requests[-1] == (command, keyword)
        assert sum(row.selected is not None for row in _rows(window)) == 1


def test_calls_history_survives_disk_roundtrip_without_display_label(
    window_factory,
) -> None:
    window_factory("calls")
    gui._HISTORY[:] = [("calls", ""), ("calls", "I001 || A001")]
    gui._save_memo()
    gui._HISTORY.clear()
    gui._load_memo()
    assert gui._HISTORY == [("calls", ""), ("calls", "I001 || A001")]


@pytest.mark.parametrize("as_json", [False, True])
def test_calls_uses_shared_execution_without_a_result_limit(
    window_factory, monkeypatch: pytest.MonkeyPatch, as_json: bool
) -> None:
    from gametool import pack_query_cli as queries
    from gametool.pack_query_options import PackQueryCliOptions

    window = window_factory("calls")
    requests: list[PackQueryCliOptions] = []

    def execute(options: PackQueryCliOptions):
        requests.append(options)
        return SimpleNamespace(
            render=lambda *, as_json: (
                json.dumps({"command": "calls"})
                if as_json
                else "complete call text\nraw arguments\nsource"
            ),
            extra_diagnostics=("source coverage diagnostic",),
        )

    monkeypatch.setattr(queries, "execute_pack_query", execute)
    body, diagnostics = window._run_query("calls", "", as_json)
    assert requests == [
        PackQueryCliOptions(window._pack_dir, "calls", "", limit=0, as_json=as_json)
    ]
    assert diagnostics == "source coverage diagnostic"
    assert (
        json.loads(body) == {"command": "calls"}
        if as_json
        else body == "complete call text\nraw arguments\nsource"
    )


def test_calls_favorites_and_md_export_keep_complete_record_text(
    window_factory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from gametool import archive_export

    output = tmp_path / "exports"
    output.mkdir()
    monkeypatch.setattr(archive_export, "tmp_extract_dir", lambda _label: str(output))
    window = window_factory("calls", "SetPlayerState")
    report = (
        "来源 子地图/001/脚本原始文本/war3map.j:17\n"
        "call SetPlayerState(Player(0), PLAYER_STATE_RESOURCE_GOLD, 123)\n"
        "参数原文\t完整多行\r\n额外来源证据\n" + "extended argument " * 400
    )
    window._output.delete("1.0", "end")
    window._output.insert("1.0", report)
    window._pin_current()
    assert gui._PINNED == [("calls SetPlayerState", report.strip())]
    assert report.strip() in window._pinned_box.get("1.0", "end")
    assert "1 项" in cast(str, cast(Widget, window._pin_button).options["text"])
    window._export_md(window._pinned_box, "收藏对比")
    exported = output / "收藏对比.md"
    assert exported.read_bytes() == (
        window._pinned_box.get("1.0", "end").strip() + "\n"
    ).encode("utf-8")
    assert window.__dict__["_test_clipboard"] == str(exported)
    assert str(exported) in window._output.get("1.0", "end")


@pytest.mark.parametrize("category", ["技能", "增益", "科技", "单位", "物品", "装饰物"])
def test_object_calls_handoff_keeps_explicit_command_and_exact_code(
    category: str,
) -> None:
    requests: list[dict[str, str]] = []
    host = SimpleNamespace(
        _selected_detail_object=SimpleNamespace(category=category, obj_id="A!  "),
        on_pack_query=lambda **request: requests.append(request),
    )
    _pack_query_selected(host, "calls")
    assert requests == [{"prefill": "A!  ", "prefill_command": "calls"}]


def test_mode_rows_retain_all_existing_commands_and_new_calls() -> None:
    commands = [command for row in MODE_ROWS for command in row]
    assert len(commands) == len(set(commands)) == 27
    assert set(commands) == set(gui._PackQueryWindow._PLACEHOLDERS)
