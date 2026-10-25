"""Finite geometry terms and source-visible handle alias/effect checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .save_call_context import extract_call_args
from .script_assignments import script_assignments, reference_parts
from .script_lexing import script_views
from .script_names import NAME_PATTERN, qualified_name, rectangle_name
from .script_numeric_expressions import numeric_expression
from .script_object_literals import strip_outer_parentheses
from .script_returns import script_returns
from .script_geometry_values import (
    GEOMETRY_FACTORIES,
    GEOMETRY_READERS,
    GEOMETRY_MUTATORS,
)
from .script_scopes import script_structure

if TYPE_CHECKING:
    from .script_function_bindings import ScriptFunctionBindings

_READ_ONLY = frozenset(
    {
        "CreateItemLoc",
        "CreateUnitAtLoc",
        "CreateItem",
        "BlzCreateItemWithSkin",
        "CreateUnit",
        "BlzCreateUnitWithSkin",
        "CreateCorpse",
        "CreateDestructable",
        "CreateDestructableZ",
        "CreateDeadDestructable",
        "CreateDeadDestructableZ",
        "SetUnitPositionLoc",
        "SetUnitPositionLocFacingBJ",
        "FourCC",
        "select",
        "table.unpack",
        "RectContainsCoords",
        "RectContainsLoc",
        "RectContainsUnit",
        "RectContainsItem",
        *GEOMETRY_READERS,
    }
)


type _Node = tuple[int | None, int, str]


@dataclass(frozen=True, slots=True)
class GeometryEffect:
    offset: int
    expression: str
    reason: str


class GeometryAliases:
    """Flow-insensitive possible aliases; uncertain effects never become coordinates."""

    def __init__(self, functions: ScriptFunctionBindings) -> None:
        self.functions = functions
        self.parents: dict[_Node, _Node] = {}
        self.effects: dict[_Node, dict[int, GeometryEffect]] = {}
        self._references: dict[tuple[str, int | None, int], tuple[_Node, ...]] = {}
        pending: list[tuple[tuple[_Node, ...], GeometryEffect]] = []
        for assignment in script_assignments(functions.text, lua=functions.lua):
            atom = functions.atoms.assignment(assignment)
            if atom is None and functions.lua is True:
                atoms = functions.atoms.assignment_values(assignment)
                if assignment.ordinal >= len(atoms) and atoms and atoms[-1] is not None:
                    atom = atoms[-1] if atoms[-1].call is not None else None
            if atom is None or atom.function is not None:
                continue
            assigned = self.reference(
                functions.views.arguments[atom.start : atom.end],
                assignment.owner,
                functions._rhs_position(assignment),
            )
            if (
                atom.call is not None
                and functions.resolve(
                    atom.call.name, atom.call.start, atom.call.owner
                ).builtin
                in GEOMETRY_FACTORIES
            ):
                assigned = (
                    (assignment.owner, atom.call.start, "@geometry:constructor"),
                )
            self.union(
                (
                    *self.reference(
                        assignment.target, assignment.owner, assignment.start
                    ),
                    *assigned,
                )
            )
        for row in script_returns(functions.text, lua=functions.lua):
            if row.owner is not None:
                self.union(
                    (
                        (row.owner, -2, "return"),
                        *self.reference(
                            row.expression, row.owner, row.expression_start
                        ),
                    )
                )
        for call in functions.structure.calls:
            if not call.complete:
                continue
            args = extract_call_args(functions.views, call.open + 1)
            if ":" in call.name:
                args = (call.name.rsplit(":", 1)[0], *args)
            reference = functions.resolve(call.name, call.start, call.owner)
            if len(reference.functions) == 1 and not reference.diagnostic:
                target = reference.functions[0].start
                parameters = functions.symbols.parameters.get(target, ())
                for index, parameter in enumerate(parameters):
                    value = (
                        args[index] if index < len(args) else args[-1] if args else ""
                    )
                    self.union(
                        (
                            functions.symbols.symbol(parameter, target, target),
                            *self.reference(value, call.owner, call.open + 1),
                        )
                    )
                if target in functions.symbols.variadic:
                    self.union(
                        (
                            (target, -3, "..."),
                            *(
                                node
                                for value in args[len(parameters) :]
                                for node in self.reference(
                                    value, call.owner, call.open + 1
                                )
                            ),
                        )
                    )
            elif reference.builtin in GEOMETRY_MUTATORS:
                nodes = (
                    self.reference(args[0], call.owner, call.open + 1) if args else ()
                )
                pending.append(
                    (
                        nodes,
                        GeometryEffect(
                            call.start,
                            functions.text[call.start : call.end],
                            "修改或销毁几何句柄",
                        ),
                    )
                )
            elif (
                reference.builtin not in GEOMETRY_FACTORIES
                and reference.builtin not in _READ_ONLY
                and not (
                    call.name.removeprefix("_G.") in _READ_ONLY
                    and not functions.bound(call.name, call.owner, call.start)
                )
            ):
                nodes = tuple(
                    node
                    for value in args
                    for node in self.reference(value, call.owner, call.open + 1)
                )
                pending.append(
                    (
                        nodes,
                        GeometryEffect(
                            call.start,
                            functions.text[call.start : call.end],
                            "传给未解析调用，副作用未验证",
                        ),
                    )
                )
        for nodes, effect in pending:
            for node in nodes:
                self.effects.setdefault(self.root(node), {})[effect.offset] = effect

    def root(self, node: _Node) -> _Node:
        trail: list[_Node] = []
        while node in self.parents and self.parents[node] != node:
            trail.append(node)
            node = self.parents[node]
        self.parents.setdefault(node, node)
        for previous in trail:
            self.parents[previous] = node
        return node

    def union(self, nodes: tuple[_Node, ...]) -> None:
        if not nodes:
            return
        root = self.root(nodes[0])
        for node in nodes[1:]:
            previous = self.root(node)
            if previous != root:
                self.effects.setdefault(root, {}).update(self.effects.pop(previous, {}))
                self.parents[previous] = root

    def reference(
        self, text: str, owner: int | None, position: int
    ) -> tuple[_Node, ...]:
        key = (text, owner, position)
        cached = self._references.get(key)
        if cached is not None:
            return cached
        value = strip_outer_parentheses(text.strip())
        if numeric_expression(value, lua=self.functions.lua) is not None:
            self._references[key] = ()
            return ()
        syntax = script_views(value, lua=self.functions.lua).syntax
        if value == "...":
            return ((owner, -3, "..."),)
        name = qualified_name(syntax) or rectangle_name(syntax)
        if name is not None:
            target = self.functions.resolve(name, position, owner)
            if len(target.functions) == 1 and not target.diagnostic:
                result = ((target.functions[0].start, -2, "return"),)
            else:
                parts, _ = reference_parts(name, lua=self.functions.lua)
                result = tuple(
                    self.functions.symbols.symbol(part, owner, position)
                    for part in parts
                )
                self.union(result)
        else:
            calls = script_structure(value, lua=self.functions.lua).calls
            whole = next(
                (
                    call
                    for call in calls
                    if call.start == 0 and call.end == len(value) and call.complete
                ),
                None,
            )
            target = (
                self.functions.resolve(whole.name, position, owner) if whole else None
            )
            if target is not None and target.builtin in GEOMETRY_FACTORIES:
                result = ((owner, position, "@geometry:constructor"),)
            elif target is not None and target.builtin in GEOMETRY_READERS:
                result = ()
            elif (
                target is not None
                and len(target.functions) == 1
                and not target.diagnostic
            ):
                result = ((target.functions[0].start, -2, "return"),)
            elif (
                whole is not None
                and whole.name.removeprefix("_G.")
                in _READ_ONLY - {"select", "table.unpack"}
                and not self.functions.bound(whole.name, owner, position)
            ):
                result = ()
            else:
                masked = list(syntax)
                for call in calls:
                    masked[call.start : call.open] = " " * (call.open - call.start)
                result = tuple(
                    self.functions.symbols.symbol(match.group(), owner, position)
                    for match in NAME_PATTERN.finditer("".join(masked))
                    if match.group() not in {"nil", "null", "true", "false"}
                )
        self._references[key] = result
        return result

    def mutations(
        self, expression: str, owner: int | None, position: int
    ) -> tuple[GeometryEffect, ...]:
        effects: dict[int, GeometryEffect] = {}
        for node in self.reference(expression, owner, position):
            effects.update(self.effects.get(self.root(node), {}))
        return tuple(effects[offset] for offset in sorted(effects))

    def diagnostic(self, expression: str, owner: int | None, position: int) -> str:
        effects = self.mutations(expression, owner, position)
        return (
            "几何句柄存在可能的修改、销毁或参数逃逸；源调用偏移: "
            + ",".join(str(effect.offset) for effect in effects)
            if effects
            else ""
        )
