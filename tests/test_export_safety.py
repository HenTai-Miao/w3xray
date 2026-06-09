"""导出文件名路径穿越防护测试。

地图内部文件名（来自不可信的 (listfile)）若是绝对路径或含 ..\\，
拼接输出路径时可能写到 out_dir 之外，造成任意文件写入。
_safe_export_path 必须把这类名字拒绝（返回 None），普通名字正常拼接。
"""
import os
import unittest

from w3xtool.api import _safe_export_path


class TestSafeExportPath(unittest.TestCase):
    def setUp(self):
        self.out = os.path.realpath(os.environ.get("TEMP", "."))

    def test_normal_name_joins_under_out_dir(self):
        dest = _safe_export_path(self.out, "war3map.j")
        self.assertEqual(dest, os.path.join(self.out, "war3map.j"))

    def test_subdir_name_allowed(self):
        dest = _safe_export_path(self.out, "scripts\\war3map.j")
        self.assertEqual(dest, os.path.join(self.out, "scripts", "war3map.j"))

    def test_windows_absolute_path_rejected(self):
        self.assertIsNone(
            _safe_export_path(self.out, "C:\\Windows\\System32\\evil.dll"))

    def test_parent_traversal_rejected(self):
        self.assertIsNone(
            _safe_export_path(self.out, "..\\..\\..\\evil.bat"))

    def test_embedded_traversal_rejected(self):
        self.assertIsNone(
            _safe_export_path(self.out, "scripts\\..\\..\\evil"))

    def test_empty_name_rejected(self):
        self.assertIsNone(_safe_export_path(self.out, ""))
        self.assertIsNone(_safe_export_path(self.out, "\\"))


if __name__ == "__main__":
    unittest.main()
