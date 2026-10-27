"""拖拽分隔条位置持久化测试。"""

import platform
from pprint import pformat
import unittest

from tests.gui_base import GuiTestCase
from gametool.gui_pane_state import _apply_sash_positions, _paned_sash_positions
from gametool.theme import LAYOUT_VERSION

_SASH_TEST_MARGIN = 20


class TestPaneState(GuiTestCase):
    def _show_object_editor_with_sash_room(self) -> tuple[int, int]:
        self.show_app(diagnostics=self._pane_diagnostics)
        self.addCleanup(self.app.withdraw)

        original_source_width = int(self.app.source_panel.cget("width"))
        self.addCleanup(self._restore_source_panel_width, original_source_width)
        self.app.source_panel.configure(width=1)
        self.app.tabs.set("对象编辑器")

        left_pane, right_pane = self.app.paned.panes()
        left_min_size = int(self.app.paned.panecget(left_pane, "minsize"))
        right_min_size = int(self.app.paned.panecget(right_pane, "minsize"))
        sash_width = int(self.app.paned.cget("sashwidth"))
        required_width = (
            left_min_size + right_min_size + sash_width + 2 * _SASH_TEST_MARGIN + 1
        )
        self.pump_events_until(
            lambda: (
                bool(self.app.paned.winfo_ismapped())
                and self.app.paned.winfo_width() >= required_width
            ),
            timeout=10.0,
            diagnostics=self._pane_diagnostics,
        )

        lower = left_min_size + _SASH_TEST_MARGIN
        upper = (
            self.app.paned.winfo_width()
            - right_min_size
            - sash_width
            - _SASH_TEST_MARGIN
        )
        self.assertLess(lower, upper, self._pane_diagnostics())
        return lower, upper

    def _pane_diagnostics(self) -> str:
        app = self.app
        ancestors = []
        widget = app.paned
        while widget is not None:
            ancestors.append(
                {
                    "path": str(widget),
                    "manager": widget.winfo_manager(),
                    "mapped": widget.winfo_ismapped(),
                    "viewable": widget.winfo_viewable(),
                    "geometry": widget.winfo_geometry(),
                    "requested": (widget.winfo_reqwidth(), widget.winfo_reqheight()),
                }
            )
            widget = widget.master
        font = app._measure_font()
        return pformat(
            {
                "platform": platform.platform(),
                "machine": platform.machine(),
                "python": platform.python_version(),
                "tk": app.tk.call("package", "provide", "Tk"),
                "tcl": app.tk.call("info", "patchlevel"),
                "windowing_system": app.tk.call("tk", "windowingsystem"),
                "screen": (app.winfo_screenwidth(), app.winfo_screenheight()),
                "root_state": app.state(),
                "root_geometry": app.geometry(),
                "selected_tab": app.tabs.get(),
                "object_tab_mapped": app.tab_obj.winfo_ismapped(),
                "source_width": app.source_panel.cget("width"),
                "source_geometry": app.source_panel.winfo_geometry(),
                "font": font.actual(),
                "font_widths": {
                    sample: font.measure(sample) for sample in ("W", "汉字", "物品列宽")
                },
                "ancestors": ancestors,
                "panes": [
                    {
                        "path": str(pane),
                        "minsize": app.paned.panecget(pane, "minsize"),
                        "stretch": app.paned.panecget(pane, "stretch"),
                    }
                    for pane in app.paned.panes()
                ],
                "sash_width": app.paned.cget("sashwidth"),
                "sash_positions": _paned_sash_positions(app.paned),
                "pending_callbacks": {
                    str(callback): app.tk.call("after", "info", callback)
                    for callback in app.tk.splitlist(app.tk.call("after", "info"))
                },
            },
            sort_dicts=False,
        )

    def _restore_source_panel_width(self, width: int) -> None:
        self.app.source_panel.configure(width=width)
        self.app.update_idletasks()

    def test_object_editor_pane_defers_resize_while_dragging(self):
        # Given: the object editor pane contains heavy list/detail widgets.
        # When / Then: dragging the sash uses deferred resize instead of
        # continuously relayouting all child panes.
        self.assertEqual(str(self.app.paned.cget("opaqueresize")), "0")

    def test_object_editor_pane_positions_save_on_drag_release(self):
        # Given: the user has dragged the object editor split panes.
        saved = {}
        original_save = self.app._save_config
        self.app._save_config = lambda **kw: saved.update(kw)

        try:
            saved_position, _ = self._show_object_editor_with_sash_room()
            _apply_sash_positions(self.app.paned, [saved_position])
            self.app.update()
            self.assertEqual(
                _paned_sash_positions(self.app.paned),
                [saved_position],
                self._pane_diagnostics(),
            )

            # When: the drag ends.
            self.app.paned.event_generate("<ButtonRelease-1>")
            self.app.update()

            # Then: the positions are saved immediately, not only on app close.
            self.assertEqual(
                saved.get("layout"), LAYOUT_VERSION, self._pane_diagnostics()
            )
            self.assertEqual(
                saved["pane_sashes"]["object_editor"],
                [saved_position],
                self._pane_diagnostics(),
            )
        finally:
            self.app._save_config = original_save

    def test_object_editor_pane_positions_restore_from_named_config(self):
        original_load = self.app._load_config

        try:
            # Given: a saved object editor layout and a different current position.
            saved_position, other_position = self._show_object_editor_with_sash_room()
            self.app._load_config = lambda: {  # pyright: ignore[reportAttributeAccessIssue]
                "layout": LAYOUT_VERSION,
                "pane_sashes": {"object_editor": [saved_position]},
            }
            _apply_sash_positions(self.app.paned, [other_position])
            self.app.update()
            self.assertEqual(
                _paned_sash_positions(self.app.paned),
                [other_position],
                self._pane_diagnostics(),
            )

            # When: layout restoration runs.
            self.app._restore_pane_sashes()
            self.app.update()

            # Then: the object editor panes return to the saved positions.
            self.assertEqual(
                _paned_sash_positions(self.app.paned),
                [saved_position],
                self._pane_diagnostics(),
            )
        finally:
            self.app._load_config = original_load


if __name__ == "__main__":
    unittest.main()
