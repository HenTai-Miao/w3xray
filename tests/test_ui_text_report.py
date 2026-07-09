"""UI/TRIGSTR text extraction for map investigation."""

import unittest

from w3xtool.api import MapData
from w3xtool.ui_texts import (
    build_ui_text_report,
    format_ui_text_references_tsv,
    format_ui_text_strings_tsv,
)


class UiTextReportTest(unittest.TestCase):
    def test_report_extracts_wts_strings_and_script_references(self):
        # Given: a WTS table and scripts that reference UI/trigger strings.
        md = MapData(path="x.w3x", name="文本图")
        md.scripts = {
            "war3map.wts": "STRING 1\n{\n开始游戏\n}\nSTRING 2\n{\n隐藏提示\n}\n",
            "war3map.j": (
                'call DisplayTextToPlayer(Player(0),0,0,"TRIGSTR_001")\n'
                'call BJDebugMsg("TRIGSTR_999")\n'
            ),
            "war3map.wct(自定义代码).txt": 'call BJDebugMsg("TRIGSTR_002")\n',
        }

        # When: the UI text report is built.
        report = build_ui_text_report(md)

        # Then: WTS strings and their script references are available.
        self.assertEqual(report.string_count, 2)
        self.assertEqual(report.reference_count, 3)
        self.assertEqual(report.unresolved_count, 1)
        by_id = {item.trigstr: item.text for item in report.strings}
        self.assertEqual(by_id["TRIGSTR_001"], "开始游戏")
        self.assertEqual(by_id["TRIGSTR_002"], "隐藏提示")
        self.assertEqual(report.references[0].text, "开始游戏")
        self.assertEqual(report.references[-1].text, "隐藏提示")

    def test_formats_strings_and_references_as_tsv(self):
        # Given: a report with one resolved and one unresolved reference.
        md = MapData(path="x.w3x", name="文本图")
        md.scripts = {
            "war3map.wts": "STRING 7\n{\n测试文本\n}\n",
            "war3map.j": 'call BJDebugMsg("TRIGSTR_007")\ncall BJDebugMsg("TRIGSTR_888")',
        }

        # When: the report is formatted for the knowledge pack.
        report = build_ui_text_report(md)
        strings = format_ui_text_strings_tsv(report)
        refs = format_ui_text_references_tsv(report)

        # Then: the output is spreadsheet-friendly and preserves unresolved refs.
        self.assertIn("TRIGSTR\t文本", strings)
        self.assertIn("TRIGSTR_007\t测试文本", strings)
        self.assertIn("来源\t行号\tTRIGSTR\t文本\t上下文", refs)
        self.assertIn("war3map.j\t1\tTRIGSTR_007\t测试文本", refs)
        self.assertIn("war3map.j\t2\tTRIGSTR_888\t", refs)


if __name__ == "__main__":
    unittest.main()
