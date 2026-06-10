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


if __name__ == "__main__":
    unittest.main()
