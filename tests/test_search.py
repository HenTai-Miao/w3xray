"""搜索打分测试（SQL 风格语法）。

语法：%x%=包含、x%=前缀、%x=后缀（% 为通配符，不分大小写）；
="x"=精准（区分大小写、连续子串、ASCII 词边界）；
&& 且、|| 或、() 分组，&& 优先于 ||；相邻词默认 &&；
引号内与 \\ 转义后的 % & | ( ) 均为字面量；裸词无 % 时按 %词% 处理。

纯函数 fuzzy_score(query, text) 已从 GUI 抽到 w3xtool.search，可独立测试。
"""
import unittest

from w3xtool.search import compile_query, fuzzy_score


class TestEmptyAndBasic(unittest.TestCase):
    def test_empty_query_scores_zero(self):
        self.assertEqual(fuzzy_score("", "随便什么"), 0)

    def test_whitespace_only_query_scores_zero(self):
        self.assertEqual(fuzzy_score("   ", "随便什么"), 0)


class TestLike(unittest.TestCase):
    def test_contains_hit_and_miss(self):
        self.assertIsNotNone(fuzzy_score("%abc%", "xxabcxx"))
        self.assertIsNone(fuzzy_score("%xyz%", "abc"))

    def test_prefix(self):
        self.assertIsNotNone(fuzzy_score("abc%", "abcdef"))
        self.assertIsNone(fuzzy_score("abc%", "xabcdef"))   # 不以 abc 开头

    def test_suffix(self):
        self.assertIsNotNone(fuzzy_score("%def", "abcdef"))
        self.assertIsNone(fuzzy_score("%def", "abcdefx"))   # 不以 def 结尾

    def test_suffix_picks_trailing_occurrence(self):
        # 文本里 ab 出现两次，%ab 仍应靠结尾命中
        self.assertIsNotNone(fuzzy_score("%ab", "abxab"))
        self.assertIsNone(fuzzy_score("%ab", "abxabx"))

    def test_middle_wildcard(self):
        self.assertIsNotNone(fuzzy_score("a%b", "axxxb"))    # a 开头 b 结尾
        self.assertIsNone(fuzzy_score("a%b", "xayb"))        # 不以 a 开头

    def test_bare_term_is_implicit_contains(self):
        # 裸词不带 % → 等价于 %词%（包含）
        self.assertIsNotNone(fuzzy_score("abc", "xxabcxx"))
        self.assertIsNotNone(fuzzy_score("智力", "高级智力圣剑"))
        self.assertIsNone(fuzzy_score("火球", "高级智力圣剑"))

    def test_like_case_insensitive(self):
        self.assertIsNotNone(fuzzy_score("%ABC%", "xxabcxx"))
        self.assertIsNotNone(fuzzy_score("%abc%", "XXABCXX"))

    def test_like_has_no_ascii_subsequence(self):
        # SQL LIKE 不做子序列：%fb% 不该命中 foobar（与旧模糊不同）
        self.assertIsNone(fuzzy_score("%fb%", "foobar"))
        self.assertIsNotNone(fuzzy_score("%fb%", "a fb c"))

    def test_lone_percent_matches_anything(self):
        self.assertIsNotNone(fuzzy_score("%", "随便什么"))

    def test_earlier_match_scores_higher(self):
        self.assertGreater(fuzzy_score("%abc%", "abcxx"),
                           fuzzy_score("%abc%", "xxabc"))


class TestEq(unittest.TestCase):
    def test_eq_requires_contiguous_substring(self):
        self.assertIsNotNone(fuzzy_score('="等级:E"', "x 等级:E y"))
        self.assertIsNone(fuzzy_score('="等级:E"', "等级要求:10 blp E"))

    def test_eq_keeps_inner_chars_literal(self):
        # 引号内的空格/竖线/&/% 都是普通字符，不当运算符
        self.assertIsNotNone(fuzzy_score('="剑 && 法杖"', "神器 剑 && 法杖 合成"))
        self.assertIsNotNone(fuzzy_score('="攻击+20%"', "宝石 攻击+20% 词条"))

    def test_eq_case_sensitive(self):
        self.assertIsNotNone(fuzzy_score('="ABC"', "x ABC y"))
        self.assertIsNone(fuzzy_score('="ABC"', "x abc y"))

    def test_eq_ascii_tail_word_boundary(self):
        # 幽罗世界等级 E / EX 是两档：="等级:E" 不该命中 等级:EX
        self.assertIsNotNone(fuzzy_score('="等级:E"', "剑 等级:E 攻击+ 50"))
        self.assertIsNone(fuzzy_score('="等级:E"', "枪 等级:EX 增加攻击"))
        self.assertIsNotNone(fuzzy_score('="等级:E"', "套装 等级:EX 升级后 等级:E"))

    def test_eq_ascii_head_word_boundary(self):
        self.assertIsNone(fuzzy_score('="06Y"', "item I06Y gem"))
        self.assertIsNotNone(fuzzy_score('="06Y"', "item 06Y gem"))


class TestAndOr(unittest.TestCase):
    def test_and_both_required(self):
        self.assertIsNotNone(fuzzy_score("%智力% && %圣剑%", "高级智力圣剑"))
        self.assertIsNone(fuzzy_score("%智力% && %火球%", "高级智力圣剑"))

    def test_or_either(self):
        self.assertIsNotNone(fuzzy_score("%剑% || %法杖%", "审判圣剑"))
        self.assertIsNotNone(fuzzy_score("%剑% || %法杖%", "奥术法杖"))
        self.assertIsNone(fuzzy_score("%斧% || %锤%", "审判圣剑"))

    def test_adjacent_terms_default_to_and(self):
        # 相邻词无运算符 → 默认 &&
        self.assertIsNotNone(fuzzy_score("%智力% %圣剑%", "高级智力圣剑"))
        self.assertIsNone(fuzzy_score("%智力% %火球%", "高级智力圣剑"))

    def test_and_binds_tighter_than_or(self):
        # a && b || c == (a && b) || c：只命中 c 也应通过
        q = "%力量% && %巨剑% || %戒指%"
        self.assertIsNotNone(fuzzy_score(q, "敏捷戒指"))          # 命中 c
        self.assertIsNotNone(fuzzy_score(q, "力量巨剑"))          # 命中 a&&b
        self.assertIsNone(fuzzy_score(q, "力量法杖"))             # a 命中但 b 不,且无 c

    def test_or_takes_best_of_branch(self):
        # OR 取较优分支，命中即非 None
        self.assertIsNotNone(fuzzy_score("%敏捷% || %全属性%", "全属性指环"))
        self.assertIsNotNone(fuzzy_score("%敏捷% || %全属性%", "敏捷之靴"))


class TestParens(unittest.TestCase):
    def test_parens_override_precedence(self):
        q = "(%剑% || %法杖%) && %智力%"
        self.assertIsNotNone(fuzzy_score(q, "智力法杖"))
        self.assertIsNotNone(fuzzy_score(q, "智力圣剑"))
        self.assertIsNone(fuzzy_score(q, "力量圣剑"))            # 缺智力
        self.assertIsNone(fuzzy_score(q, "智力指环"))            # 缺剑/法杖

    def test_nested_parens(self):
        q = "%装备% && (%剑% || (%法杖% && %奥术%))"
        self.assertIsNotNone(fuzzy_score(q, "装备 圣剑"))
        self.assertIsNotNone(fuzzy_score(q, "装备 奥术法杖"))
        self.assertIsNone(fuzzy_score(q, "装备 普通法杖"))      # 法杖但非奥术,也无剑

    def test_deep_nested_group_keeps_trailing_condition(self):
        # 深嵌套括号(超过旧 _MAX_DEPTH=100)后的 && 条件不该被静默丢弃
        q = "(" * 200 + "%a%" + ")" * 200 + " && %c%"
        self.assertIsNone(fuzzy_score(q, "a"))        # 缺 c → && %c% 生效则 miss
        self.assertIsNotNone(fuzzy_score(q, "a c"))   # a 与 c 都在 → 命中

    def test_deep_nested_group_keeps_leading_condition(self):
        q = "%c% && " + "(" * 200 + "%a%" + ")" * 200
        self.assertIsNone(fuzzy_score(q, "a"))
        self.assertIsNotNone(fuzzy_score(q, "a c"))


class TestEscape(unittest.TestCase):
    def test_escaped_percent_is_literal(self):
        # \% 表示字面量百分号,不当通配符
        self.assertIsNotNone(fuzzy_score(r"攻击+20\%", "宝石 攻击+20% 词条"))
        self.assertIsNone(fuzzy_score(r"攻击+20\%", "宝石 攻击+20 词条"))

    def test_escaped_parens_are_literal(self):
        self.assertIsNotNone(fuzzy_score(r"\(冷却", "技能 (冷却:5) 秒"))

    def test_escaped_operators_are_literal(self):
        # \&\& 与 \|\| 应作字面量,而非运算符
        self.assertIsNotNone(fuzzy_score(r"a\&\&b", "x a&&b y"))


class TestRealisticQueries(unittest.TestCase):
    def test_filters_unrelated_item(self):
        # (敏捷 或 全属性) 且 精准 等级:E
        q = '(%敏捷% || %全属性%) && ="等级:E"'
        hit = "e级蓝宝石 等级:E 敏捷+ 1 智力+ 5"
        miss = "全村最好的剑 攻击属性大幅提升 等级:EX war3mapimported.blp"
        self.assertIsNotNone(fuzzy_score(q, hit))
        self.assertIsNone(fuzzy_score(q, miss))


class TestRobustnessNoCrash(unittest.TestCase):
    """暴力/边界输入：解析器与求分器都不许崩溃或死循环，返回必为 int 或 None。"""

    def _ok(self, q, t):
        r = fuzzy_score(q, t)
        self.assertTrue(r is None or isinstance(r, int), (repr(q), repr(r)))
        return r

    def test_deeply_nested_parens(self):
        self._ok("(" * 5000 + "%x%" + ")" * 5000, "x")
        self._ok("(" * 20000 + "%x%" + ")" * 20000, "x")

    def test_unbalanced_parens(self):
        self._ok("(" * 5000 + "%x%", "x")
        self._ok("%x%" + ")" * 5000, "x")

    def test_long_lone_operator_chains(self):
        # 大量纯运算符无操作数 → 退化为空查询
        self.assertEqual(fuzzy_score("||" * 5000, "x"), 0)
        self.assertEqual(fuzzy_score("&&" * 5000, "x"), 0)
        self.assertEqual(fuzzy_score("(" * 5000 + ")" * 5000, "x"), 0)

    def test_long_and_chain_of_terms(self):
        self.assertIsNotNone(self._ok(" && ".join(["%x%"] * 5000), "x"))
        self.assertIsNone(self._ok(" && ".join(["%x%"] * 2500 + ["%zzz%"]), "x"))

    def test_long_or_chain_of_terms(self):
        self.assertIsNotNone(self._ok(" || ".join(["%zzz%"] * 4999 + ["%x%"]), "x"))
        self.assertIsNone(self._ok(" || ".join(["%zzz%"] * 5000), "x"))

    def test_huge_text_and_query(self):
        self.assertIsNotNone(self._ok("%needle%", "x" * 1_000_000 + "needle"))
        self._ok("%" + "a" * 100_000 + "%", "a" * 50)

    def test_trailing_and_lone_backslash(self):
        self._ok("%x\\", "x")
        self._ok("\\", "x")

    def test_unclosed_quote_to_eol(self):
        self.assertIsNotNone(fuzzy_score('="' + "a" * 100, "a" * 100))

    def test_random_fuzz_never_crashes(self):
        import random
        rnd = random.Random(0xC0FFEE)
        alph = list('%&|()="\\ 智力剑abAB12:+')
        texts = ["", " ", "智力圣剑 等级:E 攻击+20% (冷却:5)", "a" * 300,
                 "I06Y 等级:EX", "&&||(())", '"q" || %z%']
        for _ in range(20_000):
            q = "".join(rnd.choice(alph) for _ in range(rnd.randint(0, 16)))
            t = rnd.choice(texts)
            r = fuzzy_score(q, t)
            self.assertTrue(r is None or isinstance(r, int), (repr(q), repr(r)))


class TestCompiledQuery(unittest.TestCase):
    """compile_query().score() 必须与一次性 fuzzy_score() 完全等价（只是少解析几次）。"""

    QUERIES = [
        "", "  ", "%剑%", "智力", "剑%", "%法杖", "a%b",
        '="等级:E"', "%智力% && %圣剑%", "%剑% || %法杖%",
        "(%敏捷% || %全属性%) && \"等级:E\"".replace('"', '="', 1),
        r"攻击+20\%", "%ABC%", "%力量% && %巨剑% || %戒指%",
    ]
    TEXTS = [
        "高级智力圣剑 等级:E 攻击+20%", "审判圣剑", "奥术法杖", "敏捷之靴",
        "全属性指环 等级:EX", "ABCDEF", "力量巨剑", "敏捷戒指", "",
    ]

    def test_compiled_matches_fuzzy_score(self):
        for q in self.QUERIES:
            cq = compile_query(q)
            for t in self.TEXTS:
                self.assertEqual(cq.score(t), fuzzy_score(q, t), (repr(q), repr(t)))

    def test_compile_once_reusable_across_texts(self):
        cq = compile_query("%剑% || %法杖%")
        self.assertIsNotNone(cq.score("圣剑"))
        self.assertIsNotNone(cq.score("法杖"))
        self.assertIsNone(cq.score("盾牌"))
        # 复用不改变内部状态：重复打分结果稳定
        self.assertEqual(cq.score("圣剑"), cq.score("圣剑"))


class TestLikeOracle(unittest.TestCase):
    """差分测试：简单字母 needle 的 LIKE 行为必须与 Python 原生子串语义一致。"""

    def test_contains_matches_python_in(self):
        import random
        rnd = random.Random(7)
        for _ in range(8000):
            needle = "".join(rnd.choice("abcd") for _ in range(rnd.randint(1, 4)))
            text = "".join(rnd.choice("abcd") for _ in range(rnd.randint(0, 12)))
            got = fuzzy_score("%" + needle + "%", text) is not None
            self.assertEqual(got, needle in text, (needle, text))

    def test_prefix_suffix_match_startswith_endswith(self):
        import random
        rnd = random.Random(11)
        for _ in range(8000):
            needle = "".join(rnd.choice("abcd") for _ in range(rnd.randint(1, 4)))
            text = "".join(rnd.choice("abcd") for _ in range(rnd.randint(0, 12)))
            self.assertEqual(fuzzy_score(needle + "%", text) is not None,
                             text.startswith(needle), ("prefix", needle, text))
            self.assertEqual(fuzzy_score("%" + needle, text) is not None,
                             text.endswith(needle), ("suffix", needle, text))


if __name__ == "__main__":
    unittest.main()
