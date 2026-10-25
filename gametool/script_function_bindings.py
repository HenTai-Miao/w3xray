"""Source-local function symbols, aliases and reassignment diagnostics."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
import re

from .save_call_context import extract_call_args
from .script_assignments import ScriptAssignment, reference_parts, script_assignments
from .script_atoms import ScriptAtoms
from .script_lexing import script_views
from .script_names import qualified_name
from .script_object_literals import strip_outer_parentheses
from .script_scopes import CallSpan, FunctionSpan, script_structure, source_line_starts
from .script_symbols import ScriptSymbol, ScriptSymbols


@dataclass(frozen=True, slots=True)
class FunctionReference:
    expression: str
    functions: tuple[FunctionSpan, ...]
    diagnostic: str = ""
    builtin: str = ""


class ScriptFunctionBindings:
    def __init__(self, text: str, *, lua: bool | None) -> None:
        self.text, self.lua = text, lua
        self.structure = script_structure(text, lua=lua)
        self.views = script_views(text, lua=lua)
        self.symbols = ScriptSymbols(text, self.structure, lua=lua)
        self.atoms = ScriptAtoms(text, self.structure, lua=lua)
        self.lines = source_line_starts(text)
        self.calls: dict[int | None, list[CallSpan]] = {}
        self.writes: dict[ScriptSymbol, list[ScriptAssignment]] = {}
        self.definitions: dict[ScriptSymbol, list[FunctionSpan]] = {}
        self.assignment_offsets: dict[int, int] = {}
        assigned_functions: set[int] = set()
        for assignment in script_assignments(text, lua=lua):
            if assignment.start in self.symbols.loop_targets:
                continue
            symbol = self.symbols.symbol(
                assignment.target, assignment.owner, assignment.start
            )
            self.writes.setdefault(symbol, []).append(assignment)
            self.assignment_offsets[assignment.offset] = min(
                self.assignment_offsets.get(assignment.offset, assignment.start),
                assignment.start,
            )
            atom = self.atoms.assignment(assignment)
            if atom is not None and atom.function is not None:
                assigned_functions.add(atom.function.start)
        for function in self.structure.functions:
            if function.start in assigned_functions or function.name.startswith("<"):
                continue
            symbol = self.symbols.symbol(
                function.name.replace(":", "."), function.parent, function.start
            )
            self.definitions.setdefault(symbol, []).append(function)
        for call in self.structure.calls:
            self.calls.setdefault(call.owner, []).append(call)
        grouped: dict[tuple[ScriptSymbol, int | None], list[ScriptAssignment]] = {}
        self.write_owners: dict[ScriptSymbol, set[int | None]] = {}
        for symbol, writes in self.writes.items():
            self.write_owners[symbol] = {item.owner for item in writes}
            for item in writes:
                grouped.setdefault((symbol, item.owner), []).append(item)
        self.writes_by_owner = {
            key: (tuple(item.offset for item in rows), tuple(rows))
            for key, rows in grouped.items()
        }

    def active(self, owner: int | None, position: int) -> tuple[str, ...]:
        return tuple(
            item.condition
            for item in self.symbols.control_data(owner)[0]
            if item.start <= position < item.end and item.kind == "if"
        )

    def _write(
        self, symbol: ScriptSymbol, owner: int | None, position: int
    ) -> tuple[ScriptAssignment | None, str]:
        offsets, writes = self.writes_by_owner.get((symbol, owner), ((), ()))
        index = bisect_left(offsets, position) - 1
        owners = self.write_owners.get(symbol, set())
        if index >= 0:
            selected = writes[index]
            controls = self.symbols.control_data(owner)[0]
            contexts = tuple(
                item for item in controls if item.start <= selected.offset < item.end
            )
            if any(item.kind != "if" and item.condition != "do" for item in contexts):
                return None, "循环或块内重赋值，调用时绑定未静态确定"
            if any(not item.start <= position < item.end for item in contexts):
                return None, "分支内重赋值，调用时绑定未静态确定"
            if owners - {owner, None}:
                return None, "其他函数可重赋值此变量，运行时绑定未静态确定"
            return selected, ""
        if owners - {owner, None}:
            return None, "跨函数重赋值，运行时绑定未静态确定"
        globals_ = self.writes_by_owner.get((symbol, None), ((), ()))[1]
        if globals_ and owner is not None:
            if len(globals_) != 1 or self.active(None, globals_[0].offset):
                return None, "全局赋值顺序或分支未静态确定"
            return globals_[0], ""
        return None, ""

    def _rhs_position(self, assignment: ScriptAssignment) -> int:
        return (
            self.assignment_offsets[assignment.offset] - 1
            if assignment.local
            else assignment.offset
        )

    def bound(self, expression: str, owner: int | None, position: int) -> bool:
        symbol = self.symbols.symbol(expression.replace(":", "."), owner, position)
        return (
            symbol[1] >= 0
            or symbol in self.writes
            or symbol in self.definitions
            or expression.startswith("_G.")
            and self.bound("_G", owner, position)
        )

    def _parent_diagnostic(
        self,
        expression: str,
        owner: int | None,
        position: int,
        binding: tuple[int | None, int] | None,
    ) -> str:
        prefixes, _ = reference_parts(expression, lua=self.lua)
        for prefix in prefixes[:-1]:
            symbol = self.symbols.symbol(prefix, owner, position)
            assignment, note = self._write(symbol, owner, position)
            if note:
                return f"父表 {prefix}: {note}"
            if binding is None:
                if assignment or symbol[1] >= 0 or symbol in self.definitions:
                    return f"父表 {prefix} 已被绑定，未假定为标准库"
            elif assignment is not None:
                binding_owner, binding_position = binding
                if (
                    assignment.owner == binding_owner
                    and assignment.offset > binding_position
                ) or (binding_owner is None and assignment.owner is not None):
                    return f"父表 {prefix} 在成员绑定后被替换，未沿用旧函数"
        return ""

    def resolve(
        self, expression: str, start: int, owner: int | None
    ) -> FunctionReference:
        raw = expression.strip()
        value = strip_outer_parentheses(raw)
        start += max(0, raw.find(value))
        # Anonymous callback locations are taken from the source, never guessed by name.
        while (
            wrapper := re.match(
                r"(?:_G\s*\.\s*)?(?:Condition|Filter)\s*\(",
                script_views(value, lua=self.lua).syntax,
            )
        ) is not None:
            args = extract_call_args(script_views(value, lua=self.lua), wrapper.end())
            if len(args) != 1 or not value.endswith(")"):
                break
            argument_start = wrapper.end()
            syntax = script_views(value, lua=self.lua).syntax
            while argument_start < len(syntax) and syntax[argument_start].isspace():
                argument_start += 1
            start += argument_start
            value = strip_outer_parentheses(args[0])
            start += max(0, args[0].find(value))
        if re.match(r"function\s*\(", value):
            function = self.structure.scopes.at(start)
            if function is None or function.start != start:
                function = self.structure.scopes.at(start)
            if function is not None and function.parent == owner:
                return FunctionReference(
                    raw, (function,), "" if function.complete else "回调函数范围未闭合"
                )
        value = re.sub(r"^function\s+", "", value).strip().replace(":", ".")
        seen: set[ScriptSymbol] = set()
        while (
            name := qualified_name(script_views(value, lua=self.lua).syntax)
        ) is not None:
            value = name.replace(":", ".")
            symbol = self.symbols.symbol(value, owner, start)
            if symbol in seen:
                return FunctionReference(raw, (), "函数别名形成循环，静态绑定未确定")
            seen.add(symbol)
            assignment, diagnostic = self._write(symbol, owner, start)
            if diagnostic:
                return FunctionReference(raw, (), diagnostic)
            if assignment is not None:
                diagnostic = self._parent_diagnostic(
                    value, owner, start, (assignment.owner, assignment.offset)
                )
                if diagnostic:
                    return FunctionReference(raw, (), diagnostic)
                atom = self.atoms.assignment(assignment)
                if atom is not None and atom.function is not None:
                    function = atom.function
                    return FunctionReference(
                        raw,
                        (function,),
                        "" if function.complete else "回调函数范围未闭合",
                    )
                value = strip_outer_parentheses(self.atoms.value(assignment))
                value = re.sub(r"^function\s+", "", value).strip()
                owner, start = assignment.owner, self._rhs_position(assignment)
                continue
            candidates = tuple(self.definitions.get(symbol, ()))
            if candidates:
                parent_notes = tuple(
                    self._parent_diagnostic(
                        value, owner, start, (item.parent, item.start)
                    )
                    for item in candidates
                )
                if any(parent_notes):
                    return FunctionReference(
                        raw, (), "; ".join(filter(None, parent_notes))
                    )
                diagnostic = (
                    f"回调同名歧义：{len(candidates)} 个候选，未确定实际绑定"
                    if len(candidates) > 1
                    else ""
                )
                if any(not item.complete for item in candidates):
                    diagnostic = "; ".join(
                        filter(None, (diagnostic, "回调函数范围未闭合"))
                    )
                if any(self.active(item.parent, item.start) for item in candidates):
                    diagnostic = "; ".join(
                        filter(
                            None,
                            (diagnostic, "函数定义处于条件分支，实际绑定须按原文核对"),
                        )
                    )
                return FunctionReference(raw, candidates, diagnostic)
            canonical = symbol[2]
            builtins = {"FourCC"}
            if self.lua is True:
                builtins.update(("select", "table.unpack"))
            if canonical in builtins:
                diagnostic = self._parent_diagnostic(value, owner, start, None)
                if diagnostic:
                    return FunctionReference(raw, (), diagnostic)
                if symbol[1] < 0:
                    return FunctionReference(raw, (), builtin=canonical)
            return FunctionReference(
                raw, (), "未找到回调函数定义；可能来自外部脚本或运行时赋值"
            )
        return FunctionReference(raw, (), "动态回调表达式，静态证据未能确定函数")
