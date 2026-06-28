"""地图目录扫描测试。"""
from __future__ import annotations

import os
import threading
import unittest
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
