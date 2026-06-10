"""搜索打分：SQL 风格查询语法。

- `%x%` 包含 / `x%` 前缀 / `%x` 后缀 / `a%b` 中间通配：`%` 是通配符，**不分大小写**。
  裸词（不含 `%`）按 `%词%`（包含）处理。SQL `LIKE` 语义，**不做子序列**匹配。
- `="x"` 精准：必须原样连续出现，**区分大小写**，ASCII 端点按词边界
  （`="等级:E"` 不会命中 `等级:EX`）；引号内一切字符（空格/`&`/`|`/`%`）都当字面量。
- `&&` 且、`||` 或、`( )` 分组；`&&` 优先级高于 `||`；相邻词缺运算符时默认 `&&`。
- 反斜杠转义：`\\%` `\\&` `\\|` `\\(` `\\)` `\\\\` 表示对应字面量。

例：`(%敏捷% || %全属性%) && ="等级:E"`
  → （包含「敏捷」或「全属性」）且 精准「等级:E」。
命中返回累加分数（越靠前/越贴边分越高），未命中返回 None；空查询返回 0。

解析为 AST：词法(_lex) → 递归下降(_Parser) → 求分(_eval)。
节点：('like', segs, anchored_start, anchored_end) | ('eq', needle)
      | ('and', lhs, rhs) | ('or', lhs, rhs)
"""
from __future__ import annotations


def _is_word_char(ch: str) -> bool:
    """词内字符：ASCII 字母/数字，外加 '+'（物品等级档 S 与 S+ 是两档）。

    中文等非 ASCII 不算（每个汉字自成单位，精准词允许 全属→全属性 这类紧邻匹配；
    词边界只约束 ASCII 串）。"""
    return ch == "+" or (ch.isascii() and ch.isalnum())


def _eq_score(query: str, text: str):
    """精准（=）：原样连续子串，ASCII 端点不可粘进更长的词。区分大小写。

    若精准词以词内字符结尾，则其后一字符不能也是词内字符——否则把 `等级:E`
    误命中 `等级:EX`；开头同理。中文端点不设边界（保持 全属→全属性 可命中）。
    命中返回分数（越靠前分越高），否则 None。"""
    if not query:
        return 0
    head_word = _is_word_char(query[0])
    tail_word = _is_word_char(query[-1])
    start = 0
    while True:
        idx = text.find(query, start)
        if idx < 0:
            return None
        left_ok = not (head_word and idx > 0 and _is_word_char(text[idx - 1]))
        end = idx + len(query)
        right_ok = not (tail_word and end < len(text) and _is_word_char(text[end]))
        if left_ok and right_ok:
            return 1000 - idx
        start = idx + 1            # 这处粘进了更长的词，找下一处


def _like_score(segs, anchored_start: bool, anchored_end: bool, text: str):
    """LIKE（%）：segs 是被 % 切开的字面段（均已小写），text 已小写。

    anchored_start/end：模式两端是否**无** %（无 % 即需贴边）。各段须按序出现；
    首段贴开头、末段贴结尾（若锚定）。命中返回分数（首段越靠前越高），否则 None。
    segs 为空（如纯 `%`）表示匹配一切。"""
    if not segs:
        return 1000
    n = len(segs)
    pos = 0
    first_idx = 0
    for i, seg in enumerate(segs):
        last = i == n - 1
        if i == 0 and anchored_start:
            if not text.startswith(seg):       # 首段须贴开头
                return None
            idx = 0
        elif last and anchored_end:
            tail = len(text) - len(seg)         # 末段须贴结尾，且在游标之后
            if tail < pos or not text.endswith(seg):
                return None
            idx = tail
        else:
            idx = text.find(seg, pos)
            if idx < 0:
                return None
        if i == 0:
            first_idx = idx
        pos = idx + len(seg)
    if anchored_end and pos != len(text):       # 单段同时首尾锚定（全等）兜底
        return None
    return 1000 - first_idx


# 全角标点 → 半角（引号/竖线/括号）。一次 translate 取代多次 replace。
_NORMALIZE = str.maketrans({"“": '"', "”": '"', "｜": "|", "（": "(", "）": ")"})


# ---- 词法：把查询切成 token 流 ----
# token: ('and',) ('or',) ('lp',) ('rp',)
#        ('like', segs, anchored_start, anchored_end) ('eq', needle)
def _lex(query: str):
    query = query.translate(_NORMALIZE)
    toks = []
    i, n = 0, len(query)
    while i < n:
        ch = query[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "(":
            toks.append(("lp",)); i += 1; continue
        if ch == ")":
            toks.append(("rp",)); i += 1; continue
        if ch == "&" and i + 1 < n and query[i + 1] == "&":
            toks.append(("and",)); i += 2; continue
        if ch == "|" and i + 1 < n and query[i + 1] == "|":
            toks.append(("or",)); i += 2; continue
        if ch == "=" and i + 1 < n and query[i + 1] == '"':
            j = i + 2
            buf = []
            while j < n and query[j] != '"':       # 引号内一切字面量
                buf.append(query[j]); j += 1
            if j < n:                                # 跳过闭合引号（未闭合则到行尾）
                j += 1
            toks.append(("eq", "".join(buf)))
            i = j
            continue
        # 否则是一个 LIKE 词，读到下一个边界为止
        parts = []          # 元素: ('pct',) 通配符 | ('lit', ch) 字面量
        has_pct = False
        while i < n:
            c = query[i]
            if c.isspace() or c in "()":
                break
            if c == "&" and i + 1 < n and query[i + 1] == "&":
                break
            if c == "|" and i + 1 < n and query[i + 1] == "|":
                break
            if c == "=" and i + 1 < n and query[i + 1] == '"':
                break
            if c == "\\" and i + 1 < n:              # 转义：下一个字符取字面量
                parts.append(("lit", query[i + 1])); i += 2; continue
            if c == "%":
                parts.append(("pct",)); has_pct = True; i += 1; continue
            parts.append(("lit", c)); i += 1
        if not has_pct:
            needle = "".join(p[1] for p in parts)
            if needle:                               # 裸词 → %词%（包含）
                toks.append(("like", [needle.lower()], False, False))
            continue
        # 含 %：按 % 切成字面段
        segs, cur = [], []
        for p in parts:
            if p[0] == "pct":
                if cur:
                    segs.append("".join(cur).lower()); cur = []
            else:
                cur.append(p[1])
        if cur:
            segs.append("".join(cur).lower())
        anchored_start = parts[0][0] != "pct"
        anchored_end = parts[-1][0] != "pct"
        toks.append(("like", segs, anchored_start, anchored_end))
    return toks


# ---- 递归下降：or := and ('||' and)* ; and := atom ('&&'? atom)* ; atom := '(' or ')' | leaf ----
# AND/OR 节点用**扁平 n 元**列表 ('and', [kids]) / ('or', [kids])，而非左偏二叉树，
# 这样 _eval 对超长 `a && a && …` 链只迭代不递归（递归深度仅随括号嵌套增长）。
# 括号嵌套设上限 _MAX_DEPTH：超限即忽略多余括号，保证递归深度有界（防 RecursionError）。
class _Parser:
    _MAX_DEPTH = 100

    def __init__(self, toks):
        self.toks = toks
        self.i = 0
        self.depth = 0

    def _peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def _next(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    @staticmethod
    def _wrap(tag, kids):
        if not kids:
            return None
        if len(kids) == 1:
            return kids[0]
        return (tag, kids)

    def parse_or(self):
        kids = []
        first = self.parse_and()
        if first is not None:
            kids.append(first)
        while True:
            t = self._peek()
            if t is None or t[0] != "or":
                break
            self._next()
            nxt = self.parse_and()
            if nxt is not None:
                kids.append(nxt)
        return self._wrap("or", kids)

    def parse_and(self):
        kids = []
        first = self.parse_atom()
        if first is not None:
            kids.append(first)
        while True:
            t = self._peek()
            if t is None or t[0] in ("or", "rp"):
                break
            if t[0] == "and":               # 显式 &&；否则相邻词缺运算符 → 隐式 &&
                self._next()
            before = self.i
            nxt = self.parse_atom()
            if nxt is not None:
                kids.append(nxt)
            elif self.i == before:          # 无进展（已到 rp/末尾）→ 收尾，防死循环/越界
                break
        return self._wrap("and", kids)

    def parse_atom(self):
        # 迭代跳过游离运算符（不递归），避免长运算符链撑爆栈
        while True:
            t = self._peek()
            if t is None or t[0] == "rp":
                return None
            if t[0] == "lp":
                self._next()
                if self.depth >= self._MAX_DEPTH:
                    continue                # 嵌套超限：忽略此括号，继续在当前层扫描
                self.depth += 1
                node = self.parse_or()
                self.depth -= 1
                nxt = self._peek()
                if nxt and nxt[0] == "rp":
                    self._next()
                return node
            if t[0] in ("like", "eq"):
                self._next()
                return t
            self._next()                    # 游离的 && / ||：跳过，循环继续


def _eval(node, text: str, text_lower: str):
    if node is None:
        return 0
    tag = node[0]
    if tag == "like":
        return _like_score(node[1], node[2], node[3], text_lower)
    if tag == "eq":
        return _eq_score(node[1], text)                # 区分大小写：用原文
    if tag == "and":
        total = 0
        for child in node[1]:
            s = _eval(child, text, text_lower)
            if s is None:
                return None
            total += s
        return total
    if tag == "or":
        best = None
        for child in node[1]:
            s = _eval(child, text, text_lower)
            if s is not None and (best is None or s > best):
                best = s
        return best
    return None


class CompiledQuery:
    """预编译好的查询：词法+解析只做一次，之后对每条文本调用 score() 复用 AST。

    GUI 每次按键要对**成千上万**个对象打分；若每个对象都重新 _lex+解析同一条
    查询，纯属浪费。先 compile_query() 一次，再对每条文本 .score()，省掉 N-1 次解析。
    空查询用 _empty 标记，score() 恒返回 0（与 fuzzy_score 的空查询语义一致）。"""

    __slots__ = ("_node", "_empty")

    def __init__(self, node, empty: bool):
        self._node = node
        self._empty = empty

    def score(self, text: str):
        """命中返回累加分数，未命中返回 None，空查询返回 0。"""
        if self._empty:
            return 0
        return _eval(self._node, text, text.lower())


def compile_query(query: str) -> CompiledQuery:
    """把查询编译成可复用的 CompiledQuery（词法+解析一次完成）。"""
    if not query or not query.strip():
        return CompiledQuery(None, True)
    toks = _lex(query)
    if not toks:
        return CompiledQuery(None, True)
    node = _Parser(toks).parse_or()
    if node is None:
        return CompiledQuery(None, True)
    return CompiledQuery(node, False)


def fuzzy_score(query: str, text: str):
    """SQL 风格多关键词搜索（一次性接口）。命中返回累加分数，未命中 None，空查询 0。

    内部即 compile_query(query).score(text)。批量打分（同一查询、多条文本）请改用
    compile_query() 编译一次再循环 .score()，避免重复解析。

    传入原始大小写的 query 与 text：LIKE 不分大小写（双方转小写比较），
    引号精准词区分大小写（原样比较）。"""
    return compile_query(query).score(text)
