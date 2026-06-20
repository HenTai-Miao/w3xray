"""版本兼容报告：面向 1.24E 的只读风险提示。"""
import unittest
from types import SimpleNamespace

from w3xtool.api import MapData
from w3xtool.compat import CompatSeverity, build_compat_report


def _w3i(version=25, script_type="JASS", large_map=False):
    return SimpleNamespace(version=version, script_type=script_type, large_map=large_map)


class CompatReportTest(unittest.TestCase):
    def test_lua_map_warns_for_124e(self):
        # Given: a Lua map.
        md = MapData(path="x.w3x", name="x")
        md.w3i = _w3i(version=28, script_type="Lua")
        md.scripts = {"war3map.lua": "print('x')"}

        # When: compatibility report is built for 1.24E.
        report = build_compat_report(md)

        # Then: Lua is reported as incompatible with the classic target.
        item = report.by_code["script.lua"]
        self.assertEqual(item.severity, CompatSeverity.WARNING)
        self.assertIn("1.24E", item.detail)

    def test_reforged_w3i_version_warns_for_124e(self):
        # Given: a 1.31/1.32 style map info version.
        md = MapData(path="x.w3x", name="x")
        md.w3i = _w3i(version=31, script_type="JASS")

        # When: compatibility report is built.
        report = build_compat_report(md)

        # Then: the newer w3i format is flagged.
        self.assertEqual(report.by_code["w3i.newer_format"].severity, CompatSeverity.WARNING)

    def test_large_map_flag_warns_for_classic_target(self):
        # Given: map info marks the map as large.
        md = MapData(path="x.w3x", name="x")
        md.w3i = _w3i(version=25, script_type="JASS", large_map=True)

        # When: compatibility report is built.
        report = build_compat_report(md)

        # Then: classic compatibility receives a large-map warning.
        self.assertIn("map.large", report.by_code)

    def test_plain_v25_jass_reports_compatible(self):
        # Given: a normal TFT JASS map.
        md = MapData(path="x.w3x", name="x")
        md.w3i = _w3i(version=25, script_type="JASS")
        md.scripts = {"war3map.j": "function main takes nothing returns nothing\nendfunction"}

        # When: compatibility report is built.
        report = build_compat_report(md)

        # Then: no warning is emitted and an info summary remains.
        self.assertEqual(report.warnings, ())
        self.assertIn("target.summary", report.by_code)

    def test_return_bug_handle_to_integer_cast_warns_for_124e(self):
        # Given: an old 1.20-style H2I helper that relies on the JASS return bug.
        md = MapData(path="x.w3x", name="x")
        md.w3i = _w3i(version=25, script_type="JASS")
        md.scripts = {
            "war3map.j": (
                "function H2I takes handle h returns integer\n"
                "    return h\n"
                "    return 0\n"
                "endfunction\n"
            )
        }

        # When: compatibility report is built for 1.24E.
        report = build_compat_report(md)

        # Then: the return-bug cast is reported as a compatibility risk.
        item = report.by_code["script.return_bug"]
        self.assertEqual(item.severity, CompatSeverity.WARNING)
        self.assertIn("H2I", item.detail)

    def test_return_bug_integer_to_handle_cast_warns_for_124e(self):
        # Given: an old helper that casts integer back to a handle-derived type.
        md = MapData(path="x.w3x", name="x")
        md.w3i = _w3i(version=25, script_type="JASS")
        md.scripts = {
            "war3map.j": (
                "function I2U takes integer i returns unit\n"
                "    return i\n"
                "    return null\n"
                "endfunction\n"
            )
        }

        # When: compatibility report is built for 1.24E.
        report = build_compat_report(md)

        # Then: the unsafe cast is reported.
        self.assertIn("script.return_bug", report.by_code)


if __name__ == "__main__":
    unittest.main()
