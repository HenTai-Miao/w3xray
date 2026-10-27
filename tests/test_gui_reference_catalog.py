"""Real Tk reference interactions with synthetic data and isolated caches."""

from __future__ import annotations

from dataclasses import replace
import json
import threading
import time
import tkinter as tk

import pytest

from gametool import gui_reference_catalog as gui
from gametool.reference_models import (
    ReferenceCatalog,
    ReferenceRecord,
    ReferenceSource,
    ReferenceValue,
)


def _catalog(count: int = 1) -> ReferenceCatalog:
    source = ReferenceSource(
        "synthetic", "/synthetic/definition.tsv", "a" * 64, "synthetic fixture"
    )
    records = tuple(
        ReferenceRecord(
            "objects",
            f"{index:04}",
            f"单位 {index}",
            category="单位",
            sources=(source.id,),
            values=(ReferenceValue("uhpm", "生命上限", str(index), source=source.id),),
        )
        for index in range(count)
    )
    return ReferenceCatalog(records, (source,))


@pytest.fixture
def root(monkeypatch):
    parent = tk.Tk()
    parent.withdraw()
    monkeypatch.setattr(gui, "_SESSION", {})
    yield parent
    parent.destroy()


def _pump(parent, condition, *, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        parent.update()
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("synthetic reference GUI did not reach expected state")


def test_complete_list_worker_main_thread_delivery_and_dialog_keys(root, monkeypatch):
    catalog = _catalog(137)
    load_threads = []
    finish_threads = []

    def load(_pack, *, profile_json=None):
        load_threads.append(threading.get_ident())
        return catalog

    monkeypatch.setattr(gui, "load_reference_catalog", load)
    finish = gui.ReferenceCatalogWindow._finish

    def finished(window, result):
        finish_threads.append(threading.get_ident())
        finish(window, result)

    monkeypatch.setattr(gui.ReferenceCatalogWindow, "_finish", finished)
    window = gui.ReferenceCatalogWindow(root)
    _pump(
        root,
        lambda: (
            window._list.size() == len(catalog.records) and bool(window._detail_content)
        ),
    )
    assert load_threads and all(
        value != threading.get_ident() for value in load_threads
    )
    assert finish_threads == [threading.get_ident()]
    for sequence in (
        "<Escape>",
        "<Control-f>",
        "<Control-F>",
        "<Control-a>",
        "<Control-A>",
        "<Control-r>",
        "<Control-R>",
    ):
        assert window.bind(sequence)
    window._list.selection_clear(0, "end")
    window._list.selection_set(136)
    window._show_selected()
    _pump(root, lambda: "[0136]" in window._output.get("1.0", "end"))
    assert "SHA-256: " + "a" * 64 in window._detail_content
    window._jump("来源")
    assert window._active_section == "来源"
    window._select_all()
    assert window._output.tag_ranges("sel")
    window.destroy()


def test_detail_delivery_chunks_all_characters_and_resets_search(root, monkeypatch):
    monkeypatch.setattr(
        gui, "load_reference_catalog", lambda _pack, **_kwargs: _catalog()
    )
    window = gui.ReferenceCatalogWindow(root)
    _pump(root, lambda: bool(window._detail_content))
    text = "== 详情 ==\n" + "全文证据\r\n" * 30000 + "终点完整\n== 来源 ==\nsource"
    window._set_output(text)
    assert len(window._output.get("1.0", "end-1c")) < len(text)
    assert window._detail_content == text  # Copy-all already owns the whole detail.
    _pump(root, lambda: window._render_id is None)
    assert window._output.get("1.0", "end-1c") == text
    window._find_entry.insert(0, "终点完整")
    window._find_next()
    first = window._output.tag_ranges("reference-hit")
    assert first
    window._find_next()
    assert window._output.tag_ranges("reference-hit") == first
    window._set_output("== 详情 ==\n终点完整\nnew evidence")
    assert window._find_pos == "1.0"
    assert not window._output.tag_ranges("reference-hit")
    window._find_next()
    assert window._output.tag_ranges("reference-hit")
    window.destroy()


def test_cancel_and_close_reject_late_worker_result(root, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    catalog = _catalog()

    def load(_pack, **_kwargs):
        entered.set()
        assert release.wait(10)
        return catalog

    monkeypatch.setattr(gui, "load_reference_catalog", load)
    window = gui.ReferenceCatalogWindow(root)
    _pump(root, entered.is_set)
    window._cancel()
    assert window._result is None
    window.destroy()
    release.set()
    _pump(root, lambda: not window._gui_workers._workers)
    assert window._gui_post_stopped
    assert not window._gui_posts


def test_filter_no_records_recovery_and_profile_picker_propagation(
    root, monkeypatch, tmp_path
):
    calls = []

    def load(pack, *, profile_json=None):
        calls.append((pack, profile_json))
        return _catalog()

    monkeypatch.setattr(gui, "load_reference_catalog", load)
    window = gui.ReferenceCatalogWindow(root, tmp_path / "synthetic-pack")
    _pump(root, lambda: window._result is not None)
    window._query_entry.insert(0, "not-in-fixture")
    window._profile_entry.insert(0, str(tmp_path / "synthetic.json"))
    window._run()
    _pump(
        root,
        lambda: window._result is not None and window._result.query == "not-in-fixture",
    )
    assert window._list.size() == 0
    assert "清空关键词" in window._output.get("1.0", "end")
    assert calls[-1] == (
        str(tmp_path / "synthetic-pack"),
        str(tmp_path / "synthetic.json"),
    )
    window.destroy()


def test_export_writes_full_filter_result_in_background(root, monkeypatch, tmp_path):
    catalog = _catalog(3)
    catalog = replace(catalog, diagnostics=("synthetic incomplete source diagnostic",))
    monkeypatch.setattr(gui, "load_reference_catalog", lambda _pack, **_kwargs: catalog)
    destination = tmp_path / "reference.json"
    monkeypatch.setattr(
        gui.filedialog, "asksaveasfilename", lambda **_kwargs: str(destination)
    )
    window = gui.ReferenceCatalogWindow(root)
    _pump(root, lambda: window._result is not None)
    window._export()
    _pump(
        root, lambda: destination.is_file() and "已导出" in window._status.cget("text")
    )
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert len(payload["records"]) == 3
    assert payload["diagnostics"] == ["synthetic incomplete source diagnostic"]
    assert payload["omitted"] == 0
    window.destroy()


@pytest.mark.parametrize("terminal", ["empty", "error"])
def test_query_terminal_delivery_rejects_detail_started_from_old_list(
    root, monkeypatch, terminal
):
    catalog = _catalog()
    entered, release = threading.Event(), threading.Event()
    detail_entered, detail_release = threading.Event(), threading.Event()
    state = {"loads": 0, "block_detail": False}
    original_detail = gui._detail_text

    def load(_pack, **_kwargs):
        state["loads"] += 1
        if state["loads"] > 1:
            entered.set()
            assert release.wait(30)
            if terminal == "error":
                raise ValueError("synthetic refreshed query failed")
        return catalog

    def detail(result, selected):
        if state["block_detail"]:
            detail_entered.set()
            assert detail_release.wait(30)
        return original_detail(result, selected)

    monkeypatch.setattr(gui, "load_reference_catalog", load)
    monkeypatch.setattr(gui, "_detail_text", detail)
    window = gui.ReferenceCatalogWindow(root)
    try:
        _pump(root, lambda: bool(window._detail_content))
        window._query_entry.insert(0, "no-such-synthetic-object")
        window._run()
        _pump(root, entered.is_set)
        state["block_detail"] = True
        window._show_selected()
        _pump(root, detail_entered.is_set)
        release.set()
        _pump(root, lambda: not window._busy)
        marker = (
            "未找到符合筛选的记录"
            if terminal == "empty"
            else "synthetic refreshed query failed"
        )
        assert marker in window._detail_content
        detail_release.set()
        _pump(root, lambda: not window._gui_workers._workers)
        root.update()
        assert marker in window._detail_content
        assert "单位 0" not in window._detail_content
        if terminal == "empty":
            assert window._list.size() == 0
    finally:
        release.set()
        detail_release.set()
        window.destroy()
