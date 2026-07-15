"""GUI exports use the same no-follow output writer as knowledge packs."""

from __future__ import annotations

import errno
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from tests.gui_base import GuiTestCase
from tests.gui_worker_fakes import InlineGuiThread
from w3xtool.api import GameObject, MapData
from w3xtool.gui_worker_registry import GuiWorkerRegistry


class GuiExportSafetyTest(GuiTestCase):
    def test_export_error_redacts_absolute_source_path(self) -> None:
        output = Path(self.create_temp_dir()) / "scripts"
        secret = output.parent / "private" / "source.w3x"
        md = MapData(path="x.w3x", name="错误路径安全图")
        md.scripts = {
            "war3map.j": "function main takes nothing returns nothing\nendfunction\n"
        }
        self.app.map_data = md

        with patch(
            "w3xtool.gui_export_actions.tmp_extract_dir", return_value=str(output)
        ):
            with patch.object(
                self.app,
                "_gui_workers",
                GuiWorkerRegistry(thread_factory=InlineGuiThread),
            ):
                with patch(
                    "w3xtool.gui_export_actions.write_script_exports",
                    side_effect=OSError(errno.EACCES, "denied", str(secret)),
                ):
                    with patch(
                        "w3xtool.gui_export_actions.messagebox.showerror"
                    ) as show_error:
                        self.app.on_export_scripts()
                        self.app.update()

        message = show_error.call_args.args[1]
        self.assertIn("PermissionError", message)
        self.assertNotIn(str(secret), message)
        self.assertIn("<path>", message)

    def test_script_export_does_not_follow_destination_symlink(self) -> None:
        output = Path(self.create_temp_dir()) / "scripts"
        output.mkdir()
        outside = output.parent / "outside.j"
        outside.write_text("before", encoding="utf-8")
        self._symlink(output / "war3map.j", outside)
        md = MapData(path="x.w3x", name="脚本安全图")
        md.scripts = {
            "war3map.j": "function main takes nothing returns nothing\nendfunction\n",
        }
        self.app.map_data = md

        with patch(
            "w3xtool.gui_export_actions.tmp_extract_dir", return_value=str(output)
        ):
            with patch.object(
                self.app,
                "_gui_workers",
                GuiWorkerRegistry(thread_factory=InlineGuiThread),
            ):
                with patch("w3xtool.gui_export_actions.messagebox.showinfo"):
                    self.app.on_export_scripts()
                    self.app.update()

        self.assertEqual(outside.read_text(encoding="utf-8"), "before")

    def test_id_export_does_not_follow_destination_symlink(self) -> None:
        output = Path(self.create_temp_dir()) / "ids"
        output.mkdir()
        outside = output.parent / "outside.txt"
        outside.write_text("before", encoding="utf-8")
        self._symlink(output / "单位ID.txt", outside)
        md = MapData(path="x.w3x", name="ID安全图")
        md.objects = {
            "单位": [GameObject("单位", "w3u", "H001", "Hpal", "单位", True)],
        }
        self.app.map_data = md

        with patch(
            "w3xtool.gui_export_actions.tmp_extract_dir", return_value=str(output)
        ):
            with patch.object(
                self.app,
                "_gui_workers",
                GuiWorkerRegistry(thread_factory=InlineGuiThread),
            ):
                with patch("w3xtool.gui_export_actions.messagebox.showinfo"):
                    self.app.on_export_ids()
                    self.app.update()

        self.assertEqual(outside.read_text(encoding="utf-8"), "before")

    def create_temp_dir(self) -> str:
        directory = tempfile.mkdtemp(prefix="w3xray-gui-export-")
        self.addCleanup(self._remove_tree, directory)
        return directory

    def _remove_tree(self, path: str) -> None:
        shutil.rmtree(path, ignore_errors=True)

    def _symlink(self, link: Path, target: Path) -> None:
        try:
            link.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"symlink unavailable: {exc}")
