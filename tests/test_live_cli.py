# -*- coding: utf-8 -*-
"""live 子命令参数解析与调度边界测试。"""

from __future__ import annotations

import os

import pytest

from w3xtool.live_cli import (
    LiveCliOptionError,
    live_pack_cache_dir,
    parse_live_cli_options,
)


class TestParse:
    def test_map_only(self):
        opts = parse_live_cli_options(("maps/rpg.w3x",))
        assert opts.map_path == "maps/rpg.w3x"
        assert opts.strategy == "auto"
        assert opts.pack_dir is None

    def test_pack_only_no_map(self):
        opts = parse_live_cli_options(("--pack", "D:/pack"))
        assert opts.pack_dir == "D:/pack"
        assert opts.map_path is None

    def test_all_options(self):
        opts = parse_live_cli_options(
            (
                "m.w3x",
                "--strategy",
                "icons",
                "--test-image",
                "shot.png",
                "--save-snapshot",
                "snapdir",
                "--load-snapshot",
                "snapdir",
            )
        )
        assert opts.strategy == "icons"
        assert opts.test_image == "shot.png"
        assert opts.save_snapshot == "snapdir"
        assert opts.load_snapshot == "snapdir"

    def test_missing_everything(self):
        with pytest.raises(LiveCliOptionError, match="缺少地图路径"):
            parse_live_cli_options(())

    def test_unknown_option(self):
        with pytest.raises(LiveCliOptionError, match="不支持的参数"):
            parse_live_cli_options(("m.w3x", "--wat"))

    def test_bad_strategy(self):
        with pytest.raises(LiveCliOptionError, match="未知策略"):
            parse_live_cli_options(("m.w3x", "--strategy", "hack"))

    def test_duplicate_pack(self):
        with pytest.raises(LiveCliOptionError, match="不能重复"):
            parse_live_cli_options(("--pack", "a", "--pack", "b"))

    def test_option_without_value(self):
        with pytest.raises(LiveCliOptionError, match="缺少路径值"):
            parse_live_cli_options(("m.w3x", "--test-image"))


class TestPackCacheDir:
    def test_key_changes_with_mtime(self, tmp_path, monkeypatch):
        mp = tmp_path / "m.w3x"
        mp.write_bytes(b"data")
        monkeypatch.setenv("W3XRAY_CACHE_DIR", str(tmp_path / "cache"))
        d1 = live_pack_cache_dir(str(mp))
        os.utime(mp, (1, 100))
        d2 = live_pack_cache_dir(str(mp))
        assert d1 != d2
        assert d1.parent.name == "live-pack"


class TestRunCli:
    def test_missing_deps_message(self, monkeypatch, tmp_path):
        import builtins

        from w3xtool import live_cli

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == ".live_inventory" or name.endswith("live_inventory"):
                raise ImportError("numpy missing")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        code = live_cli.run_live_cli(live_cli.LiveCliOptions(pack_dir=str(tmp_path)))
        assert code == 2
