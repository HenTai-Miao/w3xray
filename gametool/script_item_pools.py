"""Source-local item-pool definitions, lifecycle evidence and placement snapshots."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from functools import lru_cache
import math
import re
from types import MappingProxyType

from .save_call_context import extract_call_args
from .script_atoms import ScriptAtoms
from .script_assignments import (
    ScriptAssignment,
    reference_parts,
    script_assignments,
)
from .script_control_ranges import ControlRange, control_ranges
from .script_lexing import script_views
from .script_object_literals import literal_object_code
from .script_scopes import CallSpan, ScopeLookup, script_structure, source_line_starts
from .script_symbols import ScriptSymbol as _Symbol, ScriptSymbols

_WEIGHT = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")
_MUTATIONS = frozenset(
    {"ItemPoolAddItemType", "ItemPoolRemoveItemType", "DestroyItemPool"}
)


@dataclass(frozen=True, slots=True)
class PoolMember:
    code: str
    item_expression: str
    weight: str
    offset: int
    line: int
    expression: str


@dataclass(frozen=True, slots=True)
class PoolOperation:
    api: str
    offset: int
    owner: int | None
    line: int
    expression: str
    member: PoolMember | None
    code: str
    diagnostic: str = ""


@dataclass(frozen=True, slots=True)
class PoolSnapshot:
    expression: str
    origin: int
    members: tuple[PoolMember, ...]
    operations: tuple[PoolOperation, ...]
    total_weight: str
    diagnostic: str
    destroyed: bool = False


@dataclass(frozen=True, slots=True)
class ItemPoolIndex:
    placements: Mapping[int, tuple[PoolSnapshot, ...]]


@dataclass(frozen=True, slots=True)
class _Origin:
    offset: int
    owner: int | None
    diagnostic: str = ""


def source_weight_total(members: tuple[PoolMember, ...]) -> tuple[str, str]:
    """Sum finite literal source weights exactly; uncertain inputs remain verbatim."""
    values: list[Decimal] = []
    for member in members:
        if _WEIGHT.fullmatch(member.weight) is None:
            return "", "含动态或算术权重，保留原文，不推导数值总权重"
        try:
            value = Decimal(member.weight)
            approximate = float(value)
        except InvalidOperation, ValueError, OverflowError:
            return "", "权重无法静态求和，保留原文"
        if (
            not value.is_finite()
            or value < 0
            or not math.isfinite(approximate)
            or value
            and approximate == 0
        ):
            return "", "含负权重或超出可验证浮点范围的权重，保留原文"
        values.append(value)
    if not values:
        return "0", ""
    nonzero = [value for value in values if value]
    if not nonzero:
        return "0", "总权重为0，未确认可抽取的正权重成员"
    exponent = min(int(value.as_tuple().exponent) for value in nonzero)
    high = max(value.adjusted() for value in nonzero)
    # Precision follows encoded digits and the finite numerical range, never a
    # fixed display precision. No rounding of long but representable literals.
    precision = max(1, high - exponent + len(str(len(values))) + 2)
    with localcontext() as context:
        context.prec = precision
        total = sum(nonzero, Decimal(0))
    return str(total), "" if total > 0 else "总权重为0，未确认可抽取的正权重成员"


class _Pools:
    def __init__(self, text: str, lua: bool | None) -> None:
        self.text, self.lua = text, lua
        self.views = script_views(text, lua=lua)
        self.structure = script_structure(text, lua=lua)
        self.functions = {item.start: item for item in self.structure.functions}
        self.lines = source_line_starts(text)
        self.atoms = ScriptAtoms(text, self.structure, lua=lua)
        self.symbols = ScriptSymbols(text, self.structure, lua=lua)
        self.controls: dict[int | None, ScopeLookup[ControlRange]] = {}
        self.assignments: dict[_Symbol, list[ScriptAssignment]] = {}
        self.origins: dict[int, _Origin] = {}
        self.creation: dict[ScriptAssignment, int] = {}
        self.unknown: dict[tuple[_Symbol, int], int] = {}
        for assignment in script_assignments(text, lua=lua):
            if assignment.start in self.symbols.loop_targets:
                continue
            symbol = self.symbol(assignment.target, assignment.owner, assignment.start)
            self.assignments.setdefault(symbol, []).append(assignment)
            call = self.rhs_call(assignment)
            if call is not None and call.name.removeprefix("_G.") == "CreateItemPool":
                self.creation[assignment] = call.start
                self.origins[call.start] = _Origin(
                    call.start, call.owner, self.control(call.owner, call.start)
                )

        self.by_owner: dict[
            tuple[_Symbol, int | None],
            tuple[tuple[int, ...], tuple[ScriptAssignment, ...]],
        ] = {}
        groups: dict[tuple[_Symbol, int | None], list[ScriptAssignment]] = {}
        for symbol, values in self.assignments.items():
            for assignment in values:
                groups.setdefault((symbol, assignment.owner), []).append(assignment)
        for key, values in groups.items():
            self.by_owner[key] = (
                tuple(value.offset for value in values),
                tuple(values),
            )

    def symbol(self, expression: str, owner: int | None, position: int) -> _Symbol:
        return self.symbols.symbol(expression, owner, position)

    def control_range(self, owner: int | None, position: int) -> ControlRange | None:
        lookup = self.controls.get(owner)
        if lookup is None:
            ranges = control_ranges(
                self.text,
                self.functions[owner] if owner is not None else None,
                self.structure,
                self.lua,
            )
            lookup = ScopeLookup((item.start, item.end, item) for item in ranges)
            self.controls[owner] = lookup
        return lookup.at(position)

    def control(self, owner: int | None, position: int) -> str:
        context = self.control_range(owner, position)
        return context.kind + ": " + context.condition if context is not None else ""

    def uncertain_assignment(
        self, assignment: ScriptAssignment, call: CallSpan
    ) -> bool:
        context = self.control_range(assignment.owner, assignment.offset)
        return context is not None and not (
            assignment.owner == call.owner and context.start <= call.start < context.end
        )

    def rhs_call(self, assignment: ScriptAssignment) -> CallSpan | None:
        atom = self.atoms.assignment(assignment)
        return atom.call if atom is not None else None

    def resolve(self, expression: str, call: CallSpan) -> tuple[tuple[int, ...], str]:
        parts, diagnostic = reference_parts(expression, lua=self.lua)
        symbol = self.symbol(expression, call.owner, call.start)
        choices = self.assignments.get(symbol, ())
        # Replacing a parent table invalidates members held by that table.
        candidates: list[ScriptAssignment] = []
        for prefix in (*parts[:-1], expression):
            offsets, values = self.by_owner.get(
                (self.symbol(prefix, call.owner, call.start), call.owner), ((), ())
            )
            stop = bisect_right(offsets, call.start - 1)
            if not stop:
                continue
            baseline = stop - 1
            while baseline > 0 and self.uncertain_assignment(values[baseline], call):
                baseline -= 1
            candidates.extend(values[baseline:stop])
        candidates.sort(key=lambda assignment: assignment.offset)
        notes = [diagnostic] if diagnostic else []
        if candidates:
            baseline = len(candidates) - 1
            while baseline > 0 and self.uncertain_assignment(
                candidates[baseline], call
            ):
                baseline -= 1
            relevant = candidates[baseline:]
            if len(relevant) > 1 or self.uncertain_assignment(relevant[-1], call):
                notes.append("池变量含条件/循环赋值，保留各候选定义")
        else:
            relevant = list(choices)
            if relevant:
                notes.append("跨函数或闭包池定义，执行时序未验证")
        origins = tuple(
            dict.fromkeys(
                self.creation[assignment]
                for assignment in relevant
                if assignment in self.creation
            )
        )
        if relevant and any(assignment not in self.creation for assignment in relevant):
            notes.append("池变量另有无法解析的赋值，实际池身份未确定")
        if len(origins) > 1:
            notes.append(f"同一池引用有{len(origins)}个定义候选，不合并成确定池")
        if not origins:
            period = relevant[-1].offset if relevant else -1
            origin = self.unknown.setdefault((symbol, period), -len(self.unknown) - 1)
            self.origins.setdefault(
                origin,
                _Origin(
                    origin,
                    call.owner,
                    "未定位CreateItemPool定义，按句柄表达式保留登记候选",
                ),
            )
            origins = (origin,)
        return origins, "; ".join(dict.fromkeys(notes))


@lru_cache(maxsize=8)
def item_pool_index(text: str, *, lua: bool | None = None) -> ItemPoolIndex:
    analysis = _Pools(text, lua)
    operations: dict[int, list[PoolOperation]] = {}
    placements: list[tuple[CallSpan, str, tuple[int, ...], str]] = []
    for call in analysis.structure.calls:
        api = call.name.removeprefix("_G.")
        if api not in _MUTATIONS and api != "PlaceRandomItem":
            continue
        args = extract_call_args(analysis.views, call.open + 1)
        if not args or not call.complete:
            continue
        origins, diagnostic = analysis.resolve(args[0], call)
        if api == "PlaceRandomItem":
            placements.append((call, args[0], origins, diagnostic))
            continue
        expression = text[call.start : call.end]
        code = literal_object_code(args[1].removeprefix("_G.")) if len(args) > 1 else ""
        line = bisect_right(analysis.lines, call.start)
        member = (
            PoolMember(code, args[1], args[2], call.start, line, expression)
            if api == "ItemPoolAddItemType" and len(args) == 3
            else None
        )
        controlled = analysis.control(call.owner, call.start)
        if controlled:
            diagnostic = "; ".join(
                filter(None, (diagnostic, "条件/循环登记: " + controlled))
            )
        operation = PoolOperation(
            api, call.start, call.owner, line, expression, member, code, diagnostic
        )
        for origin in origins:
            operations.setdefault(origin, []).append(operation)
    result: dict[int, tuple[PoolSnapshot, ...]] = {}
    timelines = {
        origin: (
            tuple(values),
            tuple(operation.offset for operation in values),
            any(
                operation.owner != analysis.origins[origin].owner
                for operation in values
            ),
        )
        for origin, values in operations.items()
    }
    cache: dict[tuple[int, int | None, int, str, str], PoolSnapshot] = {}
    for call, expression, origins, placement_note in placements:
        snapshots: list[PoolSnapshot] = []
        for origin_id in origins:
            origin = analysis.origins[origin_id]
            all_ops, offsets, foreign = timelines.get(origin_id, ((), (), False))
            stop = (
                bisect_right(offsets, call.start - 1)
                if call.owner == origin.owner and not foreign
                else len(all_ops)
            )
            key = (origin_id, call.owner, stop, placement_note, expression)
            snapshot = cache.get(key)
            if snapshot is None:
                selected = all_ops[:stop]
                notes = [note for note in (origin.diagnostic, placement_note) if note]
                uncertain = (
                    origin_id < 0
                    or foreign
                    or bool(origin.diagnostic)
                    or any(operation.diagnostic for operation in selected)
                )
                if foreign:
                    notes.append("奖池在多个函数中修改，执行顺序未确定")
                members: list[PoolMember] = []
                destroyed = False
                for operation in selected:
                    if operation.diagnostic:
                        notes.append(operation.diagnostic)
                    if operation.member is not None:
                        members.append(operation.member)
                    elif (
                        not uncertain
                        and operation.api == "ItemPoolRemoveItemType"
                        and operation.code
                    ):
                        members = [
                            member
                            for member in members
                            if member.code != operation.code
                        ]
                    elif not uncertain and operation.api == "DestroyItemPool":
                        members.clear()
                        destroyed = True
                        notes.append("放置前已销毁奖池，未确认可生成物品")
                    elif (
                        operation.api == "ItemPoolRemoveItemType" and not operation.code
                    ):
                        uncertain = True
                        notes.append("动态移除对象，活动成员未确定")
                if destroyed and members:
                    uncertain = True
                    notes.append("销毁后仍有登记调用，保留原文，不推导有效池")
                known = [member.code for member in members if member.code]
                if len(known) != len(set(known)):
                    uncertain = True
                    notes.append("同一物品重复登记，覆盖/累计语义未确认，不推导总权重")
                if any(not member.code for member in members):
                    uncertain = True
                    notes.append("含动态物品码，候选成员未完全确定")
                total, weight_note = (
                    source_weight_total(tuple(members))
                    if not uncertain and not destroyed
                    else ("", "")
                )
                if weight_note:
                    notes.append(weight_note)
                snapshot = PoolSnapshot(
                    expression,
                    origin_id,
                    tuple(members),
                    selected,
                    total,
                    "; ".join(dict.fromkeys(notes)),
                    destroyed,
                )
                cache[key] = snapshot
            snapshots.append(snapshot)
        result[call.start] = tuple(snapshots)
    return ItemPoolIndex(MappingProxyType(result))


def format_pool_snapshot(
    snapshot: PoolSnapshot, name_of: Callable[[str], str], number: int
) -> list[str]:
    known = {member.code for member in snapshot.members if member.code}
    lines = [
        f"  奖池{number}: {snapshot.expression}; 定义偏移 {snapshot.origin}; 候选登记{len(snapshot.members)}项 / {len(known)}种ID（随机抽取，非全部同时产出）"
    ]
    if snapshot.diagnostic:
        lines.append("    奖池诊断: " + snapshot.diagnostic)
    lines.append(
        "    原文总权重: " + (snapshot.total_weight or "未静态确定，见各登记原文")
    )
    for member in snapshot.members:
        if member.code == "\x00\x00\x00\x00":
            label = "空物品ID[0]（抽中时可能不生成有效物品）"
        elif member.code:
            code = member.code if member.code.isprintable() else repr(member.code)
            label = (
                (
                    f"{name_of(member.code)}[{code}]"
                    if name_of(member.code) != member.code
                    else f"[{code}]"
                )
                if member.code.isprintable()
                else f"物品ID[{code}]"
            )
        else:
            label = "动态物品码: " + member.item_expression
        ratio = (
            f" / {snapshot.total_weight}"
            if snapshot.total_weight and snapshot.total_weight != "0"
            else ""
        )
        lines.append(
            f"    成员: {label}; 原文权重 {member.weight}{ratio}; 登记第{member.line}行 / 偏移{member.offset}"
        )
    for operation in snapshot.operations:
        lines.append(
            f"    池操作 第{operation.line}行 / 偏移{operation.offset}: {operation.expression}"
        )
    return lines
