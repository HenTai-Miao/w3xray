"""Real Tk widget callbacks with synthetic reports only, and offline file APIs."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
import tkinter as tk
from types import SimpleNamespace
from typing import Any

import customtkinter as ctk
import pytest

from gametool import gui_live_probe
from gametool.gui_live_probe import LiveProbeWindow
from gametool.live_report_json import format_report_json


@pytest.fixture
def window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[LiveProbeWindow]:
    monkeypatch.setattr(LiveProbeWindow, "_start", lambda self: None)
    root = ctk.CTk()
    root.withdraw()
    win = LiveProbeWindow(root, str(tmp_path))
    root.update_idletasks()
    root.update()
    try:
        yield win
    finally:
        win.destroy()
        try:
            root.destroy()
        except tk.TclError:
            pass


def _report() -> dict[str, Any]:
    return {
        "pid": 41,
        "process_identity": {"pid": 41, "exe_path": "synthetic-war3.exe"},
        "captured_at": "2026-10-27T00:00:00Z",
        "selected_units": [
            {
                "unit": f"单位{i}",
                "code": "hfoo",
                "addr": 4096 + i,
                "owner": i % 12,
                "x": i + 0.5,
                "y": -i,
                "items": [
                    {"slot": 0, "name": "测试物品", "code": "I001", "addr": 8192 + i}
                ],
            }
            for i in range(91)
        ],
        "selection_complete": True,
        "selection_diagnostics": [],
        "notes": ["synthetic only"],
    }


def _deliver(win: LiveProbeWindow, report: Mapping[str, object], code: int = 0) -> None:
    win._finish(str(code) + "\0" + "摘要\n" + format_report_json(report))


def test_selected_list_buttons_and_coordinates_are_instance_specific(
    window: LiveProbeWindow,
) -> None:
    sent: list[str] = []
    window._query_callback = sent.append
    _deliver(window, _report())
    assert window._unit_list.size() == 91
    window._unit_list.selection_clear(0, "end")
    window._unit_list.selection_set(90)
    window._unit_list.event_generate("<<ListboxSelect>>", when="now")
    window.update()
    current = window._current_unit()
    assert current is not None and current["addr"] == 4186
    assert "单位90" in window._detail_output.get("1.0", "end")
    window._unit_detail_button.invoke()
    window._unit_drop_button.invoke()
    window._unit_near_buttons[1].invoke()
    window._item_buttons[0].invoke()
    window._item_buttons[1].invoke()
    window._item_buttons[2].invoke()
    assert sent == [
        'units id:="hfoo"',
        'drop id:="hfoo"',
        "near 90.5 -90 100",
        'item id:="I001"',
        'where id:="I001"',
        'drop id:="I001"',
    ]
    assert "synthetic only" in window._detail_output.get("1.0", "end")
    assert '"selected_units"' in window._output.get("1.0", "end")


def test_refresh_preserves_choice_then_authoritative_empty_clears_all_actions(
    window: LiveProbeWindow,
) -> None:
    window._query_callback = lambda _query: None
    report = _report()
    _deliver(window, report)
    window._unit_list.selection_clear(0, "end")
    window._unit_list.selection_set(88)
    window._choose_unit()
    _deliver(
        window, {**report, "selected_units": list(reversed(report["selected_units"]))}
    )
    current = window._current_unit()
    assert current is not None and current["addr"] == 4184
    _deliver(
        window, {**report, "selected_units": [], "selected_unit": {"code": "hfoo"}}
    )
    assert window._unit_list.size() == 0
    assert window._item_list.size() == 0
    assert window._current_unit() is None
    assert window._unit_detail_button.cget("state") == "disabled"
    assert all(button.cget("state") == "disabled" for button in window._item_buttons)
    assert "没有选中" in window._selection_status.cget("text")


def test_failed_partial_report_remains_inspectable_and_malformed_tail_is_disabled(
    window: LiveProbeWindow,
) -> None:
    partial = {
        **_report(),
        "selection_complete": False,
        "selection_diagnostics": ["unreadable selection successor"],
    }
    _deliver(window, partial, 2)
    assert window._unit_list.size() == 91
    assert "不完整" in window._selection_status.cget("text")
    assert "unreadable selection successor" in window._detail_output.get("1.0", "end")
    assert window._save_report_button.cget("state") == "normal"
    window._finish('0\0{"selected_units": [\n{"code":"hfoo"}\n')
    assert window._report is None
    assert window._save_report_button.cget("state") == "disabled"
    assert window._tabs.get() == "完整输出"


def test_save_open_compare_buttons_use_offline_apis_without_a_probe(
    window: LiveProbeWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from gametool.live_report import read_live_report

    path = tmp_path / "snapshot.json"
    _deliver(window, _report())
    monkeypatch.setattr(
        gui_live_probe.filedialog, "asksaveasfilename", lambda **_kwargs: str(path)
    )
    window._save_report_button.invoke()
    saved = read_live_report(path)
    assert len(saved["selected_units"]) == 91
    # Saved reports cannot be silently overwritten by the GUI.
    original = path.read_bytes()
    window._save_report_button.invoke()
    assert path.read_bytes() == original
    assert "保存失败" in window._copy_hint.cget("text")
    monkeypatch.setattr(
        gui_live_probe.filedialog, "askopenfilename", lambda **_kwargs: str(path)
    )
    monkeypatch.setattr(
        gui_live_probe,
        "LiveProbeChild",
        lambda *_args, **_kwargs: pytest.fail("offline operations must never probe"),
    )
    window._open_structured_report()
    assert "离线报告" in window._report_label.cget("text")
    assert window._probe_start_id is None
    assert window._probe_poll_id is None
    window._compare_report_button.invoke()
    assert window._tabs.get() == "离线比较"
    assert str(path) in window._comparison_output.get("1.0", "end")
    assert "比较失败" not in window._copy_hint.cget("text")


def test_search_sections_and_reference_button_use_real_widget_contract(
    window: LiveProbeWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from gametool import gui_reference_catalog

    calls = []
    monkeypatch.setattr(
        gui_reference_catalog,
        "open_reference_catalog_dialog",
        lambda parent, pack_dir=None: calls.append((parent, pack_dir)),
    )
    window._reference_button.invoke()
    assert calls == [(window, str(tmp_path))]
    _deliver(window, _report())
    assert "【单位字段证据】" in window._section_positions
    window._jump_section("【完整背包】")
    assert window._detail_output.tag_ranges("sel")
    window._find_state["start"] = "9999.0"
    window._tabs.set("完整输出")
    window._reset_search()
    assert window._find_state["start"] == "1.0"
    assert "完整 JSON" in window._section_positions


def test_closed_window_rejects_late_delivery(window: LiveProbeWindow) -> None:
    window.destroy()
    window._finish("0\0" + format_report_json(_report()))
    assert window._probe_closed


def test_selected_item_callback_uses_the_chosen_slot_and_full_evidence(
    window: LiveProbeWindow,
) -> None:
    sent: list[str] = []
    window._query_callback = sent.append
    report = _report()
    report["selected_units"][0]["items"].append(
        {
            "slot": 5,
            "name": "另一物品",
            "code": "I002",
            "addr": 9900,
            "evidence": [
                {
                    "key": "charges",
                    "value": None,
                    "value_type": "u32",
                    "state": "unknown",
                    "source": "synthetic unsupported layout",
                    "address": None,
                    "diagnostics": ["charge offset not available"],
                }
            ],
        }
    )
    _deliver(window, report)
    window._item_list.selection_clear(0, "end")
    window._item_list.selection_set(1)
    window._item_list.event_generate("<<ListboxSelect>>", when="now")
    window.update()
    window._item_buttons[1].invoke()
    assert sent == ['where id:="I002"']
    text = window._detail_output.get("1.0", "end")
    assert "另一物品" in text and "charge offset not available" in text
    assert "unknown" in text and "synthetic unsupported layout" in text


def test_open_picker_cancels_before_nested_event_loop_even_if_cancelled(
    window: LiveProbeWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed = []

    def picker(**_kwargs):
        observed.append(
            (window._probe_start_id, window._probe_poll_id, window._probe_child)
        )
        return ""

    monkeypatch.setattr(gui_live_probe.filedialog, "askopenfilename", picker)
    window._open_report_button.invoke()
    assert observed == [(None, None, None)]


def test_close_saves_edited_and_explicitly_cleared_inputs_in_private_memo(
    window: LiveProbeWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool import gui_pack_query

    memo = tmp_path / "private-memo"
    monkeypatch.setattr(gui_pack_query, "_memo_dir", lambda: str(memo))
    window._map_entry.delete(0, "end")
    window._map_entry.insert(0, "synthetic map.w3x")
    window._unit_entry.delete(0, "end")
    window.destroy()
    assert (memo / "live-probe-map.txt").read_text(
        encoding="utf-8"
    ) == "synthetic map.w3x"
    assert (memo / "live-probe-unit.txt").read_text(encoding="utf-8") == ""


def test_unavailable_memo_directory_is_fail_open_without_relative_file_fallback(
    window: LiveProbeWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool import gui_pack_query

    monkeypatch.setattr(gui_pack_query, "_memo_dir", lambda: "")
    window._save_last_map_path("synthetic.w3x")
    window._save_last_unit_query("hfoo")
    assert window._load_last_map_path() == ""
    assert window._load_last_unit_query() == ""


def test_reopen_restores_session_report_and_choice_with_historical_label(
    window: LiveProbeWindow, tmp_path: Path
) -> None:
    _deliver(window, _report())
    window._unit_list.selection_clear(0, "end")
    window._unit_list.selection_set(80)
    window._choose_unit()
    window._tabs.set("完整输出")
    parent = window.master
    window.destroy()
    reopened = LiveProbeWindow(parent, str(tmp_path))
    try:
        selected = reopened._current_unit()
        assert selected is not None and selected["addr"] == 4176
        assert "上次会话快照" in reopened._report_label.cget("text")
        assert reopened._tabs.get() == "完整输出"
        assert "synthetic only" in reopened._output.get("1.0", "end")
    finally:
        reopened.destroy()


@pytest.mark.parametrize("identity_mismatch", (False, True))
def test_compare_tab_keeps_full_unknown_and_identity_diagnostics(
    window: LiveProbeWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    identity_mismatch: bool,
) -> None:
    from gametool.live_report import (
        compare_live_reports,
        format_live_report_diff,
        read_live_report,
        write_live_report,
    )

    old = _report()
    old["selection_complete"] = False
    old["selection_diagnostics"] = ["missing end of selected chain"]
    new = _report()
    if identity_mismatch:
        new["process_identity"] = {"pid": 99, "exe_path": "different.exe"}
        new["pid"] = 99
    else:
        new["selected_units"] = []
        new["selection_complete"] = False
        new["selection_diagnostics"] = ["unknown layout"]
    path = tmp_path / "partial-old.json"
    write_live_report(path, old)
    _deliver(window, new)
    monkeypatch.setattr(
        gui_live_probe.filedialog, "askopenfilename", lambda **_kwargs: str(path)
    )
    window._compare_report_button.invoke()
    assert window._report is not None
    result = compare_live_reports(read_live_report(path), window._report)
    assert result["comparison_complete"] is False
    full_text = format_live_report_diff(result)
    assert full_text in window._comparison_output.get("1.0", "end")
    assert window._tabs.get() == "离线比较"


def test_explicit_offline_mode_schedules_no_probe_and_default_live_still_starts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    starts = []
    monkeypatch.setattr(LiveProbeWindow, "_start", lambda self: starts.append(self))
    root = ctk.CTk()
    root.withdraw()
    live = LiveProbeWindow(root, str(tmp_path / "live"))
    offline = LiveProbeWindow(root, str(tmp_path / "offline"), auto_start=False)
    try:
        assert live._probe_start_id is not None
        assert offline._probe_start_id is None
        assert "离线模式" in offline._copy_hint.cget("text")
        # Drive the registered startup timer directly. Nested application-level
        # mainloops would make this callback contract depend on other Tk roots.
        if not starts:
            timer = root.tk.call("after", "info", live._probe_start_id)
            root.tk.call(timer[0])
        assert starts == [live]
        offline._probe_button.invoke()
        assert starts == [live, offline]
    finally:
        offline.destroy()
        live.destroy()
        root.destroy()


def test_public_dialog_forwards_explicit_offline_keyword_without_breaking_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    monkeypatch.setattr(
        gui_live_probe,
        "LiveProbeWindow",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    master = object()
    gui_live_probe.open_live_probe_dialog(master)
    gui_live_probe.open_live_probe_dialog(master, "synthetic-pack", auto_start=False)
    assert calls[0] == (
        (master, None),
        {"query_callback": None, "pack_dir_provider": None, "auto_start": True},
    )
    assert calls[1] == (
        (master, "synthetic-pack"),
        {"query_callback": None, "pack_dir_provider": None, "auto_start": False},
    )


def test_offline_open_invalidates_completed_but_undelivered_child_before_picker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from gametool.gui_live_subprocess import LiveProbeResult
    from gametool.live_report import write_live_report

    report = _report()
    report["notes"] = ["saved offline report"]
    path = tmp_path / "offline.json"
    write_live_report(path, report)
    cancelled = []
    child = SimpleNamespace(
        run=lambda: LiveProbeResult(
            0, format_report_json({**report, "notes": ["stale child result"]}), ""
        ),
        cancel=lambda: cancelled.append(True),
    )
    monkeypatch.setattr(
        gui_live_probe, "LiveProbeChild", lambda *_args, **_kwargs: child
    )
    monkeypatch.setattr(
        gui_live_probe.threading,
        "Thread",
        lambda *, target, daemon: SimpleNamespace(start=target),
    )
    root = ctk.CTk()
    root.withdraw()
    win = LiveProbeWindow(root, str(tmp_path), auto_start=False)
    callbacks = []
    original_after = win.after

    def capture_after(delay, callback):
        callbacks.append(callback)
        return original_after(delay, callback)

    monkeypatch.setattr(win, "after", capture_after)
    try:
        win._start()
        assert win._probe_child is child
        stale_poll = callbacks[-1]

        def picker(**_kwargs):
            assert cancelled == [True]
            assert win._probe_child is None
            assert win._probe_poll_id is None
            stale_poll()
            return str(path)

        monkeypatch.setattr(gui_live_probe.filedialog, "askopenfilename", picker)
        win._open_report_button.invoke()
        stale_poll()
        assert win._report is not None
        assert win._report["notes"] == ["saved offline report"]
        assert "离线报告" in win._report_label.cget("text")
        assert "stale child result" not in win._output.get("1.0", "end")
    finally:
        win.destroy()
        root.destroy()
