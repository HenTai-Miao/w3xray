"""地图智能审计：把已解析 MapData 转成只读告警/提示。"""
import unittest
from types import SimpleNamespace

from w3xtool.api import GameObject, MapData
from w3xtool.audit import AuditSeverity, build_audit_report


def _obj(category, obj_id, *, custom=True):
    return GameObject(
        category=category,
        ext="w3u",
        obj_id=obj_id,
        base_id=obj_id,
        name=obj_id,
        is_custom=custom,
    )


class AuditReportTest(unittest.TestCase):
    def test_warns_when_map_info_missing(self):
        # Given: a parsed map without war3map.w3i metadata.
        md = MapData(path="x.w3x", name="x")
        md.objects = {"单位": [_obj("单位", "H001")]}

        # When: the audit report is built.
        report = build_audit_report(md)

        # Then: the missing map-info condition is surfaced as a warning.
        item = report.by_code["map_info.missing"]
        self.assertEqual(item.severity, AuditSeverity.WARNING)
        self.assertIn("war3map.w3i", item.detail)

    def test_warns_when_reference_coverage_is_low(self):
        # Given: the reference graph already detected low coverage.
        md = MapData(path="x.w3x", name="x")
        md.w3i = SimpleNamespace(version=25)
        md.ref_low_coverage = True

        # When: the audit report is built.
        report = build_audit_report(md)

        # Then: the report explains that orphan results are less reliable.
        item = report.by_code["reference.low_coverage"]
        self.assertEqual(item.severity, AuditSeverity.WARNING)
        self.assertIn("孤立", item.detail)

    def test_warns_when_category_orphan_ratio_is_high(self):
        # Given: most custom abilities are unreferenced.
        objs = [_obj("技能", f"A{i:03d}") for i in range(12)]
        md = MapData(path="x.w3x", name="x")
        md.w3i = SimpleNamespace(version=25)
        md.objects = {"技能": objs}
        md.orphans = objs[:9]

        # When: the audit report is built.
        report = build_audit_report(md)

        # Then: the high orphan ratio is called out by category.
        item = report.by_code["orphan.high_ratio.技能"]
        self.assertEqual(item.severity, AuditSeverity.WARNING)
        self.assertIn("9/12", item.detail)

    def test_reports_inventory_when_map_has_data(self):
        # Given: a map with metadata, objects, script, and file names.
        md = MapData(path="x.w3x", name="x")
        md.w3i = SimpleNamespace(version=25)
        md.objects = {
            "单位": [_obj("单位", "H001"), _obj("单位", "hpea", custom=False)],
            "技能": [_obj("技能", "A001")],
        }
        md.scripts = {"war3map.j": "function main takes nothing returns nothing\nendfunction"}
        md.all_files = ["war3map.w3i", "war3map.j", "war3map.w3u"]

        # When: the audit report is built.
        report = build_audit_report(md)

        # Then: informational inventory lines remain available for CLI/GUI display.
        self.assertIn("inventory.objects", report.by_code)
        self.assertIn("script.primary", report.by_code)
        self.assertIn("3 个对象", report.by_code["inventory.objects"].detail)

    def test_summarizes_resource_and_compat_risks(self):
        # Given: a map with an unreferenced asset and Lua/newer-format risks.
        md = MapData(path="x.w3x", name="x")
        md.w3i = SimpleNamespace(version=28, script_type="Lua", large_map=False)
        md.scripts = {"war3map.lua": "print('x')"}
        md.all_files = ["war3mapImported\\unused.blp"]

        # When: the audit report is built.
        report = build_audit_report(md)

        # Then: A/B/C risks are available in one audit surface.
        self.assertEqual(report.by_code["resources.unreferenced"].severity, AuditSeverity.WARNING)
        self.assertEqual(report.by_code["compat.warnings"].severity, AuditSeverity.WARNING)

    def test_summarizes_order_collisions(self):
        # Given: duplicated object order strings.
        md = MapData(path="x.w3x", name="x")
        md.objects = {
            "技能": [
                GameObject(
                    category="技能",
                    ext="w3a",
                    obj_id="A001",
                    base_id="A001",
                    name="火球",
                    is_custom=True,
                    fields=[("命令串 - 使用/打开", "channel")],
                ),
                GameObject(
                    category="技能",
                    ext="w3a",
                    obj_id="A002",
                    base_id="A002",
                    name="冰箭",
                    is_custom=True,
                    fields=[("命令串 - 使用/打开", "channel")],
                ),
            ]
        }

        # When: the audit report is built.
        report = build_audit_report(md)

        # Then: the order collision is surfaced as a warning.
        self.assertEqual(report.by_code["orders.collisions"].severity, AuditSeverity.WARNING)

    def test_summarizes_script_diagnostics(self):
        # Given: a script with a local-player risk.
        md = MapData(path="x.w3x", name="x")
        md.scripts = {"war3map.j": "if GetLocalPlayer() == Player(0) then\nendif"}

        # When: the audit report is built.
        report = build_audit_report(md)

        # Then: script diagnostics are summarized.
        self.assertEqual(report.by_code["script.diagnostics"].severity, AuditSeverity.WARNING)

    def test_summarizes_crash_risks(self):
        # Given: an object contains a known crash-prone Chain Lightning setup.
        md = MapData(path="x.w3x", name="x")
        md.objects = {
            "技能": [
                GameObject(
                    category="技能",
                    ext="w3a",
                    obj_id="A001",
                    base_id="AOcl",
                    name="闪电链",
                    is_custom=True,
                    fields=[("每个目标伤害减少", "-1.00")],
                )
            ]
        }

        # When: the audit report is built.
        report = build_audit_report(md)

        # Then: crash risks are summarized in the main audit surface.
        self.assertEqual(report.by_code["crash.risks"].severity, AuditSeverity.WARNING)

    def test_summarizes_cheat_residue(self):
        # Given: a script registers an official cheat phrase as a chat command.
        md = MapData(path="x.w3x", name="x")
        md.scripts = {
            "war3map.j": (
                'call TriggerRegisterPlayerChatEvent(gg_trg_Debug, Player(0), "iseedeadpeople", true)'
            )
        }

        # When: the audit report is built.
        report = build_audit_report(md)

        # Then: cheat/debug residue is summarized.
        self.assertEqual(report.by_code["cheats.residue"].severity, AuditSeverity.WARNING)

    def test_reports_custom_gameplay_constants_file(self):
        # Given: a map includes gameplay constants overrides.
        md = MapData(path="x.w3x", name="x")
        md.all_files = ["war3mapMisc.txt"]

        # When: the audit report is built.
        report = build_audit_report(md)

        # Then: the constants file is called out explicitly.
        item = report.by_code["gameplay.constants"]
        self.assertEqual(item.severity, AuditSeverity.INFO)
        self.assertIn("war3mapMisc.txt", item.detail)


if __name__ == "__main__":
    unittest.main()
