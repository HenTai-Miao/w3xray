"""war3map.wct 自定义脚本文本解析测试（移植自 w3x2lni frontend_wct.lua）。

格式：L 版本(>1 则==0x80000004 重制，再读真版本==1)；全局块 cstr 注释 + i32 size + (size!=0: cstr 代码)；
经典：i32 count + 每块 u32 size(0=空，否则 size-1 字节代码 + 1 字节 NUL)；重制：无 count 读到 EOF。
"""
import struct
import unittest

from w3xtool.wct import parse_wct


def _block(code):
    if code == "":
        return struct.pack("<I", 0)
    enc = code.encode("utf-8")
    return struct.pack("<I", len(enc) + 1) + enc + b"\x00"


def _wct(comment, custom_code, triggers, version=1):
    b = struct.pack("<I", version)
    b += comment.encode("utf-8") + b"\x00"
    if custom_code:
        enc = custom_code.encode("utf-8")
        b += struct.pack("<i", len(enc) + 1) + enc + b"\x00"
    else:
        b += struct.pack("<i", 0)
    b += struct.pack("<i", len(triggers))
    for t in triggers:
        b += _block(t)
    return b


class TestParseWct(unittest.TestCase):
    def test_global_custom_code(self):
        w = parse_wct(_wct("注释", "globals\n  integer x\nendglobals", []))
        self.assertEqual(w.custom_comment, "注释")
        self.assertIn("endglobals", w.custom_code)
        self.assertEqual(w.triggers, [])

    def test_trigger_blocks(self):
        w = parse_wct(_wct("", "", ["call A()", "", "call B()"]))
        self.assertEqual(w.triggers, ["call A()", "", "call B()"])

    def test_empty_global_and_triggers(self):
        w = parse_wct(_wct("", "", []))
        self.assertEqual(w.custom_code, "")
        self.assertEqual(w.triggers, [])

    def test_truncated_returns_partial(self):
        # 触发器块声明 3 个但数据只够 1 个 → 保留已读，不抛
        data = struct.pack("<I", 1) + b"\x00" + struct.pack("<i", 0)  # ver, 空注释, 全局 size=0
        data += struct.pack("<i", 3) + _block("ok") + struct.pack("<I", 99)  # count=3, 1好 + 截断
        w = parse_wct(data)
        self.assertEqual(w.triggers[:1], ["ok"])

    def test_bad_version_returns_empty(self):
        w = parse_wct(struct.pack("<I", 99) + b"\x00")
        self.assertEqual(w.custom_code, "")
        self.assertEqual(w.triggers, [])

    def test_garbage_returns_empty(self):
        self.assertEqual(parse_wct(b"").triggers, [])


class _FakeArchive:
    def __init__(self, files):
        self._files = files

    def has_file(self, n):
        return n in self._files

    def read_file(self, n):
        return self._files[n]


class TestWctIntegration(unittest.TestCase):
    def test_decoded_wct_added_to_scripts(self):
        from w3xtool.api import _add_wct, MapData
        wct = _wct("", "globals\n integer g\nendglobals", ["call Foo()", ""])
        md = MapData(path="x", name="x")
        _add_wct(md, _FakeArchive({"war3map.wct": wct}))
        # 解码后的可读代码作为一个脚本条目加入，供"导出脚本"/查看
        key = next((k for k in md.scripts if k.endswith(".txt") and "wct" in k.lower()), None)
        self.assertIsNotNone(key)
        text = md.scripts[key]
        self.assertIn("endglobals", text)
        self.assertIn("call Foo()", text)

    def test_no_wct_is_noop(self):
        from w3xtool.api import _add_wct, MapData
        md = MapData(path="x", name="x")
        _add_wct(md, _FakeArchive({}))
        self.assertEqual(md.scripts, {})


if __name__ == "__main__":
    unittest.main()
