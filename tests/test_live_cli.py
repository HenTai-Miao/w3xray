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

    def test_profile_export_and_load_options(self):
        opts = parse_live_cli_options(
            (
                "--pack",
                "pk",
                "--export-profile",
                "out.json",
                "--profile-json",
                "in.json",
                "--pid",
                "12345",
            )
        )
        assert opts.export_profile == "out.json"
        assert opts.profile_json == "in.json"
        assert opts.pid == "12345"

    def test_missing_everything(self):
        # 解析层不再拒绝: 无参数时交给入口自动定位当前图 (定位失败才提示)
        opts = parse_live_cli_options(())
        assert opts.map_path is None and opts.pack_dir is None

    def test_run_without_map_reports_guidance(self, monkeypatch, capsys):
        from w3xtool import live_cli

        monkeypatch.setattr(live_cli, "_auto_map_path", lambda: None)
        code = live_cli.run_live_cli(live_cli.LiveCliOptions())
        err = capsys.readouterr().err
        assert code == 2
        assert "未能自动定位正在使用的图" in err

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

    def test_elevated_hint(self):
        opts = parse_live_cli_options(("m.w3x", "--elevated-hint"))
        assert opts.elevated_hint is True
        assert parse_live_cli_options(("m.w3x",)).elevated_hint is False


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


def test_read_live_offline_snapshot_fail_open(tmp_path):
    """合成快照全流程: 无进程不炸, 异常逐层兜进 notes (fail-open 端到端)。"""
    import json

    pytest.importorskip("numpy")
    from w3xtool.live_inventory import read_live

    d = tmp_path / "snap"
    d.mkdir()
    (d / "index.json").write_text(
        json.dumps([{"base": 0x60000000, "off": 0, "len": 0x20000}]),
        encoding="utf-8",
    )
    (d / "snap.bin").write_bytes(bytes(0x20000))
    rep = read_live(None, load_snapshot_dir=str(d), verbose=False)
    assert rep["strategy_used"] is None
    assert rep["pid"] is None  # 离线快照无进程归属
    assert any("需要运行中的游戏" in n for n in rep["notes"])
    assert any("跳过" in n for n in rep["notes"])  # 用户语言, 非程序员异常
    assert not any("TypeError" in n for n in rep["notes"])
    assert rep["resources"] is None and rep["player_rows"] is None
