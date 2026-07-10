"""拖拽分隔条位置持久化测试。"""
import unittest

from tests.gui_base import GuiTestCase
from w3xtool.gui_pane_state import _apply_sash_positions, _paned_sash_positions
from w3xtool.theme import LAYOUT_VERSION


class TestPaneState(GuiTestCase):
    def test_object_editor_pane_defers_resize_while_dragging(self):
        # Given: the object editor pane contains heavy list/detail widgets.
        self.show_app()
        self.app.tabs.set("对象编辑器")
        self.pump_events_until(
            lambda: bool(self.app.paned.winfo_ismapped()) and self.app.paned.winfo_width() >= 900,
        )

        # When / Then: dragging the sash uses deferred resize instead of
        # continuously relayouting all child panes.
        self.assertEqual(str(self.app.paned.cget("opaqueresize")), "0")

    def test_object_editor_pane_positions_save_on_drag_release(self):
        # Given: the user has dragged the object editor split panes.
        saved = {}
        original_save = self.app._save_config
        self.app._save_config = lambda **kw: saved.update(kw)

        try:
            self.show_app()
            self.app.tabs.set("对象编辑器")
            self.pump_events_until(
                lambda: bool(self.app.paned.winfo_ismapped()) and self.app.paned.winfo_width() >= 900,
            )
            _apply_sash_positions(self.app.paned, [720])
            self.app.update()

            # When: the drag ends.
            self.app.paned.event_generate("<ButtonRelease-1>")
            self.app.update()

            # Then: the positions are saved immediately, not only on app close.
            self.assertEqual(saved["layout"], LAYOUT_VERSION)
            self.assertEqual(saved["pane_sashes"]["object_editor"], [720])
        finally:
            self.app._save_config = original_save
            self.app.withdraw()

    def test_object_editor_pane_positions_restore_from_named_config(self):
        # Given: a saved object editor layout from a previous run.
        original_load = self.app._load_config
        self.app._load_config = lambda: {
            "layout": LAYOUT_VERSION,
            "pane_sashes": {"object_editor": [680]},
        }

        try:
            self.show_app()
            self.app.tabs.set("对象编辑器")
            self.pump_events_until(
                lambda: bool(self.app.paned.winfo_ismapped()) and self.app.paned.winfo_width() >= 900,
            )
            _apply_sash_positions(self.app.paned, [760])
            self.app.update()

            # When: layout restoration runs.
            self.app._restore_pane_sashes()
            self.app.update()

            # Then: the object editor panes return to the saved positions.
            self.assertEqual(_paned_sash_positions(self.app.paned), [680])
        finally:
            self.app._load_config = original_load
            self.app.withdraw()


if __name__ == "__main__":
    unittest.main()
