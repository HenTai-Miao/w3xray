"""Preserve callable syntax outside the shared named-call binding grammar.

This is an evidence boundary, not a Lua/JASS compiler.  Every returned call keeps
its complete source spelling and remains unresolved; no source is evaluated.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .script_lexing import (
    _noncode_spans,
    literal_string_value,
    script_views,
)
from .script_names import LEXICAL_IDENTIFIER
from .script_scopes import CallSpan, ScriptStructure, script_structure

_TOKEN = re.compile(LEXICAL_IDENTIFIER + r"|\d[\w.]*|[^\s]")
_FUNCTION_HEADER = re.compile(
    r"\bfunction\b\s*(?:"
    + LEXICAL_IDENTIFIER
    + r"(?:\s*[.:]\s*"
    + LEXICAL_IDENTIFIER
    + r")*)?\s*(?P<opening>\()"
)
_KEYWORDS = frozenset(
    "and break do else elseif end false for function goto if in local nil not or "
    "repeat return then true until while call set takes returns native constant "
    "globals endglobals type extends array debug endfunction endif loop endloop "
    "exitwhen null private public static".split()
)
_CLOSE = {"(": ")", "[": "]", "{": "}"}


@dataclass(frozen=True, slots=True)
class ScriptCallSyntaxDiagnostic:
    code: str
    message: str
    offset: int
    end_offset: int
    raw: str
    callee: str = ""
    arguments: tuple[str, ...] = ()
    complete: bool = False


@dataclass(frozen=True, slots=True)
class _Token:
    start: int
    end: int
    value: str
    literal: bool = False


@dataclass(frozen=True, slots=True)
class _Opening:
    token: int
    kind: str
    start: int | None = None
    known: bool = False


def _tokens(
    text: str, lua: bool
) -> tuple[list[_Token], list[ScriptCallSyntaxDiagnostic]]:
    views = script_views(text, lua=lua)
    tokens = [
        _Token(match.start(), match.end(), match.group())
        for match in _TOKEN.finditer(views.syntax)
    ]
    diagnostics: list[ScriptCallSyntaxDiagnostic] = []
    for start, end, string in _noncode_spans(text, lua):
        raw = text[start:end]
        if string:
            if literal_string_value(raw) is not None:
                tokens.append(_Token(start, end, raw, True))
            else:
                diagnostics.append(
                    ScriptCallSyntaxDiagnostic(
                        "script.call.syntax.literal",
                        "字面量未闭合；保留完整原文，未将其中内容解释为调用。",
                        start,
                        end,
                        raw,
                    )
                )
        elif lua and (opening := re.match(r"--\[(=*)\[", raw)) is not None:
            close = "]" + opening.group(1) + "]"
            if raw.find(close, opening.end()) < 0:
                diagnostics.append(
                    ScriptCallSyntaxDiagnostic(
                        "script.call.syntax.comment",
                        "长括号注释未闭合；保留完整原文，未将其中内容解释为调用。",
                        start,
                        end,
                        raw,
                    )
                )
    tokens.sort(key=lambda item: item.start)
    return tokens, diagnostics


def _arguments(
    text: str,
    syntax: str,
    arguments: str,
    structure: ScriptStructure,
    start: int,
    opening: int,
    end: int,
) -> tuple[str, ...]:
    """Split full original expressions, masking only nested function ownership."""
    function = structure.scopes.at(start)
    owner = function.start if function is not None else None
    first, stop = opening + 1, end - 1
    own = structure.own_text(syntax, first, stop, owner)
    stack: list[str] = []
    result: list[str] = []
    cursor = first
    for match in re.finditer(r"[()\[\]{},]", own):
        token = match.group()
        if token in _CLOSE:
            stack.append(_CLOSE[token])
        elif token in ")]}":
            if stack and stack[-1] == token:
                stack.pop()
        elif not stack:
            result.append(text[cursor : first + match.start()].strip())
            cursor = first + match.end()
    if arguments[cursor:stop].strip() or result:
        result.append(text[cursor:stop].strip())
    return tuple(result)


def script_call_syntax_diagnostics(
    text: str, *, lua: bool, known_calls: tuple[CallSpan, ...]
) -> tuple[ScriptCallSyntaxDiagnostic, ...]:
    """Retain every recognized dynamic/sugar call and unclosed literal boundary.

    Complete dynamic records have ``code == 'script.call.dynamic'`` and retain
    the callee/arguments so a caller can expose them as unresolved call evidence.
    Prefix expressions are tracked with explicit stacks, never executed or
    assigned a native identity. Plain grouping and declaration headers are not
    calls. Named calls already represented by ``known_calls`` are not repeated.
    """
    tokens, result = _tokens(text, lua)
    views = script_views(text, lua=lua)
    structure = script_structure(text, lua=lua)
    declarations = {
        match.start("opening") for match in _FUNCTION_HEADER.finditer(views.syntax)
    }
    known = {call.open for call in known_calls}
    prefixes: dict[int, int] = {}
    stack: list[_Opening] = []

    def append_call(start: int, opening: int, end: int, *, sugar: bool) -> None:
        first = tokens[start].start
        argument_start = tokens[opening].start
        result.append(
            ScriptCallSyntaxDiagnostic(
                "script.call.dynamic",
                "动态接收者、非标准名称或 Lua 参数简写调用；保留完整词法证据，"
                "未解析函数绑定或推断实际效果。",
                first,
                end,
                text[first:end],
                text[first:argument_start].strip(),
                (text[argument_start:end],)
                if sugar
                else _arguments(
                    text,
                    views.syntax,
                    views.arguments,
                    structure,
                    first,
                    argument_start,
                    end,
                ),
                True,
            )
        )

    for index, token in enumerate(tokens):
        previous = prefixes.get(index - 1)
        if token.literal:
            if lua and previous is not None:
                append_call(previous, index, token.end, sugar=True)
                prefixes[index] = previous
            continue
        value = token.value
        if value in _CLOSE:
            if value == "(" and token.start in declarations:
                stack.append(_Opening(index, "declaration"))
            elif previous is not None and (value != "{" or lua):
                stack.append(
                    _Opening(
                        index,
                        "index" if value == "[" else "call",
                        previous,
                        value == "(" and token.start in known,
                    )
                )
            else:
                stack.append(_Opening(index, "group" if value == "(" else "value"))
            continue
        if value in ")]}":
            if not stack or _CLOSE[tokens[stack[-1].token].value] != value:
                continue
            opening = stack.pop()
            if opening.kind == "call" and opening.start is not None:
                if not opening.known:
                    append_call(
                        opening.start,
                        opening.token,
                        token.end,
                        sugar=tokens[opening.token].value == "{",
                    )
                prefixes[index] = opening.start
            elif opening.kind == "index" and opening.start is not None:
                prefixes[index] = opening.start
            elif opening.kind == "group" and index > opening.token + 1:
                prefixes[index] = opening.token
            continue
        if value in _KEYWORDS or not re.fullmatch(LEXICAL_IDENTIFIER, value):
            continue
        # A member of a dynamic prefix is still that full receiver expression.
        if index >= 2 and tokens[index - 1].value in {".", ":"}:
            receiver = prefixes.get(index - 2)
            if receiver is not None:
                prefixes[index] = receiver
            continue
        prefixes[index] = index

    for opening in stack:
        if opening.kind != "call" or opening.start is None or opening.known:
            continue
        start = tokens[opening.start].start
        result.append(
            ScriptCallSyntaxDiagnostic(
                "script.call.syntax.incomplete",
                "调用参数范围未闭合；保留完整剩余原文，未猜测调用边界或函数绑定。",
                start,
                len(text),
                text[start:],
            )
        )
    return tuple(
        sorted(result, key=lambda item: (item.offset, item.end_offset, item.code))
    )
