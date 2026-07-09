"""war3map.imp 导入文件清单解析测试。

格式（实测自真实地图，与 w3x2lni 一致）：
  int32 version, int32 count
  每条: 1 字节标志 + \\0 结尾的路径字符串
找不到该名时按惯例尝试加前缀 war3mapImported\\。
"""
import os
import struct
import unittest
from unittest.mock import patch

from w3xtool.imp import ImportEntry, parse_imp, parse_import_table

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _build(version, names):
    out = struct.pack("<ii", version, len(names))
    for flag, name in names:
        out += bytes([flag]) + name.encode("utf-8") + b"\x00"
    return out


def _build_raw(version, rows):
    out = struct.pack("<ii", version, len(rows))
    for flag, raw_name in rows:
        out += bytes([flag]) + raw_name + b"\x00"
    return out


class TestParseImp(unittest.TestCase):
    def test_basic_entries(self):
        data = _build(1, [(5, "war3mapImported\\foo.mdx"),
                          (10, "ReplaceableTextures\\bar.blp")])
        self.assertEqual(parse_imp(data),
                         ["war3mapImported\\foo.mdx",
                          "ReplaceableTextures\\bar.blp"])

    def test_structured_entries_keep_flags(self):
        data = _build(1, [(8, "icon.blp"), (13, "ReplaceableTextures\\bar.blp")])
        table = parse_import_table(data)

        self.assertEqual(table.version, 1)
        self.assertEqual(table.entry_count, 2)
        self.assertEqual(table.entries[0].type_label, "标准路径")
        self.assertEqual(table.entries[0].candidate_paths[0], "war3mapImported\\icon.blp")
        self.assertEqual(table.entries[1].type_label, "自定义路径")
        self.assertEqual(table.entries[1].candidate_paths, ("ReplaceableTextures\\bar.blp",))

    def test_windows_acp_import_path_precedes_gbk(self):
        # Given: an import path saved using Traditional Chinese ACP.
        raw_name = "素材\\測試.blp".encode("cp950")
        data = _build_raw(1, [(13, raw_name)])

        # When: Windows ACP is cp950.
        with patch("w3xtool.war3_encoding.default_legacy_codecs", return_value=("cp950", "gbk")):
            table = parse_import_table(data)

        # Then: the path remains readable and usable in resource reports.
        self.assertEqual(table.entries[0].path, "素材\\測試.blp")

    def test_unknown_flag_keeps_legacy_fallback_candidate(self):
        entry = ImportEntry(path="icon.blp", flag=5)

        self.assertEqual(entry.type_label, "未知(5)")
        self.assertEqual(entry.candidate_paths, ("icon.blp", "war3mapImported\\icon.blp"))
        self.assertEqual(entry.extension, "blp")

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

    def test_campaign_imp_names_feed_export_discovery(self):
        from w3xtool.api import _imported_names
        imp = _build(1, [(13, "UI\\CampaignIcon.blp")])
        arch = _FakeArchive({"war3campaign.imp": imp})

        names = _imported_names(arch)

        self.assertIn("UI\\CampaignIcon.blp", names)

    def test_import_flags_shape_export_candidates(self):
        from w3xtool.api import _imported_names
        imp = _build(1, [(8, "icon.blp"), (13, "ReplaceableTextures\\custom.blp")])
        arch = _FakeArchive({"war3map.imp": imp})

        names = _imported_names(arch)

        self.assertIn("war3mapImported\\icon.blp", names)
        self.assertIn("icon.blp", names)
        self.assertIn("ReplaceableTextures\\custom.blp", names)
        self.assertNotIn("war3mapImported\\ReplaceableTextures\\custom.blp", names)

    def test_no_imp_returns_empty(self):
        from w3xtool.api import _imported_names
        self.assertEqual(_imported_names(_FakeArchive({})), [])

    def test_add_import_summary_reports_missing_resources(self):
        from w3xtool.api import MapData
        from w3xtool.map_extras import add_import_summary

        imp = _build(1, [(8, "icon.blp"), (13, "ReplaceableTextures\\custom.blp")])
        arch = _FakeArchive({
            "war3map.imp": imp,
            "war3mapImported\\icon.blp": b"BLP",
        })
        md = MapData(path="x.w3x", name="x")

        add_import_summary(md, arch)

        self.assertEqual(md.import_summary.entry_count, 2)
        self.assertEqual(md.import_summary.standard_count, 1)
        self.assertEqual(md.import_summary.custom_count, 1)
        self.assertEqual(md.import_summary.resolved_paths, ("war3mapImported\\icon.blp",))
        self.assertEqual(md.import_summary.missing_paths, ("ReplaceableTextures\\custom.blp",))

    def test_add_import_summary_reads_campaign_import_table(self):
        from w3xtool.api import MapData
        from w3xtool.map_extras import add_import_summary

        imp = _build(1, [(13, "UI\\CampaignIcon.blp")])
        arch = _FakeArchive({
            "war3campaign.imp": imp,
            "UI\\CampaignIcon.blp": b"BLP",
        })
        md = MapData(path="x.w3n", name="x")

        add_import_summary(md, arch)

        self.assertEqual(md.import_summary.entry_count, 1)
        self.assertEqual(md.import_summary.resolved_paths, ("UI\\CampaignIcon.blp",))


if __name__ == "__main__":
    unittest.main()
