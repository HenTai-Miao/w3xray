"""对象浏览筛选的后台计算层测试。"""
import unittest

from w3xtool.api import GameObject, MapData
from w3xtool.object_filter import filter_objects_by_query


class TestObjectFilter(unittest.TestCase):
    def test_filters_each_category_when_query_matches_names(self):
        # Given: a map has objects in multiple categories.
        md = MapData(
            path="x.w3x",
            name="筛选测试图",
            objects={
                "物品": [
                    GameObject("物品", "w3t", "I001", "I001", "火焰剑", True),
                    GameObject("物品", "w3t", "I002", "I002", "普通剑", True),
                    GameObject("物品", "w3t", "I003", "I003", "火焰护符", True),
                ],
                "单位": [
                    GameObject("单位", "w3u", "H001", "H001", "火焰法师", True),
                ],
            },
        )

        # When: filtering with a query that only matches some object names.
        result = filter_objects_by_query(md, "火焰")

        # Then: each category gets an independent filtered list.
        self.assertEqual(
            [obj.name for obj in result.results_by_category["物品"]],
            ["火焰剑", "火焰护符"],
        )
        self.assertEqual(
            [obj.name for obj in result.results_by_category["单位"]],
            ["火焰法师"],
        )
        self.assertIn("物品2", result.summary)
        self.assertIn("单位1", result.summary)

    def test_returns_all_parallel_categories_when_query_is_empty(self):
        # Given: a map only has one populated category.
        md = MapData(
            path="x.w3x",
            name="全分类测试图",
            objects={
                "物品": [GameObject("物品", "w3t", "I001", "I001", "木头", True)],
                "可破坏物": [
                    GameObject("可破坏物", "w3b", "D001", "D001", "树木", True),
                ],
            },
        )

        # When: the user has not entered a query.
        result = filter_objects_by_query(md, "")

        # Then: missing categories are represented as empty lists for the GUI.
        self.assertEqual([obj.name for obj in result.results_by_category["物品"]], ["木头"])
        self.assertEqual([obj.name for obj in result.results_by_category["可破坏物"]], ["树木"])
        self.assertEqual(result.results_by_category["技能"], [])
        self.assertEqual(result.results_by_category["装饰物"], [])
        self.assertEqual(result.results_by_category["增益"], [])
        self.assertIn("可破坏物1", result.summary)
        self.assertIn("技能0", result.summary)


if __name__ == "__main__":
    unittest.main()
