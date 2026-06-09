"""模糊搜索打分测试：空格=AND，竖线|=OR，子串优先。

把搜索算法从 GUI 抽到 w3xtool.search，纯函数可独立测试。
"""
import unittest

from w3xtool.search import fuzzy_score


class TestFuzzyScore(unittest.TestCase):
    def test_empty_query_scores_zero(self):
        self.assertEqual(fuzzy_score("", "随便什么"), 0)

    def test_substring_hit(self):
        self.assertIsNotNone(fuzzy_score("abc", "xxabcxx"))

    def test_subsequence_hit(self):
        self.assertIsNotNone(fuzzy_score("ac", "a_b_c"))

    def test_no_match_returns_none(self):
        self.assertIsNone(fuzzy_score("xyz", "abc"))

    def test_substring_scores_higher_than_subsequence(self):
        # 连续子串应比分散子序列分高（更靠前）
        self.assertGreater(fuzzy_score("abc", "abc"), fuzzy_score("abc", "a1b2c"))

    # ---- AND（空格分隔，每段都要命中）----
    def test_and_all_terms_present(self):
        self.assertIsNotNone(fuzzy_score("智力 圣剑", "高级智力圣剑"))

    def test_and_one_term_missing(self):
        self.assertIsNone(fuzzy_score("智力 火球", "高级智力圣剑"))

    # ---- OR（竖线分隔，任一命中即可）----
    def test_or_one_alternative_hits(self):
        self.assertIsNotNone(fuzzy_score("剑|法杖", "审判圣剑"))

    def test_or_no_alternative_hits(self):
        self.assertIsNone(fuzzy_score("斧|锤", "审判圣剑"))

    def test_fullwidth_bar_treated_as_or(self):
        self.assertIsNotNone(fuzzy_score("剑｜法杖", "审判圣剑"))

    # ---- AND + OR 组合 ----
    def test_combo_and_with_or_group(self):
        # 含"智力" 且 (含"剑"或"法杖")
        self.assertIsNotNone(fuzzy_score("智力 剑|法杖", "智力法杖"))

    def test_combo_missing_and_term(self):
        self.assertIsNone(fuzzy_score("力量 剑|法杖", "智力法杖"))


if __name__ == "__main__":
    unittest.main()
