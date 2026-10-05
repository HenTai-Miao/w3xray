"""地图目录扫描测试。"""

from __future__ import annotations

import os
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from w3xtool.map_directory import scan_battle_maps


class TestMapDirectory(unittest.TestCase):
    def test_scan_battle_maps_returns_recent_supported_maps_with_names(self):
        # Given: a directory has map files and unrelated files.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_map = root / "old.w3x"
            nested_map = root / "nested" / "new.W3M"
            ignored = root / "note.txt"
            nested_map.parent.mkdir()
            for path in (old_map, nested_map, ignored):
                path.write_text("x", encoding="utf-8")
            os.utime(old_map, (10, 10))
            os.utime(nested_map, (20, 20))
            os.utime(ignored, (30, 30))

            # When: the battle map directory is scanned.
            result = scan_battle_maps(
                tmp,
                name_loader=lambda path: f"地图:{Path(path).stem}",
                max_workers=2,
            )

            # Then: only Warcraft map files are returned, newest first.
            self.assertEqual(
                result,
                [
                    (str(nested_map), "地图:new"),
                    (str(old_map), "地图:old"),
                ],
            )

    def test_scan_battle_maps_prefers_download_time_over_preserved_mtime(self):
        # Given: a newer download can preserve an older source modification time.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_download = root / "older-download.w3x"
            new_download = root / "new-download.w3x"
            old_download.write_text("a", encoding="utf-8")
            new_download.write_text("b", encoding="utf-8")
            timestamps = {
                str(old_download): (20, 100),
                str(new_download): (10, 300),
            }

            def fake_getmtime(path: str) -> float:
                return timestamps[path][0]

            def fake_stat(path: str, **_kwargs: object) -> SimpleNamespace:
                mtime, ctime = timestamps[str(path)]
                return SimpleNamespace(st_mtime=mtime, st_ctime=ctime)

            # When: sorting files whose metadata was preserved during download.
            with (
                patch.object(os.path, "getmtime", side_effect=fake_getmtime),
                patch.object(os, "stat", side_effect=fake_stat),
            ):
                result = scan_battle_maps(
                    tmp,
                    name_loader=lambda path: Path(path).stem,
                    max_workers=1,
                )

            # Then: the most recently downloaded map is first.
            self.assertEqual(
                result,
                [
                    (str(new_download), "new-download"),
                    (str(old_download), "older-download"),
                ],
            )

    def test_scan_battle_maps_loads_names_concurrently(self):
        # Given: map name loading blocks until two workers are active.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "a.w3x"
            second = root / "b.w3x"
            first.write_text("a", encoding="utf-8")
            second.write_text("b", encoding="utf-8")
            barrier = threading.Barrier(2, timeout=2)

            def name_loader(path: str) -> str:
                barrier.wait()
                return Path(path).stem

            # When: scanning with two workers.
            result = scan_battle_maps(tmp, name_loader=name_loader, max_workers=2)

            # Then: both files complete without serializing through one worker.
            self.assertEqual({name for _path, name in result}, {"a", "b"})


if __name__ == "__main__":
    unittest.main()
