"""Lexical source symbols and parameters shared by static script analyses."""

from __future__ import annotations

import re

from .script_assignments import expression_key
from .script_lexing import script_views
from .script_scopes import ScopeLookup, ScriptStructure
from .script_control_ranges import ControlRange, control_ranges

_IDENT = re.compile(r"[A-Za-z_]\w*")
_LOCAL = re.compile(r"\blocal\s+(?!function\b)")
_FOR = re.compile(r"\bfor\s+([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*(?:=|\bin\b)")
type ScriptSymbol = tuple[int | None, int, str]


class ScriptSymbols:
    def __init__(
        self, text: str, structure: ScriptStructure, *, lua: bool | None
    ) -> None:
        self.text, self.lua, self.structure = text, lua, structure
        self.views = script_views(text, lua=lua)
        self.functions = {item.start: item for item in structure.functions}
        self.locals: dict[tuple[int | None, str], list[int]] = {}
        self.parameters: dict[int, tuple[str, ...]] = {}
        self.variadic: set[int] = set()
        self.loop_targets: set[int] = set()
        self.controls: dict[
            int | None, tuple[tuple[ControlRange, ...], ScopeLookup[ControlRange]]
        ] = {}
        self._collect_locals()
        self.visibility: dict[tuple[int | None, str], ScopeLookup[int]] = {}
        for (owner, name), positions in self.locals.items():
            ranges = self.control_data(owner)[1]
            end = self.functions[owner].body_end if owner is not None else len(text)
            intervals = []
            for position in positions:
                context = ranges.at(position)
                intervals.append(
                    (position, context.end if context is not None else end, position)
                )
            self.visibility[owner, name] = ScopeLookup(intervals)

    def control_data(
        self, owner: int | None
    ) -> tuple[tuple[ControlRange, ...], ScopeLookup[ControlRange]]:
        cached = self.controls.get(owner)
        if cached is None:
            ranges = control_ranges(
                self.text,
                self.functions.get(owner) if owner is not None else None,
                self.structure,
                self.lua,
            )
            cached = (
                ranges,
                ScopeLookup((item.start, item.end, item) for item in ranges),
            )
            self.controls[owner] = cached
        return cached

    def _collect_locals(self) -> None:
        for function in self.structure.functions:
            header = self.views.syntax[function.start : function.body_start]
            if function.lua:
                opening = header.find("(")
                parameters = (
                    header[opening + 1 : header.rfind(")")] if opening >= 0 else ""
                )
                names = [match.group() for match in _IDENT.finditer(parameters)]
                if "..." in parameters:
                    self.variadic.add(function.start)
            else:
                takes = re.search(r"\btakes\s+(.*?)\s+returns\b", header, re.DOTALL)
                parameters = takes.group(1).strip() if takes is not None else ""
                names = (
                    []
                    if parameters == "nothing"
                    else [
                        match.group(1)
                        for part in parameters.split(",")
                        if (
                            match := re.fullmatch(
                                r"\s*[A-Za-z_]\w*\s+([A-Za-z_]\w*)\s*", part
                            )
                        )
                        is not None
                    ]
                )
            if function.lua and ":" in header[: header.find("(")]:
                names.insert(0, "self")
            self.parameters[function.start] = tuple(names)
            if re.match(r"\s*local\s+function\b", header):
                self.locals.setdefault((function.parent, function.name), []).append(
                    function.start
                )
            for name in names:
                self.locals.setdefault((function.start, name), []).append(
                    function.start
                )
        for match in _LOCAL.finditer(self.views.syntax):
            function = self.structure.scopes.at(match.start())
            owner = function.start if function is not None else None
            cursor = match.end()
            if self.lua is False:
                type_name = _IDENT.match(self.views.syntax, cursor)
                cursor = type_name.end() if type_name is not None else cursor
            while True:
                while cursor < len(self.text) and self.views.syntax[cursor].isspace():
                    cursor += 1
                name = _IDENT.match(self.views.syntax, cursor)
                if name is None:
                    break
                self.locals.setdefault((owner, name.group()), []).append(name.start())
                cursor = name.end()
                while cursor < len(self.text) and self.views.syntax[cursor].isspace():
                    cursor += 1
                if cursor >= len(self.text) or self.views.syntax[cursor] != ",":
                    break
                cursor += 1
        if self.lua is not False:
            for match in _FOR.finditer(self.views.syntax):
                function = self.structure.scopes.at(match.start())
                owner = function.start if function is not None else None
                ranges = self.control_data(owner)[0]
                loop = next(
                    (
                        item
                        for item in ranges
                        if item.kind == "do"
                        and item.condition.startswith("for ")
                        and item.start > match.end()
                    ),
                    None,
                )
                if loop is not None:
                    self.loop_targets.update(
                        name.start()
                        for name in _IDENT.finditer(
                            self.views.syntax, match.start(1), match.end(1)
                        )
                    )
                    for name in _IDENT.findall(match.group(1)):
                        self.locals.setdefault((owner, name), []).append(loop.start)
        for positions in self.locals.values():
            positions.sort()

    def symbol(self, expression: str, owner: int | None, position: int) -> ScriptSymbol:
        key = expression_key(expression, lua=self.lua)
        if key.startswith("_G."):
            return None, -1, key.removeprefix("_G.")
        base = _IDENT.match(key)
        if base is not None:
            current, boundary = owner, position
            while True:
                lookup = self.visibility.get((current, base.group()))
                declaration = lookup.at(boundary) if lookup is not None else None
                if declaration is not None:
                    return current, declaration, key
                if current is None:
                    break
                boundary, current = (
                    self.functions[current].start,
                    self.functions[current].parent,
                )
        return None, -1, key
