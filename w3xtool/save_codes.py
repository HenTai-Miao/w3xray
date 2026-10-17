"""存/读码文本提取 (学自 trainer save_codes)。

载体: 地图脚本里的 Preload(...) 调用与 BlzSetAbilityTooltip /
BlzSetAbilityExtendedTooltip / SetPlayerName 调用的字符串参数 —
存档图常把 -load 码模板藏在这些文本里。

边界纪律: 纯正则提取文本, **绝不执行**任何地图脚本或 Preload 内容;
脚本被加密时此类分析不可得 (提取阶梯的静态层结论)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ("SaveCode", "extract_save_codes", "extract_script_save_codes")

# 字符串字面量 (双引号, 支持反斜杠转义)
_STRING_RE = re.compile(r'"((?:\\.|[^"\\])*)"')
# 存/读码指令前缀: -load / !load / -save 等
_PREFIX_RE = re.compile(r"[-!][A-Za-z][A-Za-z0-9_-]{0,31}")
# 值得收录的码体下限: 前缀 + 至少几个字符 (纯 "-load" 不算)
_MIN_CODE_LEN = 8
# 承载存码模板的脚本调用 (trainer 实测的载体)
_CALL_RE = re.compile(
    r"\b(?:BlzSetAbilityTooltip|BlzSetAbilityExtendedTooltip|SetPlayerName"
    r"|Preload)\s*\(",
)
_UNESCAPE_RE = re.compile(r"\\([nrt\"\\])")
_UNESCAPE_MAP = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}


@dataclass(frozen=True, slots=True)
class SaveCode:
    """一条疑似存/读码: 码文本 + 指令前缀 + 载体 + 出处行号。"""

    code: str
    command: str
    source: str
    line: int

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "command": self.command,
            "source": self.source,
            "line": self.line,
        }


def _unescape_literal(s: str) -> str:
    return _UNESCAPE_RE.sub(lambda m: _UNESCAPE_MAP.get(m.group(1), m.group(1)), s)


def extract_save_codes(text: str, source: str = "plain") -> list[SaveCode]:
    """从一段文本提取疑似存/读码 (逐行扫字符串字面量)。"""
    out: list[SaveCode] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if "-" not in line and "!" not in line:
            continue
        if not _CALL_RE.search(line):
            continue
        for m in _STRING_RE.finditer(line):
            literal = _unescape_literal(m.group(1))
            pm = _PREFIX_RE.search(literal)
            if pm is None:
                continue
            code = literal[pm.start() :].strip().strip('"')
            # 码体 (前缀之后 strip) 至少 3 个实字符, 纯 "-load ab" 占位不算。
            body = code[len(pm.group(0)) :].strip()
            if len(code) < _MIN_CODE_LEN or len(body) < 3:
                continue
            out.append(
                SaveCode(code=code, command=pm.group(0), source=source, line=lineno)
            )
    return out


def extract_script_save_codes(text: str) -> list[SaveCode]:
    """从地图脚本可读文本 (war3map.j 形态) 提取存/读码。"""
    return extract_save_codes(text, source="script")
