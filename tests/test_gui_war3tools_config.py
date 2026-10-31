"""Offline entry, complete views and Tk-safe War3Tools worker contracts."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import threading
from types import SimpleNamespace
from typing import Any, cast

import pytest

from gametool import gui_war3tools_config as gui
from gametool.war3tools_config_models import (
    War3ToolsFile,
    War3ToolsInspection,
    War3ToolsRecord,
    War3ToolsSetting,
    War3ToolsSource,
)
from gametool.war3tools_config_report import select_war3tools_report


def _selection(tmp_path: Path):
    source = str(tmp_path / "War3Tools.ini")
    raw = "[Main]\r\nEnable=true\r\n; 保留完整证据\r\n"
    records = (
        War3ToolsRecord(1, 1, "section", "[Main]\r\n", 0, 8, "Main", 1),
        War3ToolsRecord(
            2, 2, "setting", "Enable=true\r\n", 8, 21, "Main", 1, "Enable", "true"
        ),
        War3ToolsRecord(3, 3, "comment", "; 保留完整证据\r\n", 21, 43, "Main", 1),
    )
    file = War3ToolsFile(
        War3ToolsSource(source, "War3Tools.ini", raw_text=raw, stable=True),
        records,
        (
            War3ToolsSetting(
                source,
                2,
                "Main",
                1,
                "Enable",
                "true",
                "功能开关",
                "boolean",
                "启用",
                "declared",
                True,
            ),
        ),
        (),
        True,
    )
    inspection = War3ToolsInspection(
        source, "file", "auto", (), (file,), (), (), (), True, True, False, stable=True
    )
    return select_war3tools_report(inspection)


class _Value:
    def __init__(self, value: str, owner: int):
        self.value, self.owner = value, owner

    def get(self):
        assert threading.get_ident() == self.owner
        return self.value


class _Control:
    def __init__(self, owner: int):
        self.owner = owner
        self.changes: list[dict[str, object]] = []

    def configure(self, **values):
        assert threading.get_ident() == self.owner
        self.changes.append(values)


def _worker_harness(selection):
    owner = threading.get_ident()
    queued, started, received, states, cancelled = [], [], [], [], []

    def record_state(enabled):
        assert threading.get_ident() == owner
        states.append(enabled)

    def receive(*args, **kwargs):
        assert threading.get_ident() == owner
        received.append((args, kwargs))

    host = SimpleNamespace(
        _closed=False,
        _fresh=True,
        _source_current=True,
        _generation=4,
        _selection=selection,
        source_var=_Value(selection.inspection.path, owner),
        encoding_var=_Value("gb18030", owner),
        query_var=_Value("Enable", owner),
        status=_Control(owner),
        _memo=lambda: None,
        _set_export_state=record_state,
        _cancel_gui_worker_group=cancelled.append,
        title=lambda _title: None,
        _start_gui_worker=lambda group, work, replace: started.append(
            (group, work, replace)
        ),
        _post_gui_worker=lambda ticket, callback: queued.append(callback),
        _receive_selection=receive,
        _receive_error=lambda generation, message: received.append(
            (generation, message)
        ),
        _receive_export=receive,
    )
    return host, SimpleNamespace(
        owner=owner,
        queued=queued,
        started=started,
        received=received,
        states=states,
        cancelled=cancelled,
    )


def _run_worker(harness, *, cancelled: bool = False):
    cancellation = threading.Event()
    if cancelled:
        cancellation.set()
    thread = threading.Thread(
        target=harness.started[-1][1],
        args=(SimpleNamespace(cancellation=cancellation),),
    )
    thread.start()
    thread.join(timeout=3)
    assert not thread.is_alive()


def test_refresh_captures_inputs_on_main_thread_and_formats_off_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    selection = _selection(tmp_path)
    host, harness = _worker_harness(selection)
    observed = []
    original_format = gui.format_war3tools_report

    def inspect(path, *, text_encoding):
        assert threading.get_ident() != harness.owner
        observed.append((path, text_encoding))
        return selection.inspection

    def format_report(value):
        assert threading.get_ident() != harness.owner
        return original_format(value)

    def revalidate(value):
        assert threading.get_ident() != harness.owner
        return value

    monkeypatch.setattr(gui, "inspect_war3tools_config", inspect)
    monkeypatch.setattr(gui, "format_war3tools_report", format_report)
    monkeypatch.setattr(gui, "revalidate_war3tools_selection", revalidate)
    gui.War3ToolsConfigDialog.refresh(cast(Any, host))
    assert harness.started[0][0] == "war3tools-read"
    assert not host._fresh and not host._source_current
    _run_worker(harness)
    assert observed == [(selection.inspection.path, "gb18030")]
    assert len(harness.queued) == 1
    harness.queued.pop()()
    args, options = harness.received[0]
    assert args[0].query == "Enable" and len(args[0].records) == 1
    assert args[1] == 5
    payload = json.loads(options["views"]["完整 JSON"].text)
    assert len(payload["files"][0]["records"]) == 3
    assert "保留完整证据" in payload["files"][0]["source"]["raw_text"]


def test_prepare_revalidates_after_serialization_and_rebuilds_changed_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    selection = _selection(tmp_path)
    changed = replace(selection, inspection=replace(selection.inspection, stable=False))
    original_format, original_json = (
        gui.format_war3tools_report,
        gui.war3tools_report_to_dict,
    )
    operations = []

    def format_report(value):
        operations.append(("text", value.inspection.stable))
        return original_format(value)

    def as_dict(value):
        operations.append(("json", value.inspection.stable))
        return original_json(value)

    def revalidate(value):
        assert value is selection
        operations.append(("proof", False))
        return changed

    monkeypatch.setattr(gui, "format_war3tools_report", format_report)
    monkeypatch.setattr(gui, "war3tools_report_to_dict", as_dict)
    monkeypatch.setattr(gui, "revalidate_war3tools_selection", revalidate)
    checked, views = gui._prepare_report(selection)
    assert checked is changed and checked.records == selection.records
    assert operations == [
        ("text", True),
        ("json", True),
        ("proof", False),
        ("text", False),
        ("json", False),
    ]
    payload = json.loads(views["完整 JSON"].text)
    assert payload["stable"] is False and payload["exit_code"] == 2
    assert payload["files"][0]["source"]["raw_text"].endswith("; 保留完整证据\r\n")


@pytest.mark.parametrize("closed,generation", [(False, 5), (True, 4)])
def test_late_or_closed_delivery_preserves_current_ui(
    tmp_path: Path, closed: bool, generation: int
):
    host = SimpleNamespace(_closed=closed, _generation=generation)
    before = dict(vars(host))
    gui.War3ToolsConfigDialog._receive_selection(
        cast(Any, host), _selection(tmp_path), 4, views={}
    )
    gui.War3ToolsConfigDialog._receive_error(cast(Any, host), 4, "late error")
    gui.War3ToolsConfigDialog._receive_export(cast(Any, host), 4, "late.json", "")
    assert vars(host) == before


def test_query_edits_disable_export_but_keep_current_source_for_rescreening(
    tmp_path: Path,
):
    host, harness = _worker_harness(_selection(tmp_path))
    gui.War3ToolsConfigDialog._invalidate_query(cast(Any, host))
    assert host._generation == 5 and not host._fresh and host._source_current
    assert harness.states == [False]
    assert "war3tools-query" in harness.cancelled
    gui.War3ToolsConfigDialog._invalidate_source(cast(Any, host))
    assert not host._source_current and not host._fresh
    assert "war3tools-read" in harness.cancelled


@pytest.mark.parametrize(
    "stable,complete,input_error,exportable",
    [
        (True, True, False, True),
        (True, False, False, True),
        (False, True, False, False),
        (True, True, True, False),
    ],
)
def test_delivered_snapshot_controls_export_without_erasing_partial_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stable: bool,
    complete: bool,
    input_error: bool,
    exportable: bool,
):
    selection = _selection(tmp_path)
    selection = replace(
        selection,
        inspection=replace(
            selection.inspection,
            stable=stable,
            inspection_complete=complete,
            input_error=input_error,
        ),
    )
    monkeypatch.setattr(gui, "_session_selection", None)
    monkeypatch.setattr(gui, "_session_views", {})
    host, harness = _worker_harness(selection)
    rendered = []
    host.view_var = _Value("配置与诊断", harness.owner)
    host._switch_view = rendered.append
    views = gui._build_views(selection)
    gui.War3ToolsConfigDialog._receive_selection(
        cast(Any, host), selection, 4, views=views
    )
    assert host._selection is selection and host._views is views
    assert host._fresh is exportable and host._source_current is exportable
    assert harness.states == [exportable] and rendered == ["配置与诊断"]
    assert "完整诊断与原始证据保留" in host.status.changes[-1]["text"]


def test_search_reuses_explicit_snapshot_and_delivers_changed_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    selection = _selection(tmp_path)
    host, harness = _worker_harness(selection)
    changed = replace(selection.inspection, stable=False)
    monkeypatch.setattr(
        gui,
        "inspect_war3tools_config",
        lambda *_args, **_kwargs: pytest.fail("Search must use the selected snapshot"),
    )
    monkeypatch.setattr(
        gui,
        "revalidate_war3tools_selection",
        lambda value: replace(value, inspection=changed),
    )
    gui.War3ToolsConfigDialog.search(cast(Any, host))
    assert harness.started[0][0] == "war3tools-query"
    _run_worker(harness)
    harness.queued.pop()()
    args, options = harness.received[0]
    assert not args[0].inspection.stable
    assert len(args[0].records) == 1
    assert json.loads(options["views"]["完整 JSON"].text)["settings_total"] == 1


def test_worker_failure_remains_actionable_and_does_not_create_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    host, harness = _worker_harness(_selection(tmp_path))

    def fail(*_args, **_kwargs):
        raise ValueError("SYNTHETIC_ENCODING_FAILURE")

    monkeypatch.setattr(gui, "inspect_war3tools_config", fail)
    gui.War3ToolsConfigDialog.refresh(cast(Any, host))
    _run_worker(harness)
    harness.queued.pop()()
    generation, message = harness.received[0]
    assert generation == 5 and "SYNTHETIC_ENCODING_FAILURE" in message
    assert "编码后重试" in message and not host._fresh


@pytest.mark.parametrize("format", ("json", "md", "tsv"))
def test_export_uses_selected_complete_report_from_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, format: str
):
    selection = _selection(tmp_path)
    host, harness = _worker_harness(selection)
    destination = tmp_path / ("report." + format)
    exports = []

    def choose(**_kwargs):
        assert threading.get_ident() == harness.owner
        return str(destination)

    def write(path, report, chosen_format):
        assert threading.get_ident() != harness.owner
        exports.append((path, report, chosen_format))
        return destination

    monkeypatch.setattr(gui.filedialog, "asksaveasfilename", choose)
    monkeypatch.setattr(gui, "write_war3tools_export", write)
    gui.War3ToolsConfigDialog.export_report(cast(Any, host), format)
    assert harness.started[0][0] == "war3tools-export"
    _run_worker(harness)
    assert exports == [(str(destination), selection, format)]
    harness.queued.pop()()
    assert harness.received == [((4, str(destination), ""), {})]


def test_cancelled_export_never_publishes_selected_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    host, harness = _worker_harness(_selection(tmp_path))
    monkeypatch.setattr(
        gui.filedialog,
        "asksaveasfilename",
        lambda **_kwargs: str(tmp_path / "report.json"),
    )
    monkeypatch.setattr(
        gui,
        "write_war3tools_export",
        lambda *_args: pytest.fail("Cancelled job must not publish"),
    )
    gui.War3ToolsConfigDialog.export_report(cast(Any, host), "json")
    _run_worker(harness, cancelled=True)
    assert not harness.queued


def test_preferences_preserve_complete_input_and_fail_open_in_private_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "memo.json"
    monkeypatch.setattr(gui, "_memo_path", lambda: path)
    values = {
        "source": "C:/明确选择/War3Tools",
        "query": "显示 && 开关\n完整原值",
        "encoding": "utf-16-le",
        "view": "完整 JSON",
    }
    gui._save_memo(values)
    assert gui._load_memo() == values
    path.write_text("broken", encoding="utf-8")
    assert gui._load_memo() == {}


def test_report_navigation_retains_every_section_and_complete_text():
    text = (
        "# 标题\n\n== 查询结果 ==\n" + "完整内容\n" * 20000 + "## 完整来源\n最后一条\n"
    )
    view = gui._report_view(text)
    assert view.text == text
    assert [name for name, _line in view.sections] == ["查询结果", "完整来源"]


def test_chunked_presentation_has_no_content_limit_and_discards_old_view(
    monkeypatch: pytest.MonkeyPatch,
):
    class Text:
        def __init__(self):
            self.value = ""

        def configure(self, **_values):
            pass

        def delete(self, *_args):
            self.value = ""

        def insert(self, _position, text):
            self.value += text

        def see(self, _position):
            pass

    class Button:
        def __init__(self, *_args, **_kwargs):
            pass

        def pack(self, **_kwargs):
            pass

        def destroy(self):
            pass

    monkeypatch.setattr(gui.ctk, "CTkButton", Button)
    queued, jumps = [], []
    host = SimpleNamespace(
        _text_epoch=0,
        _jump_buttons=[],
        _find_start="25.0",
        _find_keyword="old",
        details=Text(),
        jump_bar=object(),
        _schedule=queued.append,
        _jump=jumps.append,
    )
    old = gui._report_view("旧快照\n" * 20000)
    current = gui._report_view("## 全部声明\n" + "完整内容\n" * 20000 + "最后一条\n")
    gui.War3ToolsConfigDialog._show_view(cast(Any, host), old)
    gui.War3ToolsConfigDialog._show_view(cast(Any, host), current)
    while queued:
        queued.pop(0)()
    assert host.details.value == current.text == host._detail_text
    assert host._find_start == "1.0" and host._find_keyword == ""
    assert jumps == [0]


def test_destroy_retires_owned_callbacks_and_workers_once(
    monkeypatch: pytest.MonkeyPatch,
):
    dialog = object.__new__(gui.War3ToolsConfigDialog)
    dialog._closed = False
    dialog._generation = 3
    dialog._scheduled = {"owned-text"}
    calls = []
    monkeypatch.setattr(
        gui.War3ToolsConfigDialog, "_memo", lambda _self: calls.append("memo")
    )
    monkeypatch.setattr(
        gui, "cancel_widget_callbacks", lambda _self: calls.append("cancel-tree")
    )
    monkeypatch.setattr(
        gui.War3ToolsConfigDialog,
        "after_cancel",
        lambda _self, identifier: calls.append(identifier),
    )
    monkeypatch.setattr(
        gui.War3ToolsConfigDialog,
        "_shutdown_gui_worker_host",
        lambda _self, timeout: calls.append(("workers", timeout)),
    )
    monkeypatch.setattr(
        gui.ctk.CTkToplevel, "destroy", lambda _self: calls.append("base")
    )
    dialog.destroy()
    dialog.destroy()
    assert calls == ["memo", "cancel-tree", "owned-text", ("workers", 0), "base"]
    assert dialog._closed and dialog._generation == 4 and not dialog._scheduled


def test_data_tools_menu_opens_real_offline_dialog_without_a_map(
    monkeypatch: pytest.MonkeyPatch,
):
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

    opened = []
    monkeypatch.setattr(gui, "open_war3tools_config_dialog", opened.append)
    for name in ("CTkFrame", "CTkLabel", "CTkButton"):
        monkeypatch.setattr(topbar.ctk, name, Widget)
    monkeypatch.setattr(topbar.tk, "Menu", Menu)
    monkeypatch.setattr(topbar, "_attach_tooltip", lambda *_args: None)
    app = App(map_data=None)
    topbar.build_topbar(app)
    app.data_tools_menu.commands["War3Tools 配置总览（离线）"]()
    assert opened == [app]
    assert app.pack_query_button.options["state"] == "disabled"
