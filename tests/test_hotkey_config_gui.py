"""Exercise worker delivery without creating Tk windows or touching user assets."""

from __future__ import annotations

import threading
import time
import tkinter as tk
from types import SimpleNamespace
from typing import cast

from gametool import gui_hotkey_config
from gametool import gui_tk_callbacks
from gametool.gui_hotkey_config import _HotkeyConfigDialog
from gametool.hotkey_config import inspect_hotkey_config


class _Control:
    def __init__(self, main_thread):
        self.main_thread = main_thread
        self.changes = []

    def configure(self, **values):
        assert threading.get_ident() == self.main_thread
        self.changes.append(values)


class _WorkerHarness:
    def __init__(self):
        self.main_thread = threading.get_ident()
        self._closed = False
        self._busy = False
        self._generation = 0
        self._poll_id = None
        self._result = None
        self._views = {}
        self._result_fresh = False
        self._run_button = _Control(self.main_thread)
        self._export_button = _Control(self.main_thread)
        self._status = _Control(self.main_thread)
        self.callbacks = []
        self.rendered = 0

    def after(self, _delay, callback):
        assert threading.get_ident() == self.main_thread
        self.callbacks.append(callback)
        return f"owned-{len(self.callbacks)}"

    def _render(self):
        assert threading.get_ident() == self.main_thread
        self.rendered += 1

    def drain(self):
        deadline = time.monotonic() + 3
        yield_event = threading.Event()
        while self.callbacks and self._busy and time.monotonic() < deadline:
            self.callbacks.pop(0)()
            yield_event.wait(0.001)


def _result(tmp_path):
    path = tmp_path / "synthetic.json"
    path.write_text(
        '{"language":"auto","active_profile":"One","profiles":{"One":{"bindings":[]}}}',
        encoding="utf-8",
    )
    return inspect_hotkey_config(path)


def _isolated_session(monkeypatch):
    monkeypatch.setattr(gui_hotkey_config, "_session_result", None)
    monkeypatch.setattr(gui_hotkey_config, "_session_views", {})


def test_worker_formats_both_views_off_thread_and_delivers_widgets_on_main(
    tmp_path, monkeypatch
):
    _isolated_session(monkeypatch)
    result = _result(tmp_path)
    original_format = gui_hotkey_config.format_hotkey_result
    main_thread = threading.get_ident()
    worker_threads = []

    def checked_format(value):
        worker_threads.append(threading.get_ident())
        assert threading.get_ident() != main_thread
        return original_format(value)

    monkeypatch.setattr(gui_hotkey_config, "format_hotkey_result", checked_format)
    harness = _WorkerHarness()
    _HotkeyConfigDialog._start_worker(
        cast(_HotkeyConfigDialog, cast(object, harness)),
        lambda: (result, "done"),
        "working",
    )
    harness.drain()
    assert not harness._busy
    assert harness._result is result and harness._result_fresh
    assert harness.rendered == 1
    assert {"检查详情", "完整 JSON"} == harness._views.keys()
    assert worker_threads and all(t != main_thread for t in worker_threads)
    assert harness._export_button.changes[-1] == {"state": "normal"}


def test_worker_generation_change_discards_late_result(tmp_path, monkeypatch):
    _isolated_session(monkeypatch)
    result = _result(tmp_path)
    entered, release = threading.Event(), threading.Event()

    def work():
        entered.set()
        assert release.wait(2)
        return result, "late"

    harness = _WorkerHarness()
    _HotkeyConfigDialog._start_worker(
        cast(_HotkeyConfigDialog, cast(object, harness)), work, "working"
    )
    assert entered.wait(1)
    harness._generation += 1
    release.set()
    harness.drain()
    assert not harness._busy
    assert harness._result is None and not harness._result_fresh
    assert harness.rendered == 0
    assert "丢弃过期" in harness._status.changes[-1]["text"]


def test_closed_dialog_poll_never_touches_widgets(tmp_path, monkeypatch):
    _isolated_session(monkeypatch)
    result = _result(tmp_path)
    entered, release = threading.Event(), threading.Event()

    def work():
        entered.set()
        assert release.wait(2)
        return result, "closed"

    harness = _WorkerHarness()
    _HotkeyConfigDialog._start_worker(
        cast(_HotkeyConfigDialog, cast(object, harness)), work, "working"
    )
    assert entered.wait(1)
    before = [
        list(control.changes)
        for control in (harness._run_button, harness._export_button, harness._status)
    ]
    harness._closed = True
    release.set()
    harness.callbacks.pop(0)()
    after = [
        list(control.changes)
        for control in (harness._run_button, harness._export_button, harness._status)
    ]
    assert before == after and harness.rendered == 0


def test_worker_failure_remains_failed_without_fake_success(monkeypatch):
    _isolated_session(monkeypatch)

    def work():
        raise ValueError("SYNTHETIC_FAILURE")

    harness = _WorkerHarness()
    _HotkeyConfigDialog._start_worker(
        cast(_HotkeyConfigDialog, cast(object, harness)), work, "working"
    )
    harness.drain()
    assert not harness._busy and not harness._result_fresh
    assert harness.rendered == 0
    assert "SYNTHETIC_FAILURE" in harness._status.changes[-1]["text"]


def _unrealized_dialog(monkeypatch):
    """A real Python dialog instance whose base destroy never enters Tcl/Tk."""
    dialog = object.__new__(_HotkeyConfigDialog)
    dialog._closed = False
    dialog._destroy_started = False
    dialog._generation = 0
    dialog._poll_id = "owned-poll"
    calls = []
    monkeypatch.setattr(gui_hotkey_config, "_save_choices", lambda _values: None)
    monkeypatch.setattr(_HotkeyConfigDialog, "_choices", lambda _self: {})

    def cancel_tree(widget):
        assert widget is dialog
        calls.append("cancel-tree")
        return ("owned-poll", "owned-textbox-resize")

    def inherited_destroy(widget):
        assert widget is dialog
        calls.append("base-destroy")
        widget._on_destroy(SimpleNamespace(widget=widget))

    def after_cancel(_widget, identifier):
        calls.append("cancel-poll:" + identifier)
        if "cancel-tree" in calls:
            raise tk.TclError("owned callback already retired")

    monkeypatch.setattr(gui_tk_callbacks, "cancel_widget_callbacks", cancel_tree)
    monkeypatch.setattr(gui_hotkey_config.ctk.CTkToplevel, "destroy", inherited_destroy)
    monkeypatch.setattr(_HotkeyConfigDialog, "after_cancel", after_cancel)
    return dialog, calls


def test_direct_destroy_retires_child_callbacks_before_base_and_is_idempotent(
    monkeypatch,
):
    dialog, calls = _unrealized_dialog(monkeypatch)
    dialog.destroy()
    dialog.destroy()
    assert calls == ["cancel-tree", "base-destroy", "cancel-poll:owned-poll"]
    assert dialog._closed and dialog._poll_id is None


def test_close_keeps_worker_cleanup_and_routes_through_owned_tree_retirement(
    monkeypatch,
):
    dialog, calls = _unrealized_dialog(monkeypatch)
    dialog._close()
    dialog._close()
    assert calls == ["cancel-poll:owned-poll", "cancel-tree", "base-destroy"]
    assert dialog._closed and dialog._poll_id is None
