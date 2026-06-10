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

    def test_resolve_uses_table(self):
        table = {111: "圣水"}
        self.assertEqual(resolve("TRIGSTR_111", table), "圣水")
        self.assertEqual(resolve("普通文本", table), "普通文本")


if __name__ == "__main__":
    unittest.main()
