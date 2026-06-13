"""war3map.imp 导入文件清单解析测试。

格式（实测自真实地图，与 w3x2lni 一致）：
  int32 version, int32 count
  每条: 1 字节标志 + \\0 结尾的路径字符串
找不到该名时按惯例尝试加前缀 war3mapImported\\。
"""
import os
import struct
import unittest

from w3xtool.imp import parse_imp

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _build(version, names):
    out = struct.pack("<ii", version, len(names))
    for flag, name in names:
        out += bytes([flag]) + name.encode("utf-8") + b"\x00"
    return out


class TestParseImp(unittest.TestCase):
    def test_basic_entries(self):
        data = _build(1, [(5, "war3mapImported\\foo.mdx"),
                          (10, "ReplaceableTextures\\bar.blp")])
        self.assertEqual(parse_imp(data),
                         ["war3mapImported\\foo.mdx",
                          "ReplaceableTextures\\bar.blp"])

    def test_empty_list(self):
        self.assertEqual(parse_imp(_build(1, [])), [])

    def test_truncated_returns_partial(self):
        # 注水/截断：count 声明 3 个但数据只够 1 个 → 返回已读到的，不抛
        data = struct.pack("<ii", 1, 3) + bytes([5]) + b"a.mdx\x00"
        self.assertEqual(parse_imp(data), ["a.mdx"])

    def test_absurd_count_does_not_hang(self):
        # 注水的超大 count 不应进入数十亿次循环
        data = struct.pack("<ii", 1, 0x7FFFFFFF)
        self.assertEqual(parse_imp(data), [])

    def test_garbage_returns_empty(self):
        self.assertEqual(parse_imp(b""), [])
        self.assertEqual(parse_imp(b"\x01\x02"), [])

    def test_real_map_fixture(self):
        # 真实地图 Matrix3 的 war3map.imp（5 条）
        data = open(os.path.join(FIX, "matrix.imp"), "rb").read()
        names = parse_imp(data)
        self.assertEqual(len(names), 5)
        self.assertTrue(all(isinstance(n, str) and n for n in names))
        self.assertTrue(names[0].startswith("Replaceable"))


class _FakeArchive:
    """最小 archive：按名字返回字节，支持 has_file/read_file。"""
    def __init__(self, files):
        self._files = files            # {name: bytes}

    def has_file(self, n):
        return n in self._files

    def read_file(self, n):
        return self._files[n]


class TestImportedNamesForExport(unittest.TestCase):
    def test_imp_names_feed_export_discovery(self):
        from w3xtool.api import _imported_names
        imp = _build(1, [(5, "war3mapImported\\model.mdx"),
                         (5, "icon.blp")])
        arch = _FakeArchive({
            "war3map.imp": imp,
            "war3mapImported\\model.mdx": b"MDX",
            "war3mapImported\\icon.blp": b"BLP",   # imp 里是相对名 icon.blp
        })
        names = _imported_names(arch)
        # 直查得到的原名保留；相对名直查不到时补 war3mapImported\ 前缀
        self.assertIn("war3mapImported\\model.mdx", names)
        self.assertIn("war3mapImported\\icon.blp", names)

    def test_no_imp_returns_empty(self):
        from w3xtool.api import _imported_names
        self.assertEqual(_imported_names(_FakeArchive({})), [])


if __name__ == "__main__":
    unittest.main()
