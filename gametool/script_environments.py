"""Source-local Lua environment identities, without evaluating tables or scripts."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from typing import Protocol

from .script_assignments import script_assignments
from .script_atoms import ScriptAtoms
from .script_control_ranges import ControlRange
from .script_names import qualified_name
from .script_object_literals import strip_outer_parentheses
from .script_scopes import ScopeLookup, ScriptStructure

type EnvironmentSymbol = tuple[int | None, int, str]
type _Key = tuple[str, int | None, int, bool]
_STANDARD: EnvironmentSymbol = (None, -1, "")


class EnvironmentSources(Protocol):
    text: str
    structure: ScriptStructure
    loop_targets: set[int]

    def _lexical_symbol(
        self, key: str, owner: int | None, position: int
    ) -> EnvironmentSymbol: ...
    def _global_table_available(self, owner: int | None, position: int) -> bool: ...
    def control_data(
        self, owner: int | None
    ) -> tuple[tuple[ControlRange, ...], ScopeLookup[ControlRange]]: ...


@dataclass(frozen=True, slots=True)
class _Write:
    owner: int | None
    start: int
    rhs_position: int
    value: str
    local: bool


class LuaEnvironments:
    """Follow complete alias chains with explicit work stacks and lexical identity."""

    def __init__(self, symbols: EnvironmentSources) -> None:
        self.symbols = symbols
        atoms = ScriptAtoms(symbols.text, symbols.structure, lua=True)
        grouped: dict[EnvironmentSymbol, list[_Write]] = {}
        assignments = script_assignments(symbols.text, lua=True)
        starts: dict[int, int] = {}
        for row in assignments:
            starts[row.offset] = min(starts.get(row.offset, row.start), row.start)
        for row in assignments:
            if qualified_name(row.key) != row.key or "." in row.key:
                continue
            if row.start in symbols.loop_targets:
                continue
            symbol = symbols._lexical_symbol(row.key, row.owner, row.start)
            grouped.setdefault(symbol, []).append(
                _Write(
                    row.owner,
                    row.start,
                    starts[row.offset] - 1,
                    atoms.value(row),
                    row.local,
                )
            )
        for function in symbols.structure.functions:
            if qualified_name(function.name) != function.name or "." in function.name:
                continue
            symbol = symbols._lexical_symbol(
                function.name, function.parent, function.start
            )
            grouped.setdefault(symbol, []).append(
                _Write(function.parent, function.start, function.start, "", False)
            )
        self.writes = {
            symbol: tuple(sorted(rows, key=lambda row: row.start))
            for symbol, rows in grouped.items()
        }
        self.offsets = {
            symbol: tuple(row.start for row in rows)
            for symbol, rows in self.writes.items()
        }
        self.foreign_writes = {
            symbol
            for symbol, rows in self.writes.items()
            if any(row.owner != symbol[0] for row in rows)
        }
        self.cache: dict[_Key, EnvironmentSymbol] = {}

    def identity(self, owner: int | None, position: int) -> EnvironmentSymbol:
        return self.resolve(("_ENV", owner, position, False))

    def resolve(self, first: _Key) -> EnvironmentSymbol:
        plans: dict[_Key, tuple[str, EnvironmentSymbol, tuple[_Key, ...]]] = {}
        pending = [(first, False)]
        visiting: set[_Key] = set()
        while pending:
            key, ready = pending.pop()
            if key in self.cache:
                continue
            if ready:
                mode, fallback, dependencies = plans[key]
                result = self.cache[dependencies[-1]]
                if mode == "global" and self.cache[dependencies[0]] != _STANDARD:
                    result = fallback
                self.cache[key] = result
                visiting.discard(key)
                continue
            if key in visiting:
                self.cache[key] = (None, 0, "@environment:cycle")
                continue
            mode, fallback, dependencies = self.plan(key)
            if not dependencies:
                self.cache[key] = fallback
                continue
            visiting.add(key)
            plans[key] = mode, fallback, dependencies
            pending.append((key, True))
            pending.extend((dependency, False) for dependency in reversed(dependencies))
        return self.cache[first]

    def plan(self, key: _Key) -> tuple[str, EnvironmentSymbol, tuple[_Key, ...]]:
        name, owner, position, raw = key
        symbol = self.symbols._lexical_symbol(name, owner, position)
        rows = self.writes.get(symbol, ())
        fallback = (symbol[0], max(0, symbol[1]), symbol[2])
        uncertain = (symbol[0], max(0, position), "@environment:unresolved:" + name)
        if name != "_ENV" and symbol[1] < 0 and not raw:
            environment = ("_ENV", owner, position, False)
            if name == "_G":
                if self.symbols._global_table_available(owner, position):
                    return "global", fallback, (environment,)
                return "", fallback, ()
            return "global", fallback, (environment, (name, owner, position, True))
        if symbol in self.foreign_writes:
            return "", uncertain, ()
        if not rows:
            return "", _STANDARD if name == "_ENV" and symbol[1] < 0 else fallback, ()
        if owner == symbol[0]:
            index = bisect_left(self.offsets.get(symbol, ()), position) - 1
            selected = rows[index] if index >= 0 else None
        elif len(rows) == 1:
            selected = rows[0]
        else:
            return "", uncertain, ()
        if selected is None:
            return "", _STANDARD if name == "_ENV" and symbol[1] < 0 else fallback, ()
        fallback = (symbol[0], max(0, selected.start), symbol[2])
        context = self.symbols.control_data(selected.owner)[1].at(selected.start)
        if context is not None and not selected.local:
            return "", uncertain, ()
        value = qualified_name(strip_outer_parentheses(selected.value.strip()))
        if value is None or "." in value:
            return "", fallback, ()
        dependency = (value, selected.owner, selected.rhs_position, False)
        if raw and symbol[1] < 0 and name != "_ENV":
            return (
                "global",
                uncertain,
                (("_ENV", selected.owner, selected.start, False), dependency),
            )
        return (
            "alias",
            fallback,
            (dependency,),
        )
