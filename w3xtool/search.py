"""搜索打分：空格=AND（每段都要命中），竖线|=OR（任一命中即可），引号=精准。

- 不加引号的词 → 模糊（中等）：连续子串优先；纯 ASCII 还保留子序列（"fb"→"foobar"）。
- "…" 双引号 → 精准：必须原样连续出现；引号内的空格、|、冒号都当普通字符
  （所以能搜带空格/竖线的整句）。
例：'智力 剑|法杖' → 含「智力」且（含「剑」或「法杖」）；
    '蓝宝石 "等级:E"' → 模糊「蓝宝石」且 精准「等级:E」。
命中返回累加分数（越靠前/越连续分越高），未命中返回 None；空查询返回 0。
"""
from __future__ import annotations


def _single_score(query: str, text: str):
    """模糊（中等）：连续子串优先；纯 ASCII 允许子序列，含中文则只认子串。"""
    if not query:
        return 0
    if query in text:
        return 1000 - text.index(query)
    # 含中文等非 ASCII 字符的关键词只认子串：每个汉字都是一个词义单位，
    # 若退化成子序列匹配（字符可在长描述里分散命中），会把"全属性"匹配到
    # "全村…攻击属性"这类无关项，造成大量误命中。子序列仅保留给纯 ASCII。
    if any(ord(ch) > 127 for ch in query):
        return None
    qi = 0
    score = 0
    last = -1
    for i, ch in enumerate(text):
        if qi < len(query) and ch == query[qi]:
            score += 10 if i == last + 1 else 1
            last = i
            qi += 1
    if qi == len(query):
        return score
    return None


def _is_word_char(ch: str) -> bool:
    """"词内字符"：ASCII 字母/数字，外加 '+'。

    中文等非 ASCII 不算（每个汉字自成单位，精准词允许 全属→全属性 这类紧邻
    匹配；词边界只约束 ASCII 串）。'+' 计入是因为物品等级档用它分级（S 与 S+
    是两档），算粘连字符才能让"等级:S"不误命中"等级:S+"。"""
    return ch == "+" or (ch.isascii() and ch.isalnum())


def _exact_score(query: str, text: str):
    """精准：必须原样连续出现（子串），且 ASCII 端点不可粘进更长的词。

    若精准词以词内字符(ASCII 字母/数字或 '+')结尾，则其后一字符不能也是词内
    字符——否则把"等级:E"误命中"等级:EX"、"等级:S"误命中"等级:S+"；开头同理。
    中文端点不设边界（保持 全属→全属性 这类紧邻匹配可命中）。
    命中返回分数（越靠前分越高），否则 None。
    """
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


def _tokenize(query: str):
    """把查询切成 AND 组，每组是若干 OR 候选 (term, precise)。

    双引号内的内容为精准词：原样连续匹配，内部的空格/竖线/冒号都不作分隔。
    引号外：竖线 | 连接 OR 候选（两侧的空格会被吃掉，"a | b" 仍是 OR），
    其余空格分隔 AND 组。未闭合的引号按到行尾处理（边打边搜也不报错）。
    """
    query = (query.replace("“", '"').replace("”", '"').replace("｜", "|"))
    # 先扁平收集每个词，并记录它与前一个词的连接关系：竖线→OR，否则→AND。
    # 竖线/空格只是“间隙标记”，跨越多个空格与竖线累积，遇到下一个实词时才结算。
    terms: list[tuple[str, bool, str]] = []   # (term, precise, join: 'or'|'and')
    buf: list[str] = []
    in_quote = False
    from_quote = False        # 当前 buf 是否来自引号（精准）
    saw_bar = False           # 自上个词以来出现过竖线
    have_prev = False

    def flush_term():
        nonlocal buf, from_quote, saw_bar, have_prev
        term = "".join(buf)
        precise = from_quote
        buf = []
        from_quote = False
        if not term:                      # 空缓冲：保留间隙标记给下一个实词
            return
        join = "or" if (have_prev and saw_bar) else "and"
        terms.append((term, precise, join))
        have_prev = True
        saw_bar = False                   # 间隙标记已结算，复位

    for ch in query:
        if ch == '"':
            if in_quote:                  # 引号结束 → 当前 buf 是一个精准候选
                in_quote = False
                from_quote = True
                flush_term()
            else:                         # 引号开始 → 先收掉前面未加引号的缓冲
                flush_term()
                in_quote = True
            continue
        if in_quote:
            buf.append(ch)
            continue
        if ch.isspace():
            flush_term()                  # 空格只断词，间隙标记(saw_bar)保留
        elif ch == "|":
            flush_term()
            saw_bar = True                # 标记 OR，跨越两侧空格仍生效
        else:
            buf.append(ch)

    if in_quote:                          # 未闭合引号：剩余按精准词收尾
        from_quote = True
    flush_term()

    groups: list[list[tuple[str, bool]]] = []
    for term, precise, join in terms:
        if join == "or" and groups:
            groups[-1].append((term, precise))
        else:
            groups.append([(term, precise)])
    return groups


def fuzzy_score(query: str, text: str):
    """支持 AND + OR + 引号精准的多关键词搜索。命中返回累加分数，未命中返回 None。

    传入原始大小写的 query 与 text：模糊词不分大小写（双方转小写比较），
    引号精准词区分大小写（原样比较）。空查询返回 0。
    """
    if not query:
        return 0
    groups = _tokenize(query)
    if not groups:
        return 0
    text_lower = text.lower()
    total = 0
    for group in groups:
        best = None
        for term, precise in group:
            if precise:
                sc = _exact_score(term, text)                  # 区分大小写
            else:
                sc = _single_score(term.lower(), text_lower)   # 不分大小写
            if sc is not None and (best is None or sc > best):
                best = sc
        if best is None:        # 该 AND 段没有任何 OR 候选命中
            return None
        total += best
    return total
