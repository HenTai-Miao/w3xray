"""war3map.wct 自定义脚本文本解析测试（移植自 w3x2lni frontend_wct.lua）。

格式：L 版本(>1 则==0x80000004 重制，再读真版本==1)；全局块 cstr 注释 + i32 size + (size!=0: cstr 代码)；
经典：i32 count + 每块 u32 size(0=空，否则 size-1 字节代码 + 1 字节 NUL)；重制：无 count 读到 EOF。
"""
import struct
import unittest

from w3xtool.wct import WctDiagnostic, parse_wct


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
        self.assertEqual(w.triggers, ["ok"])
        self.assertIs(w.diagnostic, WctDiagnostic.TRUNCATED)

    def test_truncated_count_keeps_confirmed_global_code(self):
        code = b"call Confirmed()"
        data = struct.pack("<I", 1) + b"comment\x00"
        data += struct.pack("<i", len(code) + 1) + code + b"\x00"

        w = parse_wct(data)

        self.assertEqual(w.custom_comment, "comment")
        self.assertEqual(w.custom_code, "call Confirmed()")
        self.assertIs(w.diagnostic, WctDiagnostic.TRUNCATED)

    def test_truncated_global_size_keeps_confirmed_comment(self):
        # Given: the comment terminates before an incomplete global-size field.
        data = struct.pack("<I", 1) + b"confirmed comment\x00" + b"\x01\x00"

        # When: the partial WCT is parsed.
        w = parse_wct(data)

        # Then: already-confirmed metadata remains available.
        self.assertEqual(w.custom_comment, "confirmed comment")
        self.assertIs(w.diagnostic, WctDiagnostic.TRUNCATED)

    def test_global_code_uses_cstr_when_declared_size_is_nonzero(self):
        data = struct.pack("<I", 1) + b"\x00" + struct.pack("<i", 999)
        data += b"call Legacy()\x00" + struct.pack("<i", 0)

        w = parse_wct(data)

        self.assertEqual(w.custom_code, "call Legacy()")
        self.assertIsNone(w.diagnostic)

    def test_bad_version_returns_empty(self):
        w = parse_wct(struct.pack("<I", 99) + b"\x00")
        self.assertEqual(w.custom_code, "")
        self.assertEqual(w.triggers, [])
        self.assertIs(w.diagnostic, WctDiagnostic.UNSUPPORTED_VERSION)

    def test_garbage_returns_empty(self):
        w = parse_wct(b"")
        self.assertEqual(w.triggers, [])
        self.assertIs(w.diagnostic, WctDiagnostic.TRUNCATED)

    def test_reforged_reads_trigger_blocks_until_eof(self):
        data = struct.pack("<II", 0x80000004, 1) + b"\x00" + struct.pack("<i", 0)
        data += _block("call Reforged()") + _block("")

        w = parse_wct(data)

        self.assertEqual(w.triggers, ["call Reforged()", ""])
        self.assertIsNone(w.diagnostic)

    def test_result_preserves_legacy_mutable_fields(self):
        # Given: the long-standing mutable WCT result returned by the parser.
        w = parse_wct(_wct("comment", "call Original()", ["call First()"]))

        # When: a compatibility caller updates the parsed fields.
        w.custom_code = "call Replaced()"
        w.triggers.append("call Added()")

        # Then: field assignment and list mutation remain supported.
        self.assertEqual(w.custom_code, "call Replaced()")
        self.assertEqual(w.triggers, ["call First()", "call Added()"])


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
