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
    ReferenceMapScope,
    ReferenceRecord,
    ReferenceSource,
    ReferenceValue,
)
from tests.gui_base import GuiTestCase, _get_app


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
def root(monkeypatch, tmp_path):
    # Reuse the suite's Tcl interpreter, including CTk's cached images and
    # appearance/scaling timers. Only this fixture's new windows are retired.
    from gametool.gui_offline_acceptance import _capture_callbacks

    parent = _get_app()
    baseline = GuiTestCase()
    baseline.app = parent
    baseline.setUp()
    previous = set(parent.winfo_children())
    previous_state = parent.state()
    parent.withdraw()
    monkeypatch.setattr(gui, "_SESSION", {})
    monkeypatch.setattr(gui, "_selection_memory", None)
    monkeypatch.setattr(
        gui, "gamexray_cache_root", lambda: tmp_path / "reference-cache"
    )
    with _capture_callbacks(parent) as errors:
        try:
            yield parent
        finally:
            for child in parent.winfo_children():
                if child not in previous and isinstance(child, tk.Toplevel):
                    child.destroy()
            parent.update()
            parent.state(previous_state)
            assert errors == []


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

    def load(_pack, *, profile_json=None, **_kwargs):
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

    def load(pack, *, profile_json=None, **_kwargs):
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


@pytest.mark.parametrize("export_terminal", ("success", "error"))
@pytest.mark.parametrize("query_phase", ("loading", "finished"))
def test_new_query_rejects_old_export_worker_and_completion(
    root, monkeypatch, tmp_path, export_terminal, query_phase
):
    catalog = _catalog(2)
    query_entered, query_release = threading.Event(), threading.Event()
    export_entered, export_release = threading.Event(), threading.Event()
    loads = []
    exported_results = []
    export_threads = []
    completions = []
    dialogs = []
    original_write = gui.write_reference_export

    def load(_pack, **_kwargs):
        loads.append(threading.get_ident())
        if len(loads) > 1:
            query_entered.set()
            assert query_release.wait(30), "new query was not released"
        return catalog

    def write(path, result):
        exported_results.append(result)
        export_threads.append(threading.get_ident())
        export_entered.set()
        assert export_release.wait(30), "old export was not released"
        if export_terminal == "error":
            raise OSError("old synthetic export failure")
        original_write(path, result)

    monkeypatch.setattr(gui, "load_reference_catalog", load)
    monkeypatch.setattr(gui, "write_reference_export", write)
    monkeypatch.setattr(
        gui.messagebox,
        "showerror",
        lambda *args, **kwargs: dialogs.append((args, kwargs)),
    )
    destination = tmp_path / "old-query.json"
    monkeypatch.setattr(
        gui.filedialog, "asksaveasfilename", lambda **_kwargs: str(destination)
    )
    window = gui.ReferenceCatalogWindow(root)
    original_post = window._post_gui_worker

    def observe_post(ticket, callback, **kwargs):
        if ticket.group == "reference-export":
            # Retain the actual success/error closure. Replaying it through Tk
            # also covers a completion already handed off before cancellation.
            completions.append(callback)
        return original_post(ticket, callback, **kwargs)

    monkeypatch.setattr(window, "_post_gui_worker", observe_post)
    try:
        _pump(root, lambda: window._result is not None and bool(window._detail_content))
        old_result = window._result
        window._export_button.invoke()
        _pump(root, export_entered.is_set)
        export_ticket = next(
            worker.ticket
            for worker in window._gui_workers._workers.values()
            if worker.ticket.group == "reference-export"
        )
        assert exported_results == [old_result]
        assert export_threads != [threading.get_ident()]
        window._query_entry.insert(0, "单位 1")
        window._run_button.invoke()
        _pump(root, query_entered.is_set)
        assert export_ticket.cancellation.is_set()
        assert window._busy
        assert window._result is old_result
        assert window._export_button.cget("state") == "disabled"

        if query_phase == "finished":
            query_release.set()
            _pump(
                root,
                lambda: (
                    not window._busy
                    and window._result is not old_result
                    and "[0001]" in window._detail_content
                ),
            )
            assert window._result is not None
            assert window._result.query == "单位 1"
            assert window._list.size() == 1
        expected_status = window._status.cget("text")
        expected_detail = window._detail_content
        expected_export_state = window._export_button.cget("state")
        export_release.set()
        _pump(
            root,
            lambda: (
                bool(completions)
                and not any(
                    worker.ticket.group == "reference-export"
                    for worker in window._gui_workers._workers.values()
                )
            ),
        )
        assert window._status.cget("text") == expected_status
        assert window._export_button.cget("state") == expected_export_state
        assert dialogs == []
        root.after_idle(completions[0])
        root.update()
        assert window._status.cget("text") == expected_status
        assert window._export_button.cget("state") == expected_export_state
        assert window._detail_content == expected_detail
        assert dialogs == []
        if export_terminal == "success":
            payload = json.loads(destination.read_text(encoding="utf-8"))
            assert [record["id"] for record in payload["records"]] == ["0000", "0001"]
            assert payload["query"] == ""
        else:
            assert not destination.exists()
        query_release.set()
        _pump(root, lambda: not window._busy)
        assert window._result is not None
        assert window._result.query == "单位 1"
        assert window._export_button.cget("state") == "normal"
    finally:
        query_release.set()
        export_release.set()
        _pump(root, lambda: not window._gui_workers._workers)
        window.destroy()


def _map_catalog(path, *, complete=True):
    source = ReferenceSource(
        str(path),
        str(path),
        "b" * 64,
        "地图完整字节",
        member_path="Maps\\Chapter1.w3x!war3map.w3t",
        container_sha256="c" * 64,
    )
    note = () if complete else ("章节尾部对象数据未读取完整",)
    scope = ReferenceMapScope(
        str(path),
        str(path),
        "Maps\\Chapter1.w3x",
        "章节一",
        "b" * 64,
        (("物品", 1), ("单位", 0)),
        diagnostics=note,
        complete=complete,
    )
    record = replace(
        _catalog().records[0], category="物品", scope=scope.scope, sources=(source.id,)
    )
    return ReferenceCatalog(
        (record,),
        (source,),
        note,
        map_path=str(path),
        map_scopes=(scope,),
        source_counts=((scope.scope, 1),),
        input_files=(str(path),),
    )


def test_map_pack_picker_mutual_exclusion_clear_and_memory(root, monkeypatch, tmp_path):
    map_path, pack = tmp_path / "地图.w3n", tmp_path / "知识包"
    calls = []

    def load(pack_dir, *, map_path=None, profile_json=None, id_tables=(), **kwargs):
        calls.append((pack_dir, map_path, profile_json, id_tables))
        assert callable(kwargs["cancelled"]) and callable(kwargs["progress"])
        kwargs["progress"]("正在读取完整地图对象")
        return _map_catalog(map_path) if map_path else _catalog()

    monkeypatch.setattr(gui, "load_reference_catalog", load)
    window = gui.ReferenceCatalogWindow(root, id_tables=(str(tmp_path / "ID.txt"),))
    _pump(root, lambda: window._result is not None and not window._busy)
    window._profile_entry.insert(0, str(tmp_path / "profile.json"))
    monkeypatch.setattr(
        gui.filedialog, "askopenfilename", lambda **_kwargs: str(map_path)
    )
    window._map_button.invoke()
    _pump(
        root,
        lambda: (
            not window._busy
            and window._result is not None
            and window._result.map_path == str(map_path)
        ),
    )
    assert window._pack_entry.get() == ""
    assert calls[-1] == (
        None,
        str(map_path),
        str(tmp_path / "profile.json"),
        (str(tmp_path / "ID.txt"),),
    )
    assert gui._load_reference_memory() == {
        "map_path": str(map_path),
        "pack_dir": "",
        "profile_json": str(tmp_path / "profile.json"),
    }
    assert map_path.name in window.title()
    monkeypatch.setattr(gui.filedialog, "askdirectory", lambda **_kwargs: str(pack))
    window._pack_button.invoke()
    _pump(root, lambda: not window._busy and calls[-1][0] == str(pack))
    assert window._map_entry.get() == ""
    assert gui._load_reference_memory()["map_path"] == ""
    window._clear_source_button.invoke()
    _pump(root, lambda: not window._busy and calls[-1][:2] == (None, None))
    assert window._pack_entry.get() == window._map_entry.get() == ""
    assert window._id_tables == (str(tmp_path / "ID.txt"),)
    assert window._profile_entry.get() == str(tmp_path / "profile.json")
    window.destroy()


@pytest.mark.parametrize("source", ("map", "pack", "empty"))
def test_explicit_source_overrides_remembered_map_and_pack(
    root, monkeypatch, tmp_path, source
):
    calls = []
    gui._save_reference_memory(
        str(tmp_path / "old-pack"), "", str(tmp_path / "old.w3x")
    )

    def load(pack, *, map_path=None, **_kwargs):
        calls.append((pack, map_path))
        return _map_catalog(map_path) if map_path else _catalog()

    monkeypatch.setattr(gui, "load_reference_catalog", load)
    window = gui.ReferenceCatalogWindow(
        root,
        pack_dir=tmp_path / "new-pack"
        if source == "pack"
        else ""
        if source == "empty"
        else None,
        map_path=tmp_path / "new.w3x" if source == "map" else None,
    )
    _pump(root, lambda: not window._busy and window._result is not None)
    assert calls == [
        (None, str(tmp_path / "new.w3x"))
        if source == "map"
        else (str(tmp_path / "new-pack"), None)
        if source == "pack"
        else (None, None)
    ]
    window.destroy()


def test_map_partial_overview_retains_all_scopes_counts_and_member_sources(
    root, monkeypatch, tmp_path
):
    catalog = _map_catalog(tmp_path / "partial.w3n", complete=False)
    empty_scope = ReferenceMapScope(
        "missing-chapter",
        str(tmp_path / "partial.w3n"),
        "Maps\\Missing.w3x",
        "空/失败章节",
        "",
        (("物品", 0), ("单位", 0)),
        diagnostics=("缺失章节原始诊断",),
        complete=False,
    )
    catalog = replace(catalog, map_scopes=(*catalog.map_scopes, empty_scope))
    monkeypatch.setattr(gui, "load_reference_catalog", lambda _pack, **_kwargs: catalog)
    window = gui.ReferenceCatalogWindow(root, map_path=tmp_path / "partial.w3n")
    _pump(root, lambda: bool(window._detail_content))
    assert "来源不完整" in window._status.cget("text")
    assert "来源读取完整" not in window._status.cget("text")
    assert "Maps\\Chapter1.w3x!war3map.w3t" in window._detail_content
    assert "容器 SHA-256: " + "c" * 64 in window._detail_content
    window._overview_button.invoke()
    _pump(root, lambda: "missing-chapter" in window._detail_content)
    text = window._detail_content
    for marker in (
        "章节一",
        "物品 1",
        "单位 0",
        "Maps\\Missing.w3x",
        "缺失章节原始诊断",
        "章节尾部对象数据未读取完整",
    ):
        assert marker in text
    assert "来源读取: 不完整" in text
    window._query_entry.insert(0, "never-matches")
    window._run_button.invoke()
    _pump(
        root,
        lambda: (
            not window._busy
            and window._result is not None
            and window._result.query == "never-matches"
        ),
    )
    assert window._list.size() == 0
    assert "缺失章节原始诊断" in window._detail_content
    assert "清空关键词" in window._detail_content
    window.destroy()


def test_map_cancel_reenable_inputs_and_reject_old_progress_and_result(
    root, monkeypatch, tmp_path
):
    entered, release = threading.Event(), threading.Event()
    first_path, second_path = tmp_path / "first.w3x", tmp_path / "second.w3x"
    callbacks = []
    cancelled = []
    posts = []

    def load(_pack, *, map_path=None, cancelled=None, progress=None, **_kwargs):
        if map_path == str(first_path):
            callbacks.append(progress)
            assert progress is not None
            progress("第一图读取进度")
            entered.set()
            assert release.wait(20)
            assert cancelled is not None
            assert cancelled()
            progress("不应交付的旧图进度")
        return _map_catalog(map_path)

    monkeypatch.setattr(gui, "load_reference_catalog", load)
    window = gui.ReferenceCatalogWindow(root, map_path=first_path)
    original_post = window._post_gui_worker

    def post(ticket, callback, **kwargs):
        posts.append(callback)
        cancelled.append(ticket.cancellation)
        return original_post(ticket, callback, **kwargs)

    monkeypatch.setattr(window, "_post_gui_worker", post)
    try:
        _pump(root, entered.is_set)
        assert all(
            control.cget("state") == "disabled"
            for control in (
                *window._source_controls,
                *window._id_controls,
                *window._input_controls,
            )
        )
        window._clear_source()
        assert window._map_entry.get() == str(first_path)
        window._cancel()
        assert all(
            control.cget("state") == "normal"
            for control in (
                *window._source_controls,
                *window._id_controls,
                *window._input_controls,
            )
        )
        monkeypatch.setattr(
            gui.filedialog, "askopenfilename", lambda **_kwargs: str(second_path)
        )
        window._map_button.invoke()
        _pump(root, lambda: not window._busy and window._result is not None)
        assert window._result is not None
        assert window._result.map_path == str(second_path)
        status = window._status.cget("text")
        callbacks[0]("取消后的旧图进度")
        release.set()
        _pump(root, lambda: not window._gui_workers._workers)
        for callback in posts:
            root.after_idle(callback)
        root.update()
        assert window._result.map_path == str(second_path)
        assert window._status.cget("text") == status
        assert cancelled[0].is_set()
    finally:
        release.set()
        window.destroy()


@pytest.mark.parametrize("change", ("source", "filter", "cancel", "close"))
def test_export_completion_cannot_claim_success_after_source_filter_cancel_or_close(
    root, monkeypatch, tmp_path, change
):
    entered, release = threading.Event(), threading.Event()
    completions = []
    dialogs = []
    monkeypatch.setattr(
        gui, "load_reference_catalog", lambda _pack, **_kwargs: _catalog()
    )
    monkeypatch.setattr(
        gui.filedialog,
        "asksaveasfilename",
        lambda **_kwargs: str(tmp_path / "out.json"),
    )
    monkeypatch.setattr(
        gui.messagebox, "showerror", lambda *args, **kwargs: dialogs.append(args)
    )

    def write(_path, _result):
        entered.set()
        assert release.wait(20)

    monkeypatch.setattr(gui, "write_reference_export", write)
    window = gui.ReferenceCatalogWindow(root)
    original_post = window._post_gui_worker

    def post(ticket, callback, **kwargs):
        if ticket.group == "reference-export":
            completions.append(callback)
        return original_post(ticket, callback, **kwargs)

    monkeypatch.setattr(window, "_post_gui_worker", post)
    try:
        _pump(root, lambda: window._result is not None)
        window._export_button.invoke()
        _pump(root, entered.is_set)
        if change == "source":
            window._map_var.set(str(tmp_path / "changed.w3x"))
        elif change == "filter":
            window._query_entry.insert(0, "changed-filter")
        elif change == "cancel":
            window._cancel()
        else:
            window.destroy()
        release.set()
        _pump(root, lambda: bool(completions) and not window._gui_workers._workers)
        for callback in completions:
            root.after_idle(callback)
        root.update()
        assert not dialogs
        if not window._closed:
            assert "已导出" not in window._status.cget("text")
    finally:
        release.set()
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


def test_multiple_record_selection_copy_clear_and_session_restore(root, monkeypatch):
    catalog = _catalog(3)
    catalog = replace(
        catalog,
        records=tuple(
            replace(
                record,
                id="Same",
                scope=f"independent-scope-{index}",
                raw_rows=(("原始\t行\r\n", str(index)),),
                diagnostics=(f"完整记录诊断 {index}",),
            )
            for index, record in enumerate(catalog.records)
        ),
        diagnostics=("完整来源诊断",),
    )
    monkeypatch.setattr(gui, "load_reference_catalog", lambda _pack, **_kwargs: catalog)
    copied = []
    copy_threads = []
    window = gui.ReferenceCatalogWindow(root)

    def copy(value):
        copied.append(value)
        copy_threads.append(threading.get_ident())

    monkeypatch.setattr(window, "_copy", copy)
    _pump(root, lambda: bool(window._detail_content))
    assert window._list.cget("selectmode") == "extended"
    for sequence in ("<Control-a>", "<Control-A>", "<Control-c>", "<Control-C>"):
        assert window._list.bind(sequence)
    window._select_records_button.invoke()
    assert window._list.curselection() == (0, 1, 2)
    assert window._selection_count.cget("text") == "已选 3 / 3"
    window._copy_records_button.invoke()
    _pump(root, lambda: bool(copied))
    assert copy_threads == [threading.get_ident()]
    for index in range(3):
        assert f"independent-scope-{index}" in copied[0]
        assert f"完整记录诊断 {index}" in copied[0]
    assert "原始\\t行\\r\\n" in copied[0]
    assert "完整来源诊断" in copied[0]
    window._clear_records_button.invoke()
    assert window._selection_count.cget("text") == "已选 0 / 3"
    assert window._copy_records_button.cget("state") == "disabled"
    assert window._export_selected_button.cget("state") == "disabled"
    window._list.selection_set(0)
    window._list.selection_set(2)
    window._show_selected()
    window.destroy()
    restored = gui.ReferenceCatalogWindow(root)
    _pump(root, lambda: restored._result is not None)
    assert restored._list.curselection() == (0, 2)
    assert restored._selection_count.cget("text") == "已选 2 / 3"
    restored.destroy()


@pytest.mark.parametrize("suffix", (".json", ".md", ".tsv"))
def test_selected_export_uses_exact_selection_and_background_snapshot(
    root, monkeypatch, tmp_path, suffix
):
    catalog = _catalog(3)
    monkeypatch.setattr(gui, "load_reference_catalog", lambda _pack, **_kwargs: catalog)
    destination = tmp_path / f"selected{suffix}"
    monkeypatch.setattr(
        gui.filedialog, "asksaveasfilename", lambda **_kwargs: str(destination)
    )
    write = gui.write_reference_selection
    calls = []

    def write_selected(path, result, indices):
        calls.append((threading.get_ident(), result, indices))
        write(path, result, indices)

    monkeypatch.setattr(gui, "write_reference_selection", write_selected)
    window = gui.ReferenceCatalogWindow(root)
    _pump(root, lambda: window._result is not None)
    window._list.selection_set(2)
    window._show_selected()
    window._export_selected_button.invoke()
    _pump(root, lambda: "已导出选中 2 条" in window._status.cget("text"))
    assert calls[0][0] != threading.get_ident()
    assert calls[0][1] is window._result
    assert calls[0][2] == (0, 2)
    text = destination.read_text(encoding="utf-8")
    if suffix == ".json":
        payload = json.loads(text)
        assert [record["id"] for record in payload["records"]] == ["0000", "0002"]
        assert payload["selection"]["indices"] == [0, 2]
    else:
        assert "0000" in text and "0002" in text and "0001" not in text
    window.destroy()


def test_query_handoff_binds_child_and_never_uses_external_or_current_map(
    root, monkeypatch, tmp_path
):
    pack = tmp_path / "bound-pack"
    child = pack / "子地图" / "chapter"
    child.mkdir(parents=True)
    source_path = str(child / "对象ID" / "技能.tsv")
    source = ReferenceSource(
        source_path, source_path, "a" * 64, "fixture", state="map-evidence"
    )
    record = replace(
        _catalog().records[0],
        category="技能",
        id="A001",
        scope=str(child),
        sources=(source.id,),
        state="map-evidence",
    )
    catalog = ReferenceCatalog(
        (record, replace(record, scope="external-label", state="external-label")),
        (source,),
        input_roots=(str(pack),),
    )
    monkeypatch.setattr(gui, "load_reference_catalog", lambda _pack, **_kwargs: catalog)
    opened = []

    def open_query(_parent, provider, _ensure, **kwargs):
        opened.append((provider(), kwargs))

    monkeypatch.setattr(gui, "open_pack_query_dialog", open_query)
    window = gui.ReferenceCatalogWindow(root, pack_dir=pack)
    _pump(root, lambda: window._result is not None)
    assert window._query_button.cget("state") == "normal"
    window._query_button.invoke()
    assert opened == [(str(child), {"prefill": '="A001"', "prefill_command": "skills"})]
    window._list.selection_clear(0, "end")
    window._list.selection_set(1)
    window._show_selected()
    assert window._query_button.cget("state") == "disabled"
    window._query_selected()
    assert len(opened) == 1
    window._list.selection_set(0)
    window._show_selected()
    assert window._query_button.cget("state") == "disabled"
    window._query_selected()
    assert len(opened) == 1
    window.destroy()


@pytest.mark.parametrize("change", ("selection", "source", "filter", "cancel", "close"))
def test_selected_copy_rejects_stale_snapshot_on_main_thread(
    root, monkeypatch, tmp_path, change
):
    entered, release = threading.Event(), threading.Event()
    copied = []
    completions = []
    format_selection = gui.format_reference_selection
    monkeypatch.setattr(
        gui, "load_reference_catalog", lambda _pack, **_kwargs: _catalog(3)
    )

    def blocked_format(result, selected):
        entered.set()
        assert release.wait(20)
        return format_selection(result, selected)

    monkeypatch.setattr(gui, "format_reference_selection", blocked_format)
    window = gui.ReferenceCatalogWindow(root)
    monkeypatch.setattr(window, "_copy", copied.append)
    original_post = window._post_gui_worker

    def capture_post(ticket, callback, **kwargs):
        if ticket.group == "reference-copy":
            completions.append(callback)
        return original_post(ticket, callback, **kwargs)

    monkeypatch.setattr(window, "_post_gui_worker", capture_post)
    try:
        _pump(root, lambda: window._result is not None)
        window._select_all_records()
        window._copy_records_button.invoke()
        _pump(root, entered.is_set)
        if change == "selection":
            window._clear_record_selection()
        elif change == "source":
            window._map_var.set(str(tmp_path / "different.w3x"))
        elif change == "filter":
            window._query_entry.insert(0, "changed-query")
        elif change == "cancel":
            window._cancel()
        else:
            window.destroy()
        release.set()
        _pump(root, lambda: bool(completions) and not window._gui_workers._workers)
        for callback in completions:
            root.after_idle(callback)
        root.update()
        assert not copied
    finally:
        release.set()
        window.destroy()
