"""Exact, non-executing function and call ranges for JASS and Lua sources."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
import heapq
import re
from types import MappingProxyType

from .script_lexing import script_views
from .script_names import (
    IDENTIFIER,
    QUALIFIED_NAME,
    member_suffix,
    name_before,
    qualified_name,
)

_IDENT = IDENTIFIER
_NAME = QUALIFIED_NAME
_FUNCTION = re.compile(r"\bfunction\b")
_JASS_HEADER = re.compile(r"\s+(" + _IDENT + r")\s+takes\b")
_JASS_RETURN = re.compile(r"\breturns\s+" + _IDENT)
_LUA_HEADER = re.compile(r"\s*(?:(" + _NAME + r")\s*)?\(")
_BLOCK = re.compile(
    r"\b(function|endfunction|if|endif|loop|endloop|for|while|do|repeat|until|end)\b"
)
_CALL = re.compile(r"\b(" + _NAME + r")\s*\(")
_PARENS = re.compile(r"[()]")
_NEWLINE = re.compile(r"\r\n?|\n")
_LUA_KEYWORDS = frozenset(
    "and break do else elseif end false for function goto if in local nil not or repeat return then true until while".split()
)
_JASS_KEYWORDS = frozenset(
    "and or not function endfunction if elseif else endif then loop endloop exitwhen return call set local takes returns native constant globals endglobals type extends array debug true false null".split()
)
_NON_NEWLINE = re.compile(r"[^\r\n]")


def source_line_starts(text: str) -> list[int]:
    return [0, *(match.end() for match in _NEWLINE.finditer(text))]


class ScopeLookup[T]:
    """Resolve the innermost interval in logarithmic time, including nested scopes."""

    def __init__(self, ranges: Iterable[tuple[int, int, T]]) -> None:
        entries = tuple(sorted(ranges, key=lambda row: (row[0], -row[1])))
        events: dict[int, list[tuple[bool, int]]] = {}
        for index, (start, end, _value) in enumerate(entries):
            if end <= start:
                continue
            events.setdefault(start, []).append((True, index))
            events.setdefault(end, []).append((False, index))
        active: set[int] = set()
        heap: list[tuple[int, int, int]] = []
        starts: list[int] = []
        ends: list[int] = []
        values: list[T] = []
        previous = 0
        for position, changes in sorted(events.items()):
            while heap and heap[0][2] not in active:
                heapq.heappop(heap)
            if heap and position > previous:
                selected = entries[heap[0][2]][2]
                if values and selected is values[-1] and previous == ends[-1]:
                    ends[-1] = position
                else:
                    starts.append(previous)
                    ends.append(position)
                    values.append(selected)
            for enter, index in changes:
                if enter:
                    active.add(index)
                    start, end, _value = entries[index]
                    heapq.heappush(heap, (-start, end, index))
                else:
                    active.discard(index)
            previous = position
        self._starts = tuple(starts)
        self._ends = tuple(ends)
        self._values = tuple(values)

    def at(self, position: int) -> T | None:
        index = bisect_right(self._starts, position) - 1
        return (
            self._values[index] if index >= 0 and position < self._ends[index] else None
        )


@dataclass(frozen=True, slots=True)
class FunctionSpan:
    name: str
    start: int
    body_start: int
    body_end: int
    end: int
    parent: int | None
    start_line: int
    end_line: int
    complete: bool
    lua: bool


@dataclass(frozen=True, slots=True)
class CallSpan:
    name: str
    start: int
    open: int
    end: int
    owner: int | None
    parent: int | None
    primary: bool
    complete: bool


@dataclass(frozen=True, slots=True)
class ScriptStructure:
    functions: tuple[FunctionSpan, ...]
    calls: tuple[CallSpan, ...]
    scopes: ScopeLookup[FunctionSpan]
    call_scopes: ScopeLookup[CallSpan]
    children: Mapping[int | None, tuple[tuple[int, ...], tuple[FunctionSpan, ...]]]

    def own_text(self, text: str, start: int, end: int, owner: int | None) -> str:
        """Retain this scope's expression text, masking nested function definitions."""
        entry = self.children.get(owner)
        if entry is None:
            return text[start:end]
        starts, functions = entry
        index = bisect_right(starts, start - 1)
        parts: list[str] = []
        cursor = start
        while index < len(functions) and functions[index].start < end:
            item = functions[index]
            stop = min(item.end, end)
            masked = _NON_NEWLINE.sub(" ", text[item.start : stop])
            masked = "nil"[: len(masked)] + masked[3:]
            parts.extend((text[cursor : item.start], masked))
            cursor = stop
            index += 1
        parts.append(text[cursor:end])
        return "".join(parts)


@dataclass
class _Function:
    name: str
    start: int
    body: int
    parent: int | None
    lua: bool
    header_open: int | None = None
    body_end: int = 0
    end: int = 0
    complete: bool = False


def _paren_pairs(syntax: str) -> dict[int, int]:
    stack: list[int] = []
    pairs: dict[int, int] = {}
    for match in _PARENS.finditer(syntax):
        if match.group() == "(":
            stack.append(match.start())
        elif stack:
            pairs[stack.pop()] = match.start()
    return pairs


def _declaration_start(syntax: str, position: int) -> int:
    start = position
    while position:
        while position and syntax[position - 1].isspace():
            position -= 1
        end = position
        while position and (
            syntax[position - 1].isalnum() or syntax[position - 1] == "_"
        ):
            position -= 1
        if syntax[position:end] not in {
            "local",
            "private",
            "public",
            "static",
            "constant",
        }:
            break
        start = position
    return start


def _assigned_name(syntax: str, position: int) -> str:
    while position and syntax[position - 1].isspace():
        position -= 1
    if not position or syntax[position - 1] != "=":
        return ""
    position -= 1
    while position and syntax[position - 1].isspace():
        position -= 1
    parsed = name_before(syntax, position)
    return parsed[1] if parsed is not None else ""


@lru_cache(maxsize=8)
def script_structure(text: str, *, lua: bool | None = None) -> ScriptStructure:
    """Index every source range using explicit stacks; no line or depth ceiling."""
    syntax = script_views(text, lua=lua).syntax
    pairs = _paren_pairs(syntax)
    line_starts = source_line_starts(text)
    functions: list[_Function] = []
    # None means a control block, an integer identifies a function builder.
    blocks: list[tuple[str, int | None]] = []
    current: int | None = None
    cursor = 0

    def close_function(index: int, body_end: int, end: int, complete: bool) -> None:
        nonlocal current
        item = functions[index]
        item.body_end, item.end, item.complete = body_end, end, complete
        current = next(
            (owner for _kind, owner in reversed(blocks) if owner is not None), None
        )

    while (match := _BLOCK.search(syntax, cursor)) is not None:
        cursor = match.end()
        token = match.group()
        if token == "function":
            jass = _JASS_HEADER.match(syntax, cursor) if lua is not True else None
            header = (
                _LUA_HEADER.match(syntax, cursor)
                if lua is not False and jass is None
                else None
            )
            if jass is None and header is None:
                continue  # JASS `function Handler` is a reference, not a declaration.
            is_lua = header is not None
            if not is_lua and current is not None and not functions[current].lua:
                # JASS cannot nest declarations: keep both ranges on damaged input.
                while blocks:
                    _kind, owner = blocks.pop()
                    if owner is not None:
                        close_function(owner, match.start(), match.start(), False)
                        break
            start = _declaration_start(syntax, match.start())
            parent = functions[current].start if current is not None else None
            if header is not None:
                opening = header.end() - 1
                body = pairs.get(opening, opening) + 1
                name = (qualified_name(header.group(1)) if header.group(1) else "") or (
                    _assigned_name(syntax, match.start()) or f"<匿名@{match.start()}>"
                )
            else:
                assert jass is not None
                following = _FUNCTION.search(syntax, jass.end())
                closing = syntax.find("endfunction", jass.end())
                boundary = min(
                    following.start() if following else len(text),
                    closing if closing >= 0 else len(text),
                )
                result = _JASS_RETURN.search(syntax, jass.end(), boundary)
                body = result.end() if result is not None else jass.end()
                name = jass.group(1)
                opening = None
            item = _Function(name, start, body, parent, is_lua, opening)
            current = len(functions)
            functions.append(item)
            blocks.append(("function", current))
            cursor = body
        elif token == "endfunction":
            if current is not None and not functions[current].lua:
                while blocks:
                    _kind, owner = blocks.pop()
                    if owner is not None:
                        close_function(owner, match.start(), match.end(), True)
                        break
        elif current is not None and not functions[current].lua:
            continue  # JASS controls do not own an `end` token.
        elif lua is not False:
            if token in {"if", "for", "while", "repeat"}:
                blocks.append((token, None))
            elif token == "do":
                if blocks and blocks[-1][0] in {"for", "while"}:
                    blocks[-1] = ("do", None)
                else:
                    blocks.append(("do", None))
            elif blocks and (
                (token == "until" and blocks[-1][0] == "repeat")
                or (token == "end" and blocks[-1][0] in {"if", "do", "function"})
            ):
                _kind, owner = blocks.pop()
                if owner is not None:
                    close_function(owner, match.start(), match.end(), True)
    for item in functions:
        if not item.end:
            item.body_end = item.end = len(text)
    spans = tuple(
        FunctionSpan(
            item.name,
            item.start,
            item.body,
            item.body_end,
            item.end,
            item.parent,
            bisect_right(line_starts, item.start),
            bisect_right(line_starts, max(item.start, item.end - 1)),
            item.complete,
            item.lua,
        )
        for item in functions
    )
    scopes = ScopeLookup((item.start, item.end, item) for item in spans)
    declaration_opens = {item.header_open for item in functions}
    calls: list[CallSpan] = []
    ancestors: list[CallSpan] = []
    for match in _CALL.finditer(syntax):
        if member_suffix(syntax, match.start()):
            continue  # A dynamic receiver must not masquerade as its final name.
        name, opening = qualified_name(match.group(1)), match.end() - 1
        assert name is not None
        enclosing = scopes.at(match.start())
        language = enclosing.lua if enclosing is not None else lua
        keywords = (
            _LUA_KEYWORDS
            if language is True
            else _JASS_KEYWORDS
            if language is False
            else _LUA_KEYWORDS & _JASS_KEYWORDS
        )
        if name in keywords or opening in declaration_opens:
            continue
        while ancestors and ancestors[-1].end <= match.start():
            ancestors.pop()
        owner = enclosing.start if enclosing is not None else None
        parent_call = ancestors[-1] if ancestors else None
        end = pairs.get(opening)
        call = CallSpan(
            name,
            match.start(),
            opening,
            end + 1 if end is not None else len(text),
            owner,
            parent_call.start if parent_call else None,
            parent_call is None or parent_call.owner != owner,
            end is not None,
        )
        calls.append(call)
        ancestors.append(call)
    children: dict[int | None, list[FunctionSpan]] = {}
    for item in spans:
        children.setdefault(item.parent, []).append(item)
    return ScriptStructure(
        spans,
        tuple(calls),
        scopes,
        ScopeLookup((item.start, item.end, item) for item in calls),
        MappingProxyType(
            {
                parent: (tuple(item.start for item in values), tuple(values))
                for parent, values in children.items()
            }
        ),
    )
