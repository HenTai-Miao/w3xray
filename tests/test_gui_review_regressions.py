"""Real Tk regressions for reachable controls and source-bound GUI results."""

from __future__ import annotations

from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from gametool.api import GameObject, MapData
from gametool import gui_pack_query as query_gui
from gametool.gui_live_probe import LiveProbeWindow
from gametool.gui_save_workspace import SaveWorkspace
from gametool.gui_shell_object_panel import _pack_query_selected
from gametool.object_filter import filter_objects_by_query
from gametool.object_text_presentation import ObjectTextView
from gametool.save_report_query import select_save_report
from tests.gui_base import GuiTestCase


class GuiReviewRegressionTest(GuiTestCase):
    def test_all_topbar_actions_fit_minimum_and_default_window_widths(self) -> None:
        app = self.app
        geometry = app.geometry()
        original = app.map_label.cget("text")
        original_source = app.game_data_label.cget("text")
        try:
            app.map_label.configure(text="当前地图：" + "完整地图名" * 80)
            app.game_data_label.configure(text="游戏数据：" + "来源目录名" * 80)
            self.show_app()
            for width in (1040, 1440):
                app.geometry(f"{width}x860")
                app.update()
                buttons = [
                    getattr(app, name)
                    for name in (
                        "open_map_button",
                        "current_map_button",
                        "profile_settings_button",
                        "pack_query_button",
                        "live_probe_button",
                        "minimap_button",
                        "guide_button",
                        "data_tools_button",
                    )
                ]
                buttons.extend(getattr(app, "export_buttons").values())
                for button in buttons:
                    left = button.winfo_rootx() - app.winfo_rootx()
                    assert button.winfo_ismapped(), (width, button.cget("text"))
                    assert button.winfo_width() >= button.winfo_reqwidth()
                    assert 0 <= left < left + button.winfo_width() <= app.winfo_width()
        finally:
            app.map_label.configure(text=original)
            app.game_data_label.configure(text=original_source)
            app.geometry(geometry)
            app.withdraw()

    def test_switching_map_clears_selected_identity_and_rows_before_filter_finishes(
        self,
    ) -> None:
        old = GameObject("物品", "w3t", "I001", "ratf", "旧地图物品", True)
        new = GameObject("物品", "w3t", "I002", "ratf", "新地图物品", True)
        first = MapData("first.w3x", "第一张", objects={"物品": [old]})
        second = MapData("second.w3x", "第二张", objects={"物品": [new]})
        self.app.active_object_category = "物品"
        self.app._render_map(first, [], [], None)
        self.pump_events_until(lambda: self.app.col_results["物品"] == [old])
        self.app._show_detail(old)
        release = threading.Event()
        started = threading.Event()

        def delayed(md, query, fine):
            started.set()
            assert release.wait(5)
            return filter_objects_by_query(md, query, fine)

        try:
            with patch(
                "gametool.gui_object_filter_runner.filter_objects_by_query", delayed
            ):
                self.app._render_map(second, [], [], None)
                assert started.wait(2)
                assert self.app._selected_detail_object is None
                assert self.app.object_gallery.active_objects == []
                assert all(not values for values in self.app.col_results.values())
                assert self.app.copy_complete_text_button.cget("state") == "disabled"
                self.app._set_object_text_view(ObjectTextView.ALL.value)
                assert "旧地图物品" not in self.app.detail.get("1.0", "end")
                with patch.object(self.app, "on_pack_query") as query:
                    _pack_query_selected(self.app, "calls")
                    query.assert_not_called()
                release.set()
                self.pump_events_until(lambda: self.app.col_results["物品"] == [new])
            self.app._show_detail(new)
            assert self.app.copy_complete_text_button.cget("state") == "normal"
            assert all(
                button.cget("state") == "normal"
                for button in getattr(self.app, "export_buttons").values()
            )
        finally:
            release.set()

    def test_query_and_offline_probe_shortcuts_do_not_replace_global_bindings(
        self,
    ) -> None:
        sequences = ("<Control-f>", "<Control-F>", "<Control-a>", "<Control-1>")
        original = {key: self.app.bind_all(key) for key in sequences}
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(query_gui._PackQueryWindow, "_run_initial"):
                query = query_gui._PackQueryWindow(self.app, directory)
                probe = LiveProbeWindow(self.app, directory, auto_start=False)
                try:
                    self.app.update()
                    assert {
                        key: self.app.bind_all(key) for key in sequences
                    } == original
                    assert query.bind("<Control-f>")
                    assert probe.bind("<Control-F>")
                finally:
                    probe.destroy()
                    query.destroy()
                self.app.update()
                assert {key: self.app.bind_all(key) for key in sequences} == original

    def test_restored_query_result_is_bound_to_its_pack_and_labeled_as_snapshot(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first_path = str(Path(directory) / "first")
            second_path = str(Path(directory) / "second")
            with (
                patch.multiple(query_gui, _LAST_RESULT="", _LAST_RESULT_PACK=""),
                patch.object(query_gui._PackQueryWindow, "_run_initial"),
            ):
                first = query_gui._PackQueryWindow(self.app, first_path)
                first._finish("第一包的完整查询结果")
                first.destroy()
                second = query_gui._PackQueryWindow(self.app, second_path)
                try:
                    assert "第一包的完整查询结果" not in second._output.get(
                        "1.0", "end"
                    )
                finally:
                    second.destroy()
                reopened = query_gui._PackQueryWindow(self.app, first_path)
                try:
                    text = reopened._output.get("1.0", "end")
                    assert "第一包的完整查询结果" in text
                    assert "上次查询快照" in text
                finally:
                    reopened.destroy()

    def test_editing_save_inputs_retires_exports_and_late_read_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "save.txt"
            source.write_text("offline save evidence", encoding="utf-8")
            window = SaveWorkspace(self.app)
            try:
                window.source_var.set(str(source))
                window.map_var.set("")
                window.query_var.set("")
                window.refresh()
                self.pump_events_until(lambda: window._selection is not None)
                report = window._report
                assert report is not None
                for variable, value in (
                    (window.source_var, str(Path(directory) / "different.txt")),
                    (window.map_var, "different.w3x"),
                    (window.encoding_var, "utf-8"),
                ):
                    window._report = report
                    window._selection = select_save_report(report)
                    window.export_button.configure(state="normal")
                    generation = window._generation
                    variable.set(value)
                    assert window._report is None
                    assert window._selection is None
                    assert window.export_button.cget("state") == "disabled"
                    window._receive_report(report, generation, 0.0)
                    assert window._report is None
                    assert "上次快照" in window.status.cget("text")
            finally:
                window.destroy()


def test_explicit_missing_diff_pack_never_falls_back_to_remembered_pack() -> None:
    requests = []
    window = cast(
        query_gui._PackQueryWindow,
        cast(
            object,
            SimpleNamespace(
                _pack_dir="current-pack",
                _diff_against=lambda: "remembered-pack",
                _save_diff_against=lambda _value: None,
            ),
        ),
    )

    def execute(options):
        requests.append(options)
        return SimpleNamespace(
            render=lambda **_kwargs: "diagnostic", extra_diagnostics=()
        )

    with patch("gametool.pack_query_cli.execute_pack_query", execute):
        query_gui._PackQueryWindow._run_query(window, "diff", "missing-explicit-pack")
        query_gui._PackQueryWindow._run_query(window, "diff", "")
    assert [request.pack_dir_b for request in requests] == [
        "missing-explicit-pack",
        "remembered-pack",
    ]
