"""AI CLI 配置：内置预设(claude/codex/opencode) + 存取往返 + 容错。"""
import os
import tempfile
import unittest

from w3xtool.aicli.config import (PRESETS, AIConfig, default_config,
                                  get_active, load_config, save_config)
from w3xtool.aicli.runner import AIProfile


class TestPresets(unittest.TestCase):
    def test_three_presets_present(self):
        for name in ("claude", "codex", "opencode"):
            self.assertIn(name, PRESETS)
            self.assertIsInstance(PRESETS[name], AIProfile)
            self.assertTrue(PRESETS[name].command)        # 非空命令

    def test_default_config_includes_presets_and_active(self):
        cfg = default_config()
        names = {p.name for p in cfg.profiles}
        self.assertTrue({"claude", "codex", "opencode"} <= names)
        self.assertTrue(cfg.active)                        # 有默认当前项


class TestRoundtrip(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(self.path)        # 让文件先不存在

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_save_then_load_roundtrip(self):
        cfg = AIConfig(profiles=[AIProfile(name="x", command=["foo", "{prompt}"],
                                           timeout=42.0, input_mode="stdin")],
                       active="x")
        save_config(cfg, self.path)
        loaded = load_config(self.path)
        self.assertEqual(loaded.active, "x")
        self.assertEqual(loaded.profiles[0].command, ["foo", "{prompt}"])
        self.assertEqual(loaded.profiles[0].timeout, 42.0)
        self.assertEqual(loaded.profiles[0].input_mode, "stdin")

    def test_load_missing_file_returns_default(self):
        cfg = load_config(self.path)               # 文件不存在
        self.assertTrue(cfg.profiles)              # 回落到默认（含预设）

    def test_load_corrupt_file_returns_default(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        cfg = load_config(self.path)
        self.assertTrue(cfg.profiles)

    def test_get_active_returns_profile_by_name(self):
        cfg = AIConfig(profiles=[AIProfile(name="a", command=["a"]),
                                 AIProfile(name="b", command=["b"])], active="b")
        self.assertEqual(get_active(cfg).name, "b")

    def test_get_active_none_when_missing(self):
        cfg = AIConfig(profiles=[AIProfile(name="a", command=["a"])], active="zzz")
        self.assertIsNone(get_active(cfg))


if __name__ == "__main__":
    unittest.main()
