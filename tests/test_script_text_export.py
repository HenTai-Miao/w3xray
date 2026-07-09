"""Readable script text exports with TRIGSTR placeholders resolved."""

import unittest

from w3xtool.api import MapData
from w3xtool.script_text_export import build_readable_script_exports


class ScriptTextExportTest(unittest.TestCase):
    def test_readable_exports_replace_quoted_trigstr_strings(self):
        # Given: scripts with WTS-backed TRIGSTR literals and one missing reference.
        md = MapData(path="x.w3x", name="文本图")
        md.scripts = {
            "war3map.wts": 'STRING 1\n{\n开始 "游戏"\n第二行\n}\n',
            "war3map.j": (
                'call BJDebugMsg("TRIGSTR_001")\n'
                'call BJDebugMsg("TRIGSTR_999")\n'
            ),
        }

        # When: readable script exports are built.
        exports = build_readable_script_exports(md)

        # Then: the script body is copied with resolved, escaped UI text.
        by_name = {item.name: item.text for item in exports}
        self.assertNotIn("war3map.wts", by_name)
        self.assertIn('call BJDebugMsg("开始 \\"游戏\\"\\n第二行")', by_name["war3map.j"])
        self.assertIn('call BJDebugMsg("TRIGSTR_999")', by_name["war3map.j"])


if __name__ == "__main__":
    unittest.main()
