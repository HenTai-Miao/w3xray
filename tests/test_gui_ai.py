"""GUI AI 设置冒烟测试：配置加载、设置对话框可建、表单解析往返。"""
import unittest

from w3xtool.gui import App


class TestGuiAI(unittest.TestCase):
    def setUp(self):
        self.app = App()

    def tearDown(self):
        self.app.destroy()

    def test_ai_config_loaded_with_profiles(self):
        self.assertTrue(self.app._ai_config.profiles)

    def test_open_settings_creates_window(self):
        self.app._open_settings()
        self.assertIsNotNone(self.app._settings_win)
        self.assertTrue(self.app._settings_win.winfo_exists())

    def test_settings_form_parses_command_and_fields(self):
        self.app._open_settings()
        f = self.app._set_fields
        for k, v in (("name", "t"), ("command", "claude -p {prompt}"),
                     ("input_mode", "stdin"), ("cwd", ""), ("timeout", "60")):
            f[k].delete(0, "end")
            f[k].insert(0, v)
        prof = self.app._settings_form_profile()
        self.assertEqual(prof.name, "t")
        self.assertEqual(prof.command, ["claude", "-p", "{prompt}"])
        self.assertEqual(prof.input_mode, "stdin")
        self.assertEqual(prof.timeout, 60.0)

    def test_ai_tab_widgets_exist(self):
        self.assertTrue(hasattr(self.app, "ai_box"))
        self.assertTrue(hasattr(self.app, "_auto_audit_var"))

    def test_ai_set_text_updates_box(self):
        self.app._ai_set_text("质检结果示例")
        self.assertIn("质检结果示例", self.app.ai_box.get("1.0", "end"))

    def test_ai_audit_without_map_is_safe(self):
        # 没打开地图时自动模式应静默返回，不抛
        self.app.map_data = None
        self.app._ai_config.auto_audit = True
        self.app._on_ai_audit(auto=True)   # 不应抛异常

    def test_settings_silent_save_persists_form(self):
        # 关窗静默保存：编辑后即使不点保存也不丢（save 打桩，不污染真实配置）
        import w3xtool.gui as g
        captured = {}
        orig = g.save_ai_config
        g.save_ai_config = lambda cfg, *a, **k: captured.setdefault("cfg", cfg)
        try:
            self.app._open_settings()
            f = self.app._set_fields
            f["name"].delete(0, "end"); f["name"].insert(0, "myai")
            f["command"].delete(0, "end"); f["command"].insert(0, "claude -p")
            self.app._settings_save_silent()
            self.assertEqual(self.app._ai_config.active, "myai")
            self.assertTrue(any(p.name == "myai" for p in self.app._ai_config.profiles))
            self.assertIn("cfg", captured)        # 确实落盘了
        finally:
            g.save_ai_config = orig


if __name__ == "__main__":
    unittest.main()
