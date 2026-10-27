"""Complete conditional and loop ranges for static script evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
import re
from types import MappingProxyType

from .script_lexing import ScriptViews, script_views
from .script_scopes import FunctionSpan, ScriptStructure

_CONTROL = re.compile(
    r"\b(if|then|elseif|else|end|endif|for|while|do|loop|endloop|repeat|until)\b"
)
_LUA_OPEN = re.compile(r"\b(?:if|for|while|do|repeat)\b")
_JASS_OPEN = re.compile(r"\b(?:if|loop)\b")


@dataclass(frozen=True, slots=True)
class ControlRange:
    start: int
    end: int
    condition: str
    selector: str
    kind: str = "if"


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

    def close(frame: _Control, stop: int) -> None:
        if frame.start >= 0:
            result.append(
                ControlRange(
                    frame.start + base,
                    stop + base,
                    frame.condition,
                    frame.selector,
                    frame.kind,
                )
            )

    for match in _CONTROL.finditer(views.syntax):
        token = match.group()
        if lua is True and token in {"endif", "loop", "endloop"}:
            continue
        if lua is False and token in {"end", "for", "while", "do", "repeat", "until"}:
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
        elif token in {"elseif", "else"} and stack and stack[-1].kind == "if":
            frame = stack[-1]
            close(frame, match.start())
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
        close(frame, len(own))
    return tuple(sorted(result, key=lambda branch: (branch.start, -branch.end)))
