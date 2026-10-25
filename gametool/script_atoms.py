"""Complete atomic assignment values, with shared offset-preserving indexing."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .script_assignments import ScriptAssignment
from .script_lexing import script_literals, script_views
from .script_scopes import CallSpan, FunctionSpan, ScriptStructure

_SIMPLE = re.compile(
    r"(?:[+-]?(?:\$[0-9a-fA-F]+|0[xX][0-9a-fA-F]+|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)|[A-Za-z_]\w*(?:[.:][A-Za-z_]\w*)*)"
)
_LOGICAL = re.compile(r"(?:and|or)\b")


@dataclass(frozen=True, slots=True)
class ScriptAtom:
    start: int
    end: int
    call: CallSpan | None = None
    function: FunctionSpan | None = None


class ScriptAtoms:
    def __init__(
        self, text: str, structure: ScriptStructure, *, lua: bool | None
    ) -> None:
        self.text = text
        self.views = script_views(text, lua=lua)
        self.calls = {call.start: call for call in structure.calls}
        self.functions = {function.start: function for function in structure.functions}
        self.literals = {
            literal.start: literal.end for literal in script_literals(text, lua=lua)
        }
        self._values: dict[int, tuple[ScriptAtom | None, ...]] = {}

    def _atom(self, start: int, owner: int | None) -> tuple[ScriptAtom | None, int]:
        cursor = start
        opening = 0
        while cursor < len(self.text):
            if self.views.arguments[cursor].isspace():
                cursor += 1
            elif self.views.arguments[cursor] == "(":
                opening += 1
                cursor += 1
            else:
                break
        first = start
        while first < len(self.text) and self.views.arguments[first].isspace():
            first += 1
        call = self.calls.get(cursor)
        function = self.functions.get(cursor)
        if call is not None and call.complete and call.owner == owner:
            end = call.end
        elif function is not None and function.complete and function.parent == owner:
            end = function.end
        elif cursor in self.literals:
            end = self.literals[cursor]
        elif self.views.syntax.startswith("...", cursor):
            end = cursor + 3
        else:
            simple = _SIMPLE.match(self.views.arguments, cursor)
            if simple is None:
                return None, cursor
            end = simple.end()
        stop = end
        while stop < len(self.text) and (
            self.views.arguments[stop].isspace()
            or opening
            and self.views.arguments[stop] == ")"
        ):
            if self.views.arguments[stop] == ")":
                opening -= 1
                end = stop + 1
            stop += 1
        if (
            opening
            or stop < len(self.text)
            and self.views.syntax[stop] in "+-*/%^&|~<>.[:"
            or _LOGICAL.match(self.views.syntax, stop)
        ):
            return None, stop
        return ScriptAtom(first, end, call, function), stop

    def assignment_values(
        self, assignment: ScriptAssignment
    ) -> tuple[ScriptAtom | None, ...]:
        values = self._values.get(assignment.offset)
        if values is None:
            result: list[ScriptAtom | None] = []
            cursor = assignment.rhs
            while True:
                atom, stop = self._atom(cursor, assignment.owner)
                result.append(atom)
                if (
                    atom is None
                    or stop >= len(self.text)
                    or self.views.arguments[stop] != ","
                ):
                    break
                cursor = stop + 1
            values = tuple(result)
            self._values[assignment.offset] = values
        return values

    def assignment(self, assignment: ScriptAssignment) -> ScriptAtom | None:
        values = self.assignment_values(assignment)
        return values[assignment.ordinal] if assignment.ordinal < len(values) else None

    def value(self, assignment: ScriptAssignment) -> str:
        atom = self.assignment(assignment)
        return (
            self.views.arguments[atom.start : atom.end].strip()
            if atom is not None
            else ""
        )
