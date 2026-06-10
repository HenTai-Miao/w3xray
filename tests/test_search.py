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

    # ---- 竖线两侧带空格仍是 OR（用户常这么打）----
    def test_or_with_spaces_around_bar(self):
        # "敏捷 | 全属性" 应是 (敏捷 或 全属性)，而不是 敏捷 且 全属性
        self.assertIsNotNone(fuzzy_score("敏捷 | 全属性", "全属性指环"))
        self.assertIsNotNone(fuzzy_score("敏捷 | 全属性", "敏捷之靴"))

    def test_and_with_spaced_or_group(self):
        # "等级C 敏捷 | 全属性" = 含"等级C" 且 (含"敏捷"或"全属性")
        self.assertIsNotNone(fuzzy_score("等级C 敏捷 | 全属性", "等级C全属性指环"))
        self.assertIsNotNone(fuzzy_score("等级C 敏捷 | 全属性", "等级C敏捷之靴"))
        # 没有"等级C"的不该命中
        self.assertIsNone(fuzzy_score("等级C 敏捷 | 全属性", "等级A敏捷之靴"))

    # ---- 中文关键词只认子串，不退化成分散子序列（避免误命中）----
    def test_cjk_term_no_subsequence_falsepositive(self):
        # "全属性"散落成 全(全村)…属…性(攻击属性)，不该命中
        txt = "全村最好的剑 说明:攻击属性大幅提升 等级要求:10".lower()
        self.assertIsNone(fuzzy_score("全属性", txt))
        # "等级:e"散落成 等级(等级要求)…:…e(blp路径)，不该命中
        txt2 = "全村最好的剑 等级要求:10 war3mapimported.blp".lower()
        self.assertIsNone(fuzzy_score("等级:e", txt2))

    def test_cjk_substring_still_hits(self):
        txt = "e级蓝宝石 等级:e 敏捷+ 1 全属性+ 5".lower()
        self.assertIsNotNone(fuzzy_score("敏捷", txt))
        self.assertIsNotNone(fuzzy_score("全属性", txt))
        self.assertIsNotNone(fuzzy_score("等级:e", txt))

    def test_real_query_filters_unrelated_item(self):
        # 用户真实输入：(敏捷 或 全属性) 且 等级:E
        q = "敏捷 | 全属性 等级:E".lower()
        hit = "e级蓝宝石 等级:e 敏捷+ 1 智力+ 5".lower()
        miss = "全村最好的剑 说明:攻击属性大幅提升 等级要求:10 war3mapimported.blp".lower()
        self.assertIsNotNone(fuzzy_score(q, hit))
        self.assertIsNone(fuzzy_score(q, miss))

    # ---- 引号 = 精准（原样连续子串）----
    def test_quoted_term_requires_exact_substring(self):
        # 精准词必须原样连续出现
        self.assertIsNotNone(fuzzy_score('"等级:e"', "x 等级:e y"))
        # 同样的字散落但不连续 → 精准词不命中
        self.assertIsNone(fuzzy_score('"等级:e"', "等级要求:10 blp e"))

    def test_quoted_keeps_spaces_and_bar_literal(self):
        # 引号内的空格不当 AND，竖线不当 OR，整串原样匹配
        self.assertIsNotNone(fuzzy_score('"敏捷 全属性"', "戒指 敏捷 全属性 套装"))
        self.assertIsNone(fuzzy_score('"敏捷 全属性"', "敏捷之靴 全属性指环"))  # 不连续
        self.assertIsNotNone(fuzzy_score('"剑|法杖"', "神器 剑|法杖 合成"))

    def test_quoted_ascii_disables_subsequence(self):
        # 不加引号 ASCII 走子序列；加引号必须连续
        self.assertIsNotNone(fuzzy_score("fb", "foobar"))
        self.assertIsNone(fuzzy_score('"fb"', "foobar"))
        self.assertIsNotNone(fuzzy_score('"fb"', "a fb c"))

    # ---- 精准词以 ASCII 字母/数字结尾时，不可粘进更长的词 ----
    def test_quoted_ascii_tail_respects_word_boundary(self):
        # 幽罗世界物品等级：E / EX 是两档。精准"等级:E"不该命中"等级:EX"
        self.assertIsNotNone(fuzzy_score('"等级:E"', "全村最好的剑 等级:E 攻击力+ 50"))
        self.assertIsNone(fuzzy_score('"等级:E"', "天地圣枪 等级:EX 增加攻击"))
        # 行内（换行分隔）同样成立
        self.assertIsNotNone(fuzzy_score('"等级:E"', "武器\n等级:E\n敏捷+ 10"))
        self.assertIsNone(fuzzy_score('"等级:E"', "武器\n等级:EX\n敏捷+ 10"))
        # 文本里同时有 EX 和 E，应跳过 EX 命中真正的 E
        self.assertIsNotNone(fuzzy_score('"等级:E"', "套装 等级:EX 升级后 等级:E"))

    def test_quoted_ascii_head_respects_word_boundary(self):
        # 前缘同理：以 ASCII 字母/数字开头的精准词，不可从词中切入
        self.assertIsNone(fuzzy_score('"06Y"', "item I06Y gem"))
        self.assertIsNotNone(fuzzy_score('"I06Y"', "item I06Y gem"))

    def test_quoted_full_grade_real_query(self):
        # 用户真实输入：(敏捷 或 全属性) 且 精准 等级:E —— EX 物品不该混进来
        q = '"敏捷" | "全属性" "等级:E"'
        e_item = "全村最好的剑 武器\n等级:E\n攻击力+ 50\n敏捷+ 10"
        ex_item = "残月之追星云霄弓 武器\n等级:EX\n增加攻击\n增加敏捷"
        self.assertIsNotNone(fuzzy_score(q, e_item))
        self.assertIsNone(fuzzy_score(q, ex_item))

    def test_quoted_plus_grade_respects_boundary(self):
        # S 与 S+ 是两档：加号也算"粘连字符"，精准"等级:S"不该命中"等级:S+"
        self.assertIsNotNone(fuzzy_score('"等级:S"', "苍穹剑 等级:S 增加攻击"))
        self.assertIsNone(fuzzy_score('"等级:S"', "忍冬剑 等级:S+ 增加攻击"))
        # 行内同样成立
        self.assertIsNotNone(fuzzy_score('"等级:S"', "武器\n等级:S\n力量+ 10"))
        self.assertIsNone(fuzzy_score('"等级:S"', "武器\n等级:S+\n力量+ 10"))
        # 想要 S+ 档就带上加号，依然能命中
        self.assertIsNotNone(fuzzy_score('"等级:S+"', "忍冬剑 等级:S+ 增加攻击"))
        # 同时含 S+ 与 S，应跳过 S+ 命中真正的 S
        self.assertIsNotNone(fuzzy_score('"等级:S"', "套装 等级:S+ 降级后 等级:S"))

    def test_mix_fuzzy_and_exact_in_one_query(self):
        # 同一行混用：模糊"蓝宝石" 且 精准"等级:e"
        q = '蓝宝石 "等级:e"'.lower()
        self.assertIsNotNone(fuzzy_score(q, "e级蓝宝石 等级:e 敏捷+ 1"))
        self.assertIsNone(fuzzy_score(q, "e级蓝宝石 等级:a 敏捷+ 1"))   # 等级不对
        self.assertIsNone(fuzzy_score(q, "天地圣枪 等级:e"))           # 不是蓝宝石

    def test_fullwidth_quotes_treated_as_quotes(self):
        self.assertIsNotNone(fuzzy_score('“等级:e”', "x 等级:e y"))

    def test_unclosed_quote_does_not_crash(self):
        # 边打边搜：引号还没闭合也能正常匹配（按精准词处理到行尾）
        self.assertIsNotNone(fuzzy_score('"等级:e', "x 等级:e y"))

    # ---- 大小写：模糊不分大小写，精准区分大小写 ----
    def test_fuzzy_is_case_insensitive(self):
        self.assertIsNotNone(fuzzy_score("ABC", "xx abc xx"))
        self.assertIsNotNone(fuzzy_score("abc", "XX ABC XX"))
        self.assertIsNotNone(fuzzy_score("FB", "foobar"))   # ASCII 子序列也不分大小写

    def test_exact_is_case_sensitive(self):
        # 精准词区分大小写：大小写不一致不命中
        self.assertIsNone(fuzzy_score('"I06Y"', "item i06y gem"))
        self.assertIsNotNone(fuzzy_score('"I06Y"', "item I06Y gem"))
        self.assertIsNone(fuzzy_score('"abc"', "XXABCXX"))


if __name__ == "__main__":
    unittest.main()
