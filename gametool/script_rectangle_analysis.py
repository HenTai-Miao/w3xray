"""Named rectangle bounds with source-backed values and handle effect diagnostics."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from functools import lru_cache

from .script_assignments import ScriptAssignment, script_assignments
from .script_function_graph import script_functions
from .script_geometry_values import geometry_coordinates
from .script_names import rectangle_name
from .script_placement_analysis import PlacementDiagnostic


@dataclass(frozen=True, slots=True)
class ScriptRectangle:
    name: str
    bounds: tuple[float, float, float, float]
    offset: int
    line: int
    expression: str
    evidence: tuple[str, ...] = ()

    def row(self) -> tuple[str, float, float, float, float]:
        return self.name, *self.bounds


@dataclass(frozen=True, slots=True)
class RectangleAnalysis:
    rectangles: tuple[ScriptRectangle, ...]
    diagnostics: tuple[PlacementDiagnostic, ...] = ()


@lru_cache(maxsize=8)
def analyze_script_rectangles(
    script: str, *, lua: bool | None = False
) -> RectangleAnalysis:
    functions = script_functions(script, lua=lua)
    found: dict[
        tuple[int, tuple[str, float, float, float, float]], ScriptRectangle
    ] = {}
    diagnostics: list[PlacementDiagnostic] = []

    def expression(assignment: ScriptAssignment) -> str:
        atoms = functions.atoms.assignment_values(assignment)
        end = max(
            (atom.end for atom in atoms if atom is not None), default=assignment.rhs
        )
        return script[assignment.start : end]

    def resolve(
        assignment: ScriptAssignment,
        name: str,
        arguments: tuple[str | None, ...],
        unknown_tail: bool,
        evidence: tuple[str, ...] = (),
    ) -> str:
        atoms = functions.atoms.assignment_values(assignment)
        if any(atom is None for atom in atoms):
            return "区域赋值表达式未完整解析，未猜测矩形边界"
        parts = tuple(
            functions.views.arguments[atom.start : atom.end]
            for atom in atoms
            if atom is not None
        )
        value = functions.argument_values(
            parts,
            assignment.owner,
            functions._rhs_position(assignment),
            arguments,
            unknown_tail=unknown_tail,
        ).at(assignment.ordinal)
        bounds = geometry_coordinates(value)
        note = functions.values.geometry_note(
            assignment.target, assignment.owner, assignment.rhs
        )
        if note or value.kind != "rect" or bounds is None:
            return note or value.diagnostic or "区域句柄未静态确定，未猜测矩形边界"
        assert len(bounds) == 4
        proof = dict.fromkeys(functions.values.proof_lines(value))
        proof.update(dict.fromkeys(evidence))
        row = ScriptRectangle(
            name,
            (bounds[0], bounds[1], bounds[2], bounds[3]),
            assignment.start,
            bisect_right(functions.lines, assignment.start),
            expression(assignment),
            tuple(proof),
        )
        found.setdefault((row.offset, row.row()), row)
        return ""

    for assignment in script_assignments(script, lua=lua):
        name = rectangle_name(assignment.target)
        if name is None:
            continue
        if name.startswith("_ENV.") and lua is not True:
            continue
        if name.startswith("_G.") and functions.bound(
            "_G", assignment.owner, assignment.start
        ):
            continue
        name = name.removeprefix("_G.").removeprefix("_ENV.")
        arguments = (
            tuple(None for _ in functions.symbols.parameters.get(assignment.owner, ()))
            if assignment.owner is not None
            else ()
        )
        note = resolve(
            assignment, name, arguments, assignment.owner in functions.symbols.variadic
        )
        if not note:
            continue
        dynamic: dict[str, None] = {}
        if assignment.owner is not None and (
            functions.symbols.parameters.get(assignment.owner)
            or assignment.owner in functions.symbols.variadic
        ):
            for context in functions.source_contexts().get(assignment.owner, ()):
                result = resolve(
                    assignment,
                    name,
                    context.node.arguments,
                    context.node.unknown_tail,
                    context.evidence,
                )
                if result and context.incoming:
                    dynamic["; ".join((result, *context.diagnostics))] = None
        if any(offset == assignment.start for offset, _row in found) and not dynamic:
            continue
        diagnostics.append(
            PlacementDiagnostic(
                assignment.start,
                bisect_right(functions.lines, assignment.start),
                expression(assignment),
                "; ".join(dynamic or {note: None}),
            )
        )
    return RectangleAnalysis(
        tuple(sorted(found.values(), key=lambda row: row.offset)), tuple(diagnostics)
    )
