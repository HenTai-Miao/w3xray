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


# ---- 解析：调度场(shunting-yard)算法，纯迭代、用显式栈，无递归 ----
# 文法：or := and ('||' and)* ; and := atom ('&&'? atom)* ; atom := '(' or ')' | leaf
# 运算符优先级 && > ||；相邻操作数缺运算符按隐式 &&。
#
# 为何不用递归下降：括号每嵌一层就多一层 Python 调用栈，深嵌套(如 20000 层)会
# RecursionError。旧实现靠 _MAX_DEPTH 截断递归，但截断时把多出的 '(' 静默吞掉、
# 不配对 ')'，导致后续 token 错位、把深嵌套组之后的查询条件整段丢弃（过滤失效）。
# 改用调度场：解析完全迭代，任意深嵌套都不爆栈，也绝不丢内容。
#
# AND/OR 节点用**扁平 n 元**列表 ('and', [kids]) / ('or', [kids])：合并(apply_op)时
# 把同种运算符的子节点摊平，使 `a&&a&&…`、`((…))` 等结合性链路只产生一个扁平节点，
# _eval 对其只迭代不深递归。
_PREC = {"and": 2, "or": 1}


def _parse(toks):
    out = []          # 操作数(AST 节点)栈
    ops = []          # 运算符栈：'and' / 'or' / 'lp'
    group_base = []   # 每遇 '(' 记录当时 out 的长度，用于判断该组是否产出了操作数
    prev_value = False  # 上一个 token 是否产出了一个值(操作数或非空分组)

    def apply_op():
        op = ops.pop()
        if len(out) < 2:                # 游离运算符(操作数不足)→ 丢弃，保留已有操作数
            return
        r = out.pop()
        l = out.pop()
        kids = list(l[1]) if isinstance(l, tuple) and l[0] == op else [l]
        kids += list(r[1]) if isinstance(r, tuple) and r[0] == op else [r]
        out.append((op, kids))

    def push_op(op):                    # 左结合：弹出栈顶同/更高优先级运算符
        while ops and ops[-1] != "lp" and _PREC[ops[-1]] >= _PREC[op]:
            apply_op()
        ops.append(op)

    for t in toks:
        k = t[0]
        if k in ("like", "eq"):
            if prev_value:              # 相邻操作数 → 隐式 &&
                push_op("and")
            out.append(t)
            prev_value = True
        elif k in ("and", "or"):
            if not prev_value:          # 缺左操作数的游离运算符 → 跳过
                continue
            push_op(k)
            prev_value = False
        elif k == "lp":
            if prev_value:              # 分组前的相邻操作数 → 隐式 &&
                push_op("and")
            ops.append("lp")
            group_base.append(len(out))
            prev_value = False
        elif k == "rp":
            if not group_base:          # 多余的 ')' → 忽略
                continue
            while ops and ops[-1] != "lp":
                apply_op()
            if ops and ops[-1] == "lp":
                ops.pop()
            base = group_base.pop()
            prev_value = len(out) > base   # 分组产出了操作数才算一个值

    while ops:                          # 收尾：弹出剩余运算符，丢弃未配对的 '('
        if ops[-1] == "lp":
            ops.pop()
            if group_base:
                group_base.pop()
        else:
            apply_op()

    if not out:
        return None
    node = out[0]
    for extra in out[1:]:               # 防御：多余残留操作数用 && 兜合(正常不会发生)
        node = ("and", [node, extra])
    return node


def _eval(node, text: str, text_lower: str):
    # 纯迭代：后序遍历 + id->分值缓存。AST 已扁平为 n 元 and/or，深度只来自
    # &&/|| 交替嵌套；这里同样不用递归，与 _parse 一致，任意深嵌套都不爆栈
    # （_eval 曾是递归，约 1000 层交替括号即 RecursionError，违背本模块设计承诺）。
    if node is None:
        return 0
    order = []                       # 前序：父在前、子在后
    stack = [node]
    while stack:
        n = stack.pop()
        order.append(n)
        if n[0] in ("and", "or"):
            stack.extend(n[1])       # 子节点稍后出栈 → 排在父之后
    val = {}                         # id(节点) -> 分值（None 表示未命中）
    for n in reversed(order):        # 逆序 = 后序：先算子、再算父
        tag = n[0]
        if tag == "like":
            val[id(n)] = _like_score(n[1], n[2], n[3], text_lower)
        elif tag == "eq":
            val[id(n)] = _eq_score(n[1], text)         # 区分大小写：用原文
        elif tag == "and":
            total, miss = 0, False
            for c in n[1]:
                s = val[id(c)]
                if s is None:
                    miss = True
                    break
                total += s
            val[id(n)] = None if miss else total
        elif tag == "or":
            best = None
            for c in n[1]:
                s = val[id(c)]
                if s is not None and (best is None or s > best):
                    best = s
            val[id(n)] = best
        else:
            val[id(n)] = None
    return val[id(node)]


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
    node = _parse(toks)
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
