"""Real Tk callback bridge, keyboard/menu and closed-guide regressions."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import sys
from time import monotonic, sleep
import tkinter as tk
from traceback import format_exception
from typing import Any
from uuid import uuid4

import customtkinter as ctk
import pytest

from gametool import gui_topbar
from gametool.dev_test import create_test_environment
from gametool.map_data import MapData
from tests.gui_base import GuiTestCase, _get_app


@dataclass
class Guide:
    root: tk.Tk
    window: ctk.CTkToplevel
    entry: ctk.CTkEntry
    box: ctk.CTkTextbox
    menu: tk.Menu
    errors: list[str]
    callbacks: dict[str, Callable[..., Any]]
    queries: list[dict[str, Any]]
    source_path: str


def _command(widget, sequence: str) -> str:
    script = widget.bind(sequence)
    assert script, sequence
    match = re.search(r"\[([^\s\]]+)", script)
    assert match is not None, script
    return match.group(1)


@pytest.fixture
def guide(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Guide]:
    # Keep StringVars, PhotoImages and CTk's cached images on the same Tcl
    # interpreter as the rest of the GUI suite; never destroy the shared App.
    root = _get_app()
    baseline = GuiTestCase()
    baseline.app = root
    baseline.setUp()
    callbacks: dict[str, Callable[..., Any]] = {}
    callback_owners: dict[str, str] = {}
    register = getattr(tk.Misc, "_register")

    def record(widget, func, subst=None, needcleanup=1):
        name = register(widget, func, subst, needcleanup)
        callbacks[name] = func
        callback_owners[name] = str(widget)
        return name

    monkeypatch.setattr(tk.Misc, "_register", record)
    errors: list[str] = []
    queries: list[dict[str, Any]] = []
    source_path = str(tmp_path / "synthetic-guide.w3x")
    monkeypatch.setattr(root, "map_data", MapData(path=source_path, name="合成攻略"))
    monkeypatch.setattr(root, "on_pack_query", lambda **kwargs: queries.append(kwargs))
    monkeypatch.setattr(
        root,
        "report_callback_exception",
        lambda kind, error, trace: errors.append(
            "".join(format_exception(kind, error, trace))
        ),
    )
    token = uuid4().hex
    saved_bgerror = f"saved_guide_bgerror_{token}"
    error_command = f"record_guide_bgerror_{token}"
    had_bgerror = bool(root.tk.call("info", "commands", "bgerror"))
    if had_bgerror:
        root.tk.call("rename", "bgerror", saved_bgerror)
    root.tk.createcommand(
        error_command,
        lambda message: errors.append("Tcl bgerror: " + str(message)),
    )
    root.tk.call("proc", "bgerror", "message", error_command + " $message")
    previous = set(root.winfo_children())
    previous_state = root.state()
    root.deiconify()
    gui_topbar._open_guide_window(
        root,
        "【基本信息】\nneedle first\nneedle second\n物品 [I001]\n坐标 @(1.25, -2.5)\n",
    )
    window = next(
        child
        for child in root.winfo_children()
        if child not in previous and isinstance(child, ctk.CTkToplevel)
    )
    widgets: list[Any] = []
    pending = list(window.winfo_children())
    while pending:
        widget = pending.pop()
        widgets.append(widget)
        pending.extend(widget.winfo_children())
    box = next(widget for widget in widgets if isinstance(widget, ctk.CTkTextbox))
    entry = next(widget for widget in widgets if isinstance(widget, ctk.CTkEntry))
    menu = next(widget for widget in widgets if isinstance(widget, tk.Menu))
    root.update_idletasks()
    root.update()
    try:
        assert getattr(tk, "_default_root") is root
        yield Guide(
            root, window, entry, box, menu, errors, callbacks, queries, source_path
        )
    finally:
        if window.winfo_exists():
            window.destroy()
        # CTk child animations can outlive their destroyed widgets. Retire only
        # this fixture's descendant callbacks before another test reuses App;
        # the close assertions above still run against the real live queue.
        owned = {
            name
            for name, owner in callback_owners.items()
            if owner == str(window) or owner.startswith(str(window) + ".")
        }
        for after_id in root.tk.splitlist(root.tk.call("after", "info")):
            data = root.tk.call("after", "info", after_id)
            script = root.tk.splitlist(data)[0]
            commands = root.tk.splitlist(script)
            if commands and commands[0] in owned:
                root.tk.call("after", "cancel", after_id)
        root.update()
        root.tk.call("rename", "bgerror", "")
        if had_bgerror:
            root.tk.call("rename", saved_bgerror, "bgerror")
        root.tk.deletecommand(error_command)
        root.state(previous_state)


def test_zero_argument_tcl_commands_and_real_keyboard_events(
    guide: Guide, monkeypatch: pytest.MonkeyPatch
) -> None:
    for sequence in ("<Control-f>", "<Control-F>"):
        command = _command(guide.window, sequence)
        assert guide.root.tk.call(command) == "break"
        guide.window.focus_force()
        guide.window.event_generate(sequence, when="now")
        guide.root.update()
        assert guide.root.focus_get() is guide.entry._entry
    for sequence in ("<Control-a>", "<Control-A>"):
        guide.box.tag_remove("sel", "1.0", "end")
        assert guide.root.tk.call(_command(guide.window, sequence)) == "break"
        assert guide.box.get("sel.first", "sel.last") == guide.box.get("1.0", "end")
        guide.box.tag_remove("sel", "1.0", "end")
        guide.window.focus_force()
        guide.window.event_generate(sequence, when="now")
        assert guide.box.get("sel.first", "sel.last") == guide.box.get("1.0", "end")
    guide.box.tag_remove("sel", "1.0", "end")
    guide.entry.delete(0, "end")
    guide.box.mark_set("insert", "1.0")
    guide.entry.insert(0, "needle")
    guide.root.tk.call(_command(guide.entry._entry, "<Return>"))
    assert guide.box.index("insert") == "2.0"
    guide.entry._entry.focus_force()
    guide.entry._entry.event_generate("<Return>", when="now")
    assert guide.box.index("insert") == "3.0"
    popups = []
    monkeypatch.setattr(tk.Menu, "tk_popup", lambda self, x, y: popups.append((x, y)))
    guide.root.tk.call(_command(guide.box._textbox, "<Button-3>"))
    assert len(popups) == 1
    guide.box._textbox.event_generate(
        "<Button-3>", x=10, y=20, rootx=110, rooty=220, when="now"
    )
    assert popups[-1] == (110, 220)
    assert guide.errors == []


@pytest.mark.parametrize("event_mode", (False, True))
def test_escape_closes_with_zero_arguments_or_real_event(
    guide: Guide, event_mode: bool
) -> None:
    if event_mode:
        guide.window.focus_force()
        guide.window.event_generate("<Escape>", when="now")
    else:
        guide.root.tk.call(_command(guide.window, "<Escape>"))
    guide.root.update()
    assert not guide.window.winfo_exists()
    assert guide.source_path in gui_topbar._GUIDE_SCROLL
    assert guide.errors == []


def test_context_commands_preserve_copy_export_refresh_query_and_near(
    guide: Guide, monkeypatch: pytest.MonkeyPatch
) -> None:
    copied = []
    exported = []
    refreshed = []
    monkeypatch.setattr(guide.box, "clipboard_clear", lambda: None)
    monkeypatch.setattr(guide.box, "clipboard_append", copied.append)
    monkeypatch.setattr(
        gui_topbar, "_export_guide", lambda app, text: exported.append((app, text))
    )
    monkeypatch.setattr(
        gui_topbar,
        "_show_guide",
        lambda app, refresh=False: refreshed.append((app, refresh)),
    )
    guide.box.tag_add("sel", "4.0", "4.end")
    guide.menu.invoke("复制选中")
    guide.menu.invoke("复制全部")
    assert copied == ["物品 [I001]", guide.box.get("1.0", "end")]
    guide.menu.invoke("导出报告 (.md)")
    guide.menu.invoke("强制重算 (清缓存刷新报告)")
    assert exported == [(guide.root, guide.box.get("1.0", "end"))]
    assert refreshed == [(guide.root, True)]
    for label in (
        "用选中/剪贴板码查包查询",
        "用选中/剪贴板码 where 反查获取途径",
        "用选中/剪贴板码 drop 反查掉落",
    ):
        guide.menu.invoke(label)
    assert [query["prefill_command"] for query in guide.queries] == [
        "doc",
        "where",
        "drop",
    ]
    assert all(query["prefill"] == "I001" for query in guide.queries)
    guide.box.tag_remove("sel", "1.0", "end")
    guide.box.tag_add("sel", "5.0", "5.end")
    guide.menu.invoke("用选中/剪贴板坐标 near 再查 (半径 500)")
    guide.menu.invoke("用选中坐标 near 再查 (半径 100, 更精细)")
    assert [query["prefill"] for query in guide.queries[-2:]] == [
        "1.25 -2.5 500",
        "1.25 -2.5 100",
    ]
    assert guide.errors == []


@pytest.mark.parametrize("close_mode", ("direct", "wm"))
def test_closed_guide_discards_queued_events_and_late_bridge_callbacks(
    guide: Guide, monkeypatch: pytest.MonkeyPatch, close_mode: str
) -> None:
    popups = []
    monkeypatch.setattr(tk.Menu, "tk_popup", lambda *args: popups.append(args))
    event_callbacks = [
        guide.callbacks[_command(guide.window, sequence)]
        for sequence in (
            "<Control-f>",
            "<Control-F>",
            "<Control-a>",
            "<Control-A>",
            "<Escape>",
        )
    ]
    event_callbacks.extend(
        (
            guide.callbacks[_command(guide.entry._entry, "<Return>")],
            guide.callbacks[_command(guide.box._textbox, "<Button-3>")],
        )
    )
    last = guide.menu.index("end")
    assert last is not None
    commands = [
        guide.callbacks[guide.menu.entrycget(index, "command")]
        for index in range(last + 1)
        if guide.menu.type(index) == "command"
    ]
    for sequence in ("<Control-f>", "<Control-A>", "<Escape>"):
        guide.window.event_generate(sequence, when="tail")
    guide.entry._entry.event_generate("<Return>", when="tail")
    guide.box._textbox.event_generate("<Button-3>", x=3, y=4, when="tail")
    event = tk.Event()
    event.x_root, event.y_root = 3, 4
    for callback in event_callbacks:
        guide.root.after_idle(callback)
        guide.root.after_idle(callback, event)
    for callback in commands:
        guide.root.after_idle(callback)
    queued = []
    owned_timer = guide.window.after(0, lambda: queued.append("guide"))
    guide.root.after_idle(lambda: queued.append("root"))
    if close_mode == "wm":
        guide.root.tk.call(guide.window.protocol("WM_DELETE_WINDOW"))
    else:
        guide.window.destroy()
    guide.root.update()
    guide.window.destroy()  # Idempotent when a second queued close arrives.
    assert guide.errors == []
    assert guide.queries == []
    assert popups == []
    assert queued == ["root"]
    assert owned_timer not in guide.root.tk.splitlist(
        guide.root.tk.call("after", "info")
    )


def _run_isolated_app_test(node: str, tmp_path: Path) -> None:
    env = create_test_environment()
    env["GAMEXRAY_GUIDE_CALLBACK_CHILD"] = node
    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-m",
            "pytest",
            "-q",
            "--basetemp",
            str(tmp_path / "child-pytest"),
            f"{Path(__file__).resolve()}::{node}",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


def test_parent_app_destroy_cancels_guide_timers_and_late_events(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    node = "test_parent_app_destroy_cancels_guide_timers_and_late_events"
    if os.environ.get("GAMEXRAY_GUIDE_CALLBACK_CHILD") != node:
        _run_isolated_app_test(node, tmp_path)
        return
    from gametool.gui import App

    callbacks = {}
    register = getattr(tk.Misc, "_register")

    def record(widget, func, subst=None, needcleanup=1):
        name = register(widget, func, subst, needcleanup)
        callbacks[name] = func
        return name

    monkeypatch.setattr(tk.Misc, "_register", record)
    app = App()
    app.withdraw()
    errors = []
    app.report_callback_exception = lambda kind, error, trace: errors.append(
        "".join(format_exception(kind, error, trace))
    )
    app.update_idletasks()
    app.update()
    gui_topbar._open_guide_window(app, "【基本信息】\n父窗口关闭路径\n")
    window = next(
        child for child in app.winfo_children() if isinstance(child, ctk.CTkToplevel)
    )
    late_callbacks = [
        callbacks[_command(window, sequence)]
        for sequence in (
            "<Control-f>",
            "<Control-F>",
            "<Control-a>",
            "<Control-A>",
            "<Escape>",
        )
    ]
    owned_timer = window.after(0, lambda: errors.append("closed guide timer ran"))
    app._shutdown_background_loader()
    app._shutdown_object_filter_runner()
    app._shutdown_gui_worker_host(timeout_seconds=1.5)
    app._shutdown_current_map_gui()
    app.destroy()
    assert owned_timer not in app.tk.splitlist(app.tk.call("after", "info"))
    for callback in late_callbacks:
        callback()
        callback(tk.Event())
    assert errors == []


def test_acceptance_callback_error_retains_full_traceback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    node = "test_acceptance_callback_error_retains_full_traceback"
    if os.environ.get("GAMEXRAY_GUIDE_CALLBACK_CHILD") != node:
        _run_isolated_app_test(node, tmp_path)
        return
    from gametool.gui_acceptance import run_gui_acceptance

    original = gui_topbar._open_guide_window

    def guide_callback_failure() -> None:
        try:
            raise ValueError("guide original cause")
        except ValueError as exc:
            raise RuntimeError("guide callback traceback marker") from exc

    def open_with_failing_callback(app, text):
        original(app, text)
        app.after(0, guide_callback_failure)

    monkeypatch.setattr(gui_topbar, "_open_guide_window", open_with_failing_callback)
    path = (
        Path(__file__).parents[1] / "tests/fixtures/maps/war3net-map-script-builder.w3x"
    )
    with pytest.raises(RuntimeError, match="GUI 回调异常") as caught:
        run_gui_acceptance(path)
    message = str(caught.value)
    assert "Traceback (most recent call last)" in message
    assert "guide_callback_failure" in message
    assert "test_guide_window_callbacks.py" in message
    assert "guide original cause" in message
    assert "guide callback traceback marker" in message


@pytest.mark.parametrize("error_kind", ("python", "tcl"))
def test_acceptance_reports_delayed_error_after_parent_destroy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    error_kind: str,
) -> None:
    node = f"test_acceptance_reports_delayed_error_after_parent_destroy[{error_kind}]"
    if os.environ.get("GAMEXRAY_GUIDE_CALLBACK_CHILD") != node:
        _run_isolated_app_test(node, tmp_path)
        return
    from gametool import gui_acceptance

    original_destroy = gui_acceptance._destroy_without_persisting
    destroyed = []
    fired = []
    marker = "delayed-parent-destroy-" + error_kind + "-" + uuid4().hex

    def delayed_python_failure() -> None:
        fired.append("python")
        try:
            raise ValueError("parent destroy original cause")
        except ValueError as exc:
            raise RuntimeError(marker) from exc

    def destroy_with_delayed_failure(app) -> None:
        original_destroy(app)
        assert not app.tk.call("info", "commands", ".")
        destroyed.append(app)
        # Register only after real destruction, so widget-owned cancellation
        # cannot hide the regression. This needs the final post-close pump.
        if error_kind == "python":
            app.after(100, delayed_python_failure)
        else:
            command = "::record_parent_destroy_error_" + uuid4().hex
            app.tk.createcommand(command, lambda: fired.append("tcl"))
            app.tk.call("after", 100, f"{command}; error {marker}")

    monkeypatch.setattr(
        gui_acceptance, "_destroy_without_persisting", destroy_with_delayed_failure
    )
    path = (
        Path(__file__).parents[1] / "tests/fixtures/maps/war3net-map-script-builder.w3x"
    )
    with pytest.raises(RuntimeError, match="GUI 回调异常") as caught:
        gui_acceptance.run_gui_acceptance(path)
    assert len(destroyed) == 1
    assert fired == [error_kind]
    message = str(caught.value)
    assert marker in message
    if error_kind == "python":
        assert "Traceback (most recent call last)" in message
        assert "delayed_python_failure" in message
        assert "test_guide_window_callbacks.py" in message
        assert "parent destroy original cause" in message
    else:
        assert "Tcl background error" in message
        assert "while executing" in message


def test_full_acceptance_query_close_retires_only_its_owned_timers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    node = "test_full_acceptance_query_close_retires_only_its_owned_timers"
    if os.environ.get("GAMEXRAY_GUIDE_CALLBACK_CHILD") != node:
        _run_isolated_app_test(node, tmp_path)
        return
    import json

    from gametool import gui_acceptance
    from gametool.gui_pack_query import _PackQueryWindow

    original_destroy = _PackQueryWindow.destroy
    observations: list[dict[str, Any]] = []
    closed: list[_PackQueryWindow] = []

    def observe_destroy(window: _PackQueryWindow) -> None:
        app = window.master
        assert app is not None
        owners: dict[str, str] = {}
        pending: list[tk.Misc] = [window]
        while pending:
            widget = pending.pop()
            owners.update(
                (command, str(widget))
                for command in getattr(widget, "_tclCommands", ()) or ()
            )
            pending.extend(widget.winfo_children())
        owned: dict[str, str] = {}
        for identifier in app.tk.splitlist(app.tk.call("after", "info")):
            info = app.tk.splitlist(app.tk.call("after", "info", identifier))
            script = app.tk.splitlist(info[0])
            if script and (owner := owners.get(str(script[0]))) is not None:
                owned[str(identifier)] = owner
        boxes = (str(window._output), str(window._pinned_box))
        sibling = tk.Toplevel(app)
        sibling.withdraw()
        fired: list[str] = []
        parent_timer = app.after(100, lambda: fired.append("parent"))
        sibling_timer = sibling.after(100, lambda: fired.append("sibling"))
        query_generation = window._query_generation
        observation = {
            "owned_before_close": owned,
            "textbox_owners": boxes,
            "query_generation": query_generation,
            "final_query": json.JSONDecoder().raw_decode(
                window._output.get("1.0", "end").lstrip()
            )[0],
            "external_fired": fired,
        }
        observations.append(observation)
        try:
            original_destroy(window)
            remaining = set(app.tk.splitlist(app.tk.call("after", "info")))
            observation["owned_after_close"] = sorted(set(owned) & remaining)
            observation["external_preserved"] = {
                parent_timer,
                sibling_timer,
            }.issubset(remaining)
            observation["generation_after_close"] = window._query_generation
            # Let the actual CTk textboxes' recurring timers become due while
            # the real acceptance App and its strict callback capture are live.
            deadline = monotonic() + 0.35
            while monotonic() < deadline:
                app.update_idletasks()
                app.update()
                sleep(0.01)
            closed.append(window)
        finally:
            sibling.destroy()

    original_exercise_queries = gui_acceptance._exercise_queries

    def observe_query_workflow(app) -> str:
        # Offline handoff windows have text output and their own acceptance
        # cases; observe only this test's current-map list/near/again workflow.
        with monkeypatch.context() as query_scope:
            query_scope.setattr(_PackQueryWindow, "destroy", observe_destroy)
            return original_exercise_queries(app)

    monkeypatch.setattr(gui_acceptance, "_exercise_queries", observe_query_workflow)
    path = (
        Path(__file__).parents[1] / "tests/fixtures/maps/war3net-map-script-builder.w3x"
    )
    pack = tmp_path / "query-acceptance-request"
    pack.mkdir()
    try:
        detail = gui_acceptance.run_gui_acceptance(path, pack_path=pack)
    except RuntimeError:
        print(
            "QUERY-CLOSE-OBSERVATIONS " + json.dumps(observations, ensure_ascii=False)
        )
        raise
    assert "tabs=12" in detail
    assert "query-window=list/invalid-near/again" in detail
    assert len(observations) == len(closed) == 1
    observation = observations[0]
    assert all(
        owner in observation["owned_before_close"].values()
        for owner in observation["textbox_owners"]
    )
    assert observation["owned_after_close"] == []
    assert observation["external_preserved"]
    assert sorted(observation["external_fired"]) == ["parent", "sibling"]
    assert observation["generation_after_close"] > observation["query_generation"]
    assert observation["final_query"]["command"] == "list"
    assert observation["final_query"]["exit_code"] == 0
    for window in closed:
        original_destroy(window)  # Closing again after the parent is gone is harmless.
