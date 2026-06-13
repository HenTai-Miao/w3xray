"""字段标签：手工精选优先、MetaData.slk 全量生成兜底、未知码原样返回。"""
import unittest

from w3xtool.fields import label_for, field_type, FIELD_LABELS


class TestFieldLabels(unittest.TestCase):
    def test_curated_label_takes_precedence(self):
        # "unam" 在精选表里是「名称」，全量表里是「名字」——精选优先
        self.assertEqual(FIELD_LABELS["unam"], "名称")
        self.assertEqual(label_for("unam"), "名称")

    def test_generated_label_fallback(self):
        # 精选表没有的字段码应回退到全量生成标签（不再显示原始 4cc）
        self.assertNotIn("uarm", FIELD_LABELS)
        self.assertEqual(label_for("uarm"), "装甲类型")

    def test_unknown_code_returns_itself(self):
        self.assertEqual(label_for("zzzz"), "zzzz")

    def test_field_type_lookup(self):
        self.assertEqual(field_type("iabi"), "abilityList")
        self.assertEqual(field_type("unam"), "string")
        self.assertEqual(field_type("zzzz"), "")


if __name__ == "__main__":
    unittest.main()
