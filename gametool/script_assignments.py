"""Offset-preserving variable assignments shared by static handle analyses."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re

from .script_lexing import literal_string_value, script_literals, script_views
from .script_scopes import script_structure
from .static_numbers import static_number

_SPACE = re.compile(r"\s+")
_ASSIGNMENT = re.compile(r"[{}]|(?<![<>=~!])=(?!=)")


def expression_key(text: str, *, lua: bool | None) -> str:
    views = script_views(text, lua=lua)
    parts: list[str] = []
    cursor = 0
    for literal in script_literals(text, lua=lua):
        parts.extend(
            (_SPACE.sub("", views.syntax[cursor : literal.start]), repr(literal.value))
        )
        cursor = literal.end
    parts.append(_SPACE.sub("", views.syntax[cursor:]))
    return "".join(parts)


def assigned_start(syntax: str, end: int) -> int | None:
    cursor = end
    while cursor:
        while cursor and syntax[cursor - 1].isspace():
            cursor -= 1
        if cursor and syntax[cursor - 1] == "]":
            depth = 1
            cursor -= 1
            while cursor and depth:
                cursor -= 1
                depth += (syntax[cursor] == "]") - (syntax[cursor] == "[")
            if depth:
                return None
            continue
        stop = cursor
        while cursor and (syntax[cursor - 1].isalnum() or syntax[cursor - 1] == "_"):
            cursor -= 1
        if stop == cursor or not (syntax[cursor].isalpha() or syntax[cursor] == "_"):
            return None
        start = cursor
        while cursor and syntax[cursor - 1].isspace():
            cursor -= 1
        if cursor and syntax[cursor - 1] == ".":
            cursor -= 1
            continue
        return start
    return None


def reference_parts(
    expression: str, *, lua: bool | None
) -> tuple[tuple[str, ...], str]:
    views = script_views(expression, lua=lua)
    if assigned_start(views.syntax, len(views.syntax)) != 0:
        return (), "动态句柄表达式，未跨调用推断触发器关联"
    prefixes: list[str] = []
    opening = -1
    depth = 0
    dynamic = False
    for position, char in enumerate(views.syntax):
        if depth == 0 and char in ".[":
            prefixes.append(expression_key(expression[:position], lua=lua))
        if char == "[":
            if depth == 0:
                opening = position
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                index = views.arguments[opening + 1 : position].strip()
                dynamic |= (
                    literal_string_value(index) is None
                    and static_number(index, lua=lua is True) is None
                )
    prefixes.append(expression_key(expression, lua=lua))
    return tuple(
        prefixes
    ), "句柄含动态索引；仅按表达式关联，实际对象由运行时决定" if dynamic else ""


@dataclass(frozen=True, slots=True)
class ScriptAssignment:
    owner: int | None
    offset: int
    start: int
    end: int
    rhs: int
    ordinal: int
    count: int
    target: str
    key: str
    local: bool


@lru_cache(maxsize=8)
def script_assignments(
    text: str, *, lua: bool | None = None
) -> tuple[ScriptAssignment, ...]:
    structure = script_structure(text, lua=lua)
    views = script_views(text, lua=lua)
    depths: dict[int | None, int] = {}
    result: list[ScriptAssignment] = []
    for match in _ASSIGNMENT.finditer(views.syntax):
        function = structure.scopes.at(match.start())
        owner = function.start if function is not None else None
        token = match.group()
        if token in {"{", "}"}:
            depths[owner] = max(0, depths.get(owner, 0) + (1 if token == "{" else -1))
            continue
        if lua is not False and depths.get(owner, 0):
            continue
        end = match.start()
        targets: list[tuple[int, int]] = []
        while (start := assigned_start(views.syntax, end)) is not None:
            targets.append((start, end))
            end = start
            while end and views.syntax[end - 1].isspace():
                end -= 1
            if lua is False or not end or views.syntax[end - 1] != ",":
                break
            end -= 1
        if not targets:
            continue
        first = targets[-1][0]
        # Only the declaration prefix is examined; never scan/copy the source tail.
        prefix = first
        words: list[str] = []
        for _ in range(2):
            while prefix and views.syntax[prefix - 1].isspace():
                prefix -= 1
            stop = prefix
            while prefix and (
                views.syntax[prefix - 1].isalnum() or views.syntax[prefix - 1] == "_"
            ):
                prefix -= 1
            words.append(views.syntax[prefix:stop])
        local = (
            words[0] == "local"
            or lua is not True
            and len(words) > 1
            and words[1] == "local"
        )
        for ordinal, (start, stop) in enumerate(reversed(targets)):
            target = views.arguments[start:stop].strip()
            result.append(
                ScriptAssignment(
                    owner,
                    match.start(),
                    start,
                    stop,
                    match.end(),
                    ordinal,
                    len(targets),
                    target,
                    expression_key(target, lua=lua),
                    local,
                )
            )
    return tuple(result)
