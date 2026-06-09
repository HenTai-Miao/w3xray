"""模糊搜索打分：空格=AND（每段都要命中），竖线|=OR（任一命中即可）。

例：'智力 剑|法杖' → 含「智力」并且（含「剑」或「法杖」）。
命中返回累加分数（子串优先、连续加权），未命中返回 None；空查询返回 0。
"""
from __future__ import annotations

import re

_BAR_WS = re.compile(r"\s*\|\s*")   # 竖线两侧的空格都吃掉，保证 "a | b" 仍是 OR


def _single_score(query: str, text: str):
    if not query:
        return 0
    if query in text:
        return 1000 - text.index(query)
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


def fuzzy_score(query: str, text: str):
    """支持 AND + OR 的多关键词搜索。命中返回累加分数，未命中返回 None。"""
    if not query:
        return 0
    normalized = _BAR_WS.sub("|", query.replace("｜", "|"))   # "a | b" → "a|b"
    groups = normalized.split()                  # 空格分隔 → AND 各段
    if not groups:
        return 0
    total = 0
    for group in groups:
        alts = [a for a in group.split("|") if a]   # 竖线分隔 → OR 候选
        if not alts:
            continue
        best = None
        for a in alts:
            sc = _single_score(a, text)
            if sc is not None and (best is None or sc > best):
                best = sc
        if best is None:        # 该 AND 段没有任何 OR 候选命中
            return None
        total += best
    return total
