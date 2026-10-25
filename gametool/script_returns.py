"""Source ranges for every return statement, independent of physical lines."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from functools import lru_cache
import re

from .script_lexing import script_views
from .script_scopes import script_structure, source_line_starts

_RETURN = re.compile(r"\breturn\b")
_TOKEN = re.compile(r"\b[A-Za-z_]\w*\b|[()\[\]{};,]")
_STOP = frozenset(
    "return local if then elseif else end endif endfunction loop endloop exitwhen while for do repeat until break goto set call globals endglobals".split()
)


@dataclass(frozen=True, slots=True)
class ReturnSpan:
    start: int
    expression_start: int
    end: int
    owner: int | None
    line: int
    end_line: int
    expression: str
    first: str
    diagnostic: str = ""


@lru_cache(maxsize=8)
def script_returns(text: str, *, lua: bool | None = None) -> tuple[ReturnSpan, ...]:
    """Collect inline/multiline returns, retaining nested literals and exact offsets."""
    structure = script_structure(text, lua=lua)
    views = script_views(text, lua=lua)
    tokens = tuple(_TOKEN.finditer(views.syntax))
    starts = tuple(token.start() for token in tokens)
    calls = {call.start: call for call in structure.calls if call.complete}
    functions = {function.start: function for function in structure.functions}
    lines = source_line_starts(text)
    rows: list[ReturnSpan] = []
    for match in _RETURN.finditer(views.syntax):
        function = structure.scopes.at(match.start())
        owner = function.start if function is not None else None
        bound = function.body_end if function is not None else len(text)
        cursor = bisect_left(starts, match.end())
        stack: list[str] = []
        first_end: int | None = None
        end = bound
        note = ""
        while cursor < len(tokens) and tokens[cursor].start() < bound:
            token = tokens[cursor]
            value = token.group()
            nested = functions.get(token.start())
            call = calls.get(token.start())
            if nested is not None and nested.parent == owner and nested.complete:
                cursor = bisect_left(starts, nested.end)
                continue
            if call is not None and call.owner == owner:
                cursor = bisect_left(starts, call.end)
                continue
            if not stack and (value == ";" or value in _STOP):
                end = token.start()
                break
            if value in "([{":
                stack.append(value)
            elif value in ")]}":
                if not stack or stack[-1] != {")": "(", "]": "[", "}": "{"}[value]:
                    end, note = token.start(), "返回表达式括号不匹配"
                    break
                stack.pop()
            elif value == "," and not stack and first_end is None:
                first_end = token.start()
            cursor += 1
        if stack:
            note = "返回表达式未闭合"
        expression_start = match.end()
        while expression_start < end and views.arguments[expression_start].isspace():
            expression_start += 1
        while end > expression_start and views.arguments[end - 1].isspace():
            end -= 1
        first_stop = min(first_end, end) if first_end is not None else end
        rows.append(
            ReturnSpan(
                match.start(),
                expression_start,
                end,
                owner,
                bisect_right(lines, match.start()),
                bisect_right(lines, max(match.start(), end - 1)),
                views.arguments[expression_start:end],
                views.arguments[expression_start:first_stop].strip(),
                note,
            )
        )
    return tuple(rows)
