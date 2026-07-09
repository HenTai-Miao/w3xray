"""脚本机制线索：BJ 隐式对象与运行时默认池。"""

import unittest

from w3xtool.script_mechanics import (
    format_script_mechanism_report,
    scan_script_need_marks,
)


class ScriptMechanicsTest(unittest.TestCase):
    def test_need_marks_report_runtime_default_pools(self) -> None:
        # Given: a script using BJ helpers that select objects from Blizzard runtime pools.
        script = "\n".join((
            "call ChooseRandomItemBJ(3)",
            "call ChooseRandomCreep(5)",
            "call InitNeutralBuildings()",
        ))

        # When: script need marks are scanned.
        marks = scan_script_need_marks(script)
        text = format_script_mechanism_report(script)

        # Then: the report names the mechanism without inventing concrete 4cc IDs.
        labels = {mark.label for mark in marks}
        self.assertIn("随机物品池", labels)
        self.assertIn("随机野怪池", labels)
        self.assertIn("中立建筑初始化", labels)
        self.assertIn("ChooseRandomItemBJ", text)
        self.assertIn("不直接给出固定 4cc", text)


if __name__ == "__main__":
    unittest.main()
