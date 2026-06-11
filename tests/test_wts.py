"""war3map.wts 字符串表解析：UTF-8 为主，单条 GBK 片段独立回退（混合编码地图）。"""
import unittest

from w3xtool.wts import parse_wts, resolve


class TestParseWts(unittest.TestCase):
    def test_basic_utf8(self):
        data = "STRING 1\n{\n你好\n}\n".encode("utf-8")
        self.assertEqual(parse_wts(data)[1], "你好")

    def test_bom_stripped(self):
        data = "﻿STRING 7\n{\nHi\n}\n".encode("utf-8")
        self.assertEqual(parse_wts(data)[7], "Hi")

    def test_mixed_encoding_per_string_gbk_fallback(self):
        # 大部分 UTF-8，个别字符串是 GBK（作者粘贴老内容）→ 各自独立解码，互不影响
        good = "STRING 1\n{\n正常\n}\n".encode("utf-8")
        gbk = "STRING 2\n{\n".encode("utf-8") + "测试".encode("gbk") + "\n}\n".encode("utf-8")
        table = parse_wts(good + gbk)
        self.assertEqual(table[1], "正常")        # UTF-8 条目不受影响
        self.assertEqual(table[2], "测试")        # GBK 条目正确还原，而非乱码

    def test_gbk_body_with_brace_trail_byte_not_truncated(self):
        # GBK 双字节字符的尾字节可能正好是 0x7D('}')。按字节找 '}' 会在此处误截断。
        # 闭合括号应锚定到行首，避免误伤。
        gbk_char = None
        for cp in range(0x4E00, 0xA000):
            try:
                b = chr(cp).encode("gbk")
            except UnicodeEncodeError:
                continue
            if len(b) == 2 and b[1] == 0x7D:
                gbk_char = chr(cp)
                break
        self.assertIsNotNone(gbk_char, "找不到尾字节为 0x7D 的 GBK 字符")
        body = ("前" + gbk_char + "后").encode("gbk")
        data = "STRING 9\n{\n".encode("utf-8") + body + "\n}\n".encode("utf-8")
        table = parse_wts(data)
        self.assertEqual(table[9], "前" + gbk_char + "后")   # 完整，未被 0x7D 截断

    def test_body_line_starting_with_brace_not_truncated(self):
        # 正文里有以 } 开头但非独占一行的行(如 JASS 片段 "} else {")，
        # 不应被当成闭合括号提前截断；真正的闭合是独占一行的 }。
        body = "if x then\n} else {\nreturn\n}}end"
        data = ("STRING 5\n{\n" + body + "\n}\nSTRING 6\n{\nnext\n}\n").encode("utf-8")
        table = parse_wts(data)
        self.assertEqual(table[5], body)
        self.assertEqual(table[6], "next")

    def test_resolve_uses_table(self):
        table = {111: "圣水"}
        self.assertEqual(resolve("TRIGSTR_111", table), "圣水")
        self.assertEqual(resolve("普通文本", table), "普通文本")


if __name__ == "__main__":
    unittest.main()
