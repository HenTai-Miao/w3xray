"""拖拽分隔条位置持久化测试。"""
import unittest

from tests.gui_base import GuiTestCase
from w3xtool.theme import LAYOUT_VERSION


class TestPaneState(GuiTestCase):
    def test_object_editor_pane_positions_save_on_drag_release(self):
        # Given: the user has dragged the object editor split panes.
        saved = {}
        original_save = self.app._save_config
        self.app._save_config = lambda **kw: saved.update(kw)

        try:
            self.app.deiconify()
            self.app.tabs.set("对象编辑器")
            self.app.update_idletasks()
            self.app.paned.sashpos(0, 210)
            self.app.paned.sashpos(1, 980)

            # When: the drag ends.
            self.app.paned.event_generate("<ButtonRelease-1>")
            self.app.update()

            # Then: the positions are saved immediately, not only on app close.
            self.assertEqual(saved["layout"], LAYOUT_VERSION)
            self.assertEqual(saved["pane_sashes"]["object_editor"], [210, 980])
        finally:
            self.app._save_config = original_save
            self.app.withdraw()

    def test_object_editor_pane_positions_restore_from_named_config(self):
        # Given: a saved object editor layout from a previous run.
        original_load = self.app._load_config
        self.app._load_config = lambda: {
            "layout": LAYOUT_VERSION,
            "pane_sashes": {"object_editor": [190, 920]},
        }

        try:
            self.app.deiconify()
            self.app.tabs.set("对象编辑器")
            self.app.update_idletasks()
            self.app.paned.sashpos(0, 260)
            self.app.paned.sashpos(1, 1050)

            # When: layout restoration runs.
            self.app._restore_pane_sashes()

            # Then: the object editor panes return to the saved positions.
            self.assertEqual([self.app.paned.sashpos(0), self.app.paned.sashpos(1)], [190, 920])
        finally:
            self.app._load_config = original_load
            self.app.withdraw()


if __name__ == "__main__":
    unittest.main()
