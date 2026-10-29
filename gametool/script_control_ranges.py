"""Complete conditional and loop ranges for static script evidence."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from bisect import bisect_left
from collections.abc import Mapping
import re
from types import MappingProxyType

from .script_lexing import ScriptViews, script_literals, script_views
from .script_names import LEXICAL_IDENTIFIER
from .script_scopes import FunctionSpan, ScriptStructure
from .static_numbers import numeric_literal_end

_CONTROL = re.compile(
    r"\b(if|then|elseif|else|end|endif|for|while|do|loop|endloop|repeat|until|exitwhen)\b"
)
_LUA_OPEN = re.compile(r"\b(?:if|for|while|do|repeat)\b")
_JASS_OPEN = re.compile(r"\b(?:if|loop)\b")


@dataclass(frozen=True, slots=True)
class ControlPredicate:
    """An original condition span; negated means an earlier branch was excluded."""

    start: int
    end: int
    negated: bool = False
    role: str = "condition"


@dataclass(frozen=True, slots=True)
class ControlRange:
    start: int
    end: int
    condition: str
    selector: str
    kind: str = "if"
    predicates: tuple[ControlPredicate, ...] = ()
    complete: bool = True


@dataclass(frozen=True, slots=True)
class PreparedControlSource:
    """One immutable source/structure/language binding for owner range scans."""

    text: str
    structure: ScriptStructure
    lua: bool | None
    views: ScriptViews = field(init=False)
    functions: Mapping[int, FunctionSpan] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "views", script_views(self.text, lua=self.lua))
        object.__setattr__(
            self,
            "functions",
            MappingProxyType(
                {function.start: function for function in self.structure.functions}
            ),
        )


def prepare_control_source(
    text: str, structure: ScriptStructure, lua: bool | None
) -> PreparedControlSource:
    """Prepare the full source once; callers never supply unbound lexical views."""
    return PreparedControlSource(text, structure, lua)


@dataclass
class _Control:
    kind: str
    header: int
    start: int = -1
    condition: str = ""
    selector: str = ""
    previous: list[str] = field(default_factory=list)
    predicates: list[ControlPredicate] = field(default_factory=list)
    metadata_complete: bool = True


_EXPRESSION_TOKEN = re.compile(
    LEXICAL_IDENTIFIER + r"|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|"
    r"\.\.\.|\.\.|//|<<|>>|==|~=|!=|<=|>=|[^\s]"
)
_BINARY = frozenset("and or + - * / // % ^ & | ~ << >> == ~= != < > <= >= ..".split())
_TERMINATORS = frozenset(
    "end endif endloop until then else elseif do local return call set if for while repeat loop break exitwhen".split()
)


class _ConditionTokens:
    """Find an expression boundary, without evaluating it or imposing a budget."""

    def __init__(self, text: str, views: ScriptViews) -> None:
        tokens: list[tuple[int, int, str]] = []
        cursor = 0
        for match in _EXPRESSION_TOKEN.finditer(views.syntax):
            if match.start() < cursor:
                continue
            numeric_end = numeric_literal_end(views.syntax, match.start())
            if numeric_end is not None:
                tokens.append((match.start(), numeric_end, "<number>"))
                cursor = numeric_end
            else:
                tokens.append((match.start(), match.end(), match.group()))
        tokens.extend(
            (item.start, item.end, "<literal>")
            for item in script_literals(text, lua=views.lua)
        )
        self.tokens = sorted(tokens)
        self.starts = [item[0] for item in self.tokens]
        self.source_end = len(text)

    def end(self, start: int) -> tuple[int, bool]:
        index = bisect_left(self.starts, start)
        expecting = True
        stop = start
        tokens = self.tokens
        while index < len(tokens):
            first, end, token = tokens[index]
            if token in _TERMINATORS or token in {";", ",", ")", "]", "}"}:
                break
            if expecting:
                if token in {"not", "+", "-", "~", "#"}:
                    stop, index = end, index + 1
                    continue
                if token not in {"(", "{"}:
                    if (
                        token in {"<literal>", "<number>"}
                        or token == "..."
                        or token[0].isalnum()
                        or token[0] == "_"
                    ):
                        stop, index, expecting = end, index + 1, False
                        continue
                    break
            else:
                if token in _BINARY:
                    stop, index, expecting = end, index + 1, True
                    continue
                if token in {".", ":"}:
                    stop, index, expecting = end, index + 1, True
                    continue
                if token not in {"(", "["}:
                    break
            if token in {"(", "[", "{"}:
                stack = [{"(": ")", "[": "]", "{": "}"}[token]]
                index += 1
                while index < len(tokens) and stack:
                    _first, stop, nested = tokens[index]
                    if nested in {"(", "[", "{"}:
                        stack.append({"(": ")", "[": "]", "{": "}"}[nested])
                    elif nested in {")", "]", "}"}:
                        if nested != stack.pop():
                            return stop, False
                    index += 1
                if stack:
                    return self.source_end, False
                expecting = False
                continue
            return first, False
        return stop, not expecting


def control_ranges(
    text: str,
    function: FunctionSpan | None,
    structure: ScriptStructure,
    lua: bool | None,
    *,
    prepared: PreparedControlSource | None = None,
) -> tuple[ControlRange, ...]:
    if prepared is not None:
        if (
            prepared.text is not text
            or prepared.structure is not structure
            or prepared.views.lua is not lua
            or function is not None
            and prepared.functions.get(function.start) is not function
        ):
            raise ValueError(
                "prepared control source identity/language/function mismatch"
            )
        syntax = prepared.views.syntax
    else:
        syntax = script_views(text, lua=lua).syntax
    base = function.body_start if function is not None else 0
    end = function.body_end if function is not None else len(text)
    owner = function.start if function is not None else None
    if lua is True and _LUA_OPEN.search(syntax, base, end) is None:
        return ()
    if lua is False and _JASS_OPEN.search(syntax, base, end) is None:
        return ()
    own = structure.own_text(text, base, end, owner)
    views = script_views(own, lua=lua)
    stack: list[_Control] = []
    result: list[ControlRange] = []
    conditions: _ConditionTokens | None = None

    def close(frame: _Control, stop: int, *, complete: bool = True) -> None:
        if frame.start >= 0:
            result.append(
                ControlRange(
                    frame.start + base,
                    stop + base,
                    frame.condition,
                    frame.selector,
                    frame.kind,
                    tuple(frame.predicates),
                    complete and frame.metadata_complete,
                )
            )

    for match in _CONTROL.finditer(views.syntax):
        token = match.group()
        if lua is True and token in {"endif", "loop", "endloop", "exitwhen"}:
            continue
        if lua is False and token in {"end", "for", "while", "do", "repeat", "until"}:
            continue
        if (
            token == "exitwhen"
            or token == "until"
            and stack
            and stack[-1].kind == "repeat"
        ):
            frame = next(
                (
                    item
                    for item in reversed(stack)
                    if item.kind == ("loop" if token == "exitwhen" else "repeat")
                ),
                None,
            )
            if frame is not None:
                if conditions is None:
                    conditions = _ConditionTokens(own, views)
                stop, complete = conditions.end(match.end())
                frame.predicates.append(
                    ControlPredicate(match.end() + base, stop + base, role="loop-exit")
                )
                frame.metadata_complete &= complete
            if token == "exitwhen":
                continue
        if token == "if":
            stack.append(_Control("if", match.end()))
        elif token == "then" and stack and stack[-1].kind == "if":
            frame = stack[-1]
            condition = views.arguments[frame.header : match.start()].strip()
            frame.start, frame.condition, frame.selector = (
                match.end(),
                condition,
                condition,
            )
            frame.previous.append(condition)
            frame.predicates.append(
                ControlPredicate(frame.header + base, match.start() + base)
            )
        elif token in {"elseif", "else"} and stack and stack[-1].kind == "if":
            frame = stack[-1]
            close(frame, match.start())
            frame.predicates = [
                replace(item, negated=True) for item in frame.predicates
            ]
            frame.start = -1
            frame.header = match.end()
            if token == "else":
                frame.start = match.end()
                frame.condition = (
                    "else（排除此前分支：" + "；".join(frame.previous) + "）"
                )
                frame.selector = ""
        elif token in {"for", "while", "loop", "repeat"}:
            stack.append(
                _Control(
                    token,
                    match.end(),
                    start=match.end() if token in {"loop", "repeat"} else -1,
                    condition=token,
                )
            )
        elif token == "do":
            if stack and stack[-1].kind in {"for", "while"}:
                frame = stack[-1]
                frame.condition = (
                    frame.kind
                    + " "
                    + views.arguments[frame.header : match.start()].strip()
                )
                frame.start = match.end()
                frame.predicates.append(
                    ControlPredicate(frame.header + base, match.start() + base)
                )
                frame.kind = "do"
            else:
                stack.append(
                    _Control("do", match.end(), start=match.end(), condition="do")
                )
        elif stack and (
            token == "end"
            and lua is not False
            or token == "endif"
            and stack[-1].kind == "if"
            or token == "endloop"
            and stack[-1].kind == "loop"
            or token == "until"
            and stack[-1].kind == "repeat"
        ):
            close(stack.pop(), match.start())
    for frame in stack:
        close(frame, len(own), complete=False)
    return tuple(sorted(result, key=lambda branch: (branch.start, -branch.end)))
