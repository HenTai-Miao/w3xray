"""控制命令 / Order 分析：检测技能命令串与脚本命令引用。"""
import unittest

from w3xtool.api import GameObject, MapData
from w3xtool.order_ids import ORDER_ID_NAMES
from w3xtool.orders import build_order_report


def _ability(obj_id, name, order):
    return GameObject(
        category="技能",
        ext="w3a",
        obj_id=obj_id,
        base_id=obj_id,
        name=name,
        is_custom=True,
        fields=[("命令串 - 使用/打开", order)],
    )


class OrderReportTest(unittest.TestCase):
    def test_object_order_fields_are_collected(self):
        # Given: an ability with an order-string field.
        md = MapData(path="x.w3x", name="x")
        md.objects = {"技能": [_ability("A001", "火球", "channel")]}

        # When: the order report is built.
        report = build_order_report(md)

        # Then: the order is indexed by normalized command string.
        self.assertIn("channel", report.by_order)
        self.assertEqual(report.by_order["channel"][0].source, "对象 A001")

    def test_duplicate_object_orders_are_reported_as_collision(self):
        # Given: two custom abilities reuse the same order string.
        md = MapData(path="x.w3x", name="x")
        md.objects = {
            "技能": [
                _ability("A001", "火球", "channel"),
                _ability("A002", "冰箭", "channel"),
            ]
        }

        # When: the order report is built.
        report = build_order_report(md)

        # Then: the duplicated order string is reported as a collision.
        self.assertEqual(len(report.collisions), 1)
        self.assertEqual(report.collisions[0].order, "channel")

    def test_script_issue_order_strings_are_collected(self):
        # Given: script code issues an order by string.
        md = MapData(path="x.w3x", name="x")
        md.scripts = {"war3map.j": 'call IssueImmediateOrder(u, "stop")'}

        # When: the order report is built.
        report = build_order_report(md)

        # Then: the script order is listed without creating a collision.
        self.assertIn("stop", report.by_order)
        self.assertEqual(report.by_order["stop"][0].source, "脚本 war3map.j")
        self.assertEqual(report.collisions, ())

    def test_script_issue_order_by_id_is_mapped(self):
        # Given: script code issues a known numeric order id.
        md = MapData(path="x.w3x", name="x")
        md.scripts = {"war3map.j": "call IssueImmediateOrderById(u, 851972)"}

        # When: the order report is built.
        report = build_order_report(md)

        # Then: the id is mapped to the canonical order string.
        uses = report.by_order["stop"]
        self.assertEqual(uses[0].detail, "IssueOrderById 851972")

    def test_script_issue_order_by_id_uses_complete_public_order_table(self):
        # Given: script code issues less-common numeric order ids.
        md = MapData(path="x.w3x", name="x")
        md.scripts = {
            "war3map.j": (
                "call IssueImmediateOrderById(u, 851990)\n"
                "call IssueImmediateOrderById(u, 851993)\n"
                "call IssueImmediateOrderById(u, 852600)\n"
            )
        }

        # When: the order report is built.
        report = build_order_report(md)

        # Then: ids are mapped to canonical order names, including the
        # corrected patrol/hold-position values and the Channel order.
        self.assertIn("patrol", report.by_order)
        self.assertIn("holdposition", report.by_order)
        self.assertIn("channel", report.by_order)

    def test_order_id_table_covers_public_command_id_catalog(self):
        # Given: the bundled order-id table.
        # When: its coverage is inspected.
        count = len(ORDER_ID_NAMES)

        # Then: it covers the public catalog rather than a handful of ids.
        self.assertGreaterEqual(count, 360)
        self.assertEqual(ORDER_ID_NAMES["851990"], "patrol")
        self.assertEqual(ORDER_ID_NAMES["851993"], "holdposition")
        self.assertEqual(ORDER_ID_NAMES["852600"], "channel")

    def test_unknown_script_order_id_is_preserved(self):
        # Given: script code issues an unknown numeric order id.
        md = MapData(path="x.w3x", name="x")
        md.scripts = {"war3map.j": "call IssuePointOrderById(u, 859999, 0, 0)"}

        # When: the order report is built.
        report = build_order_report(md)

        # Then: the numeric id remains visible for manual lookup.
        self.assertIn("id:859999", report.by_order)


if __name__ == "__main__":
    unittest.main()
