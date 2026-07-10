"""文本对象档分类 classify 测试。

依据特征字段 + 代码首字母投票判类型；无单位/技能/科技信号则默认"物品"。
"""
import unittest

from w3xtool.textobj import classify, parse_text_objects


def test_parse_text_objects_and_classify_preserve_current_behavior() -> None:
    # Given: an INI object table with CRLF lines and a duplicate field.
    text = "[hfoo]\r\nName=Footman\r\nName=Ignored\r\nTrains=hbar\r\n"

    # When: the table is parsed and classified from its parsed fields.
    objects = parse_text_objects(text)
    category = classify(
        [code for code, _fields in objects],
        {field for _code, fields in objects for field in fields},
    )

    # Then: parsing keeps the first field value and classification stays unit-based.
    assert objects == [("hfoo", {"Name": "Footman", "Trains": "hbar"})]
    assert category == "单位"


class TestClassify(unittest.TestCase):
    def test_unit_by_field_markers(self):
        self.assertEqual(classify(["x000"], {"Propernames", "Trains"}), "单位")

    def test_ability_by_code_prefix(self):
        self.assertEqual(classify(["A001", "A002", "A003"], {"Name"}), "技能")

    def test_upgrade_by_code_prefix(self):
        self.assertEqual(classify(["R001", "R002"], set()), "科技")

    def test_unit_by_code_prefix(self):
        self.assertEqual(classify(["h001", "h002", "h003"], set()), "单位")

    def test_item_is_default_without_markers(self):
        self.assertEqual(classify(["I001", "I002"], {"Name", "Tip", "Ubertip"}), "物品")


if __name__ == "__main__":
    unittest.main()
