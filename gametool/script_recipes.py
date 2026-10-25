"""Source-bearing recipe operations and explicit formula declarations."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re

from .save_call_context import extract_call_args
from .script_lexing import script_views
from .script_object_literals import literal_object_code
from .script_sources import script_language

_REMOVALS = {"RemoveItem": 0, "UnitRemoveItem": 1, "UnitRemoveItemSwapped": 0}
_OUTPUTS = {
    "CreateItem": 0,
    "CreateItemLoc": 0,
    "BlzCreateItemWithSkin": 0,
    "UnitAddItemById": 1,
    "UnitAddItemByIdSwapped": 0,
}
_ITEM_LOOKUPS = {
    **_OUTPUTS,
    "GetItemOfTypeFromUnitBJ": 1,
    "GetItemOfTypeFromUnit": 1,
    "GetItemOfType": 1,
    "YDWEGetItemOfType": 1,
    "YDWEGetItemOfTypeFromUnitBJ": 1,
}
_CALL_NAMES = "|".join((*_REMOVALS, *_OUTPUTS, "YDWENewItemsFormula"))
_EVENT = re.compile(
    r"\b(?:(?P<call>" + _CALL_NAMES + r")\s*\(|"
    r"(?P<block>function|endfunction|if|endif|loop|endloop|for|while|do|repeat|until|end)\b)"
)
_HEADER = re.compile(r"\s*(?:([A-Za-z_]\w*(?:[.:][A-Za-z_]\w*)*)\s*)?(\(|takes\b)")
_WRAPPER = re.compile(r"([A-Za-z_]\w*)\s*\(")
_PARENS = re.compile(r"[()]")
_COUNT = re.compile(r"[+-]?\s*(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


@dataclass
class Recipe:
    ingredients: list[str]
    result: str
    func: str = ""
    source: str = ""
    line: int = 0
    confidence: str = "已确认"
    evidence: str = ""
    offset: int = 0
    unresolved_reason: str = ""


@dataclass(frozen=True, slots=True)
class ScriptFormula:
    result: str
    ingredients: tuple[tuple[str, int], ...]
    func: str
    source: str
    line: int
    evidence: str
    offset: int


@dataclass(frozen=True, slots=True)
class _Scope:
    name: str = ""
    identity: int = 0
    control_base: int = 0


@dataclass(frozen=True, slots=True)
class _Call:
    name: str
    arguments: tuple[str, ...]
    scope: _Scope
    conditional: bool
    line: int
    offset: int
    evidence: str


@dataclass
class _Materials:
    codes: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    inferred: bool = False
    unknown: bool = False


def _closing_parens(syntax: str) -> dict[int, int]:
    opened: list[int] = []
    closed: dict[int, int] = {}
    for match in _PARENS.finditer(syntax):
        if match.group() == "(":
            opened.append(match.start())
        elif opened:
            closed[opened.pop()] = match.start()
    return closed


def _calls(script: str, *, lua: bool | None) -> Iterator[_Call]:
    """Walk source order and function scopes without recursion or line limits."""
    views = script_views(script, lua=lua)
    syntax = views.syntax
    closed = _closing_parens(syntax)
    line_starts = [0, *(match.end() for match in re.finditer("\n", script))]
    # A function saves its parent scope; other entries own a control-flow end.
    blocks: list[tuple[str, _Scope | None]] = []
    current = _Scope()
    identity = control_depth = cursor = 0

    def pop() -> None:
        nonlocal current, control_depth
        kind, parent = blocks.pop()
        if kind == "function":
            assert parent is not None
            current = parent
        else:
            control_depth -= 1

    while (match := _EVENT.search(syntax, cursor)) is not None:
        cursor = match.end()
        name = match.group("call")
        if name:
            end = closed.get(match.end() - 1)
            if end is None:
                continue
            yield _Call(
                name,
                extract_call_args(views, match.end()),
                current,
                control_depth > current.control_base,
                bisect_right(line_starts, match.start()),
                match.start(),
                script[match.start() : end + 1],
            )
            # Nested item construction belongs to its consuming outer call.
            cursor = end + 1
            continue
        token = match.group("block")
        if token == "function":
            header = _HEADER.match(syntax, match.end())
            if header is None:
                continue  # JASS's `function Handler` reference is not a body.
            is_lua = header.group(2) == "("
            if lua is False and is_lua:
                continue
            identity += 1
            blocks.append(("function", current))
            current = _Scope(
                header.group(1) or f"<匿名@{match.start()}>", identity, control_depth
            )
            cursor = (
                closed.get(header.end() - 1, header.end() - 1) + 1
                if is_lua
                else header.end()
            )
        elif token in {"if", "loop", "for", "while", "repeat"}:
            blocks.append((token, None))
            control_depth += 1
        elif token == "do" and lua is not False:
            if blocks and blocks[-1][0] in {"for", "while"}:
                blocks[-1] = ("do", None)
            else:
                blocks.append(("do", None))
                control_depth += 1
        elif token == "endfunction":
            while blocks:
                kind = blocks[-1][0]
                pop()
                if kind == "function":
                    break
        elif blocks and (
            (token == "end" and lua is not False and blocks[-1][0] != "repeat")
            or (token == "endif" and blocks[-1][0] == "if")
            or (token == "endloop" and blocks[-1][0] == "loop")
            or (token == "until" and blocks[-1][0] == "repeat")
        ):
            pop()


def _item_code(expression: str, *, lua: bool | None) -> str:
    """Follow known item wrappers using their object-ID argument positions."""
    while expression:
        literal = literal_object_code(expression)
        if literal:
            return literal
        wrapper = _WRAPPER.match(expression)
        if wrapper is None or wrapper.group(1) not in _ITEM_LOOKUPS:
            return ""
        views = script_views(expression, lua=lua)
        if _closing_parens(views.syntax).get(wrapper.end() - 1) != len(expression) - 1:
            return ""
        args = extract_call_args(views, wrapper.end())
        index = _ITEM_LOOKUPS[wrapper.group(1)]
        expression = args[index] if index < len(args) else ""
    return ""


def scan_recipes(
    script: str, *, source: str = "", lua: bool | None = None
) -> list[Recipe]:
    """Retain single-material upgrades and every sequential consume/create call.

    Branch/loop-dependent operations and unresolved consumptions remain marked
    as inferred. This static evidence does not execute or prove runtime paths.
    """
    lua = script_language(source) if lua is None else lua
    pending: dict[int, _Materials] = {}
    recipes: list[Recipe] = []
    for call in _calls(script, lua=lua):
        if call.name in _REMOVALS:
            materials = pending.setdefault(call.scope.identity, _Materials())
            index = _REMOVALS[call.name]
            code = (
                _item_code(call.arguments[index], lua=lua)
                if index < len(call.arguments)
                else ""
            )
            if code:
                materials.codes.append(code)
            materials.evidence.append(call.evidence)
            materials.inferred |= call.conditional
            materials.unknown |= not code
        elif call.name in _OUTPUTS:
            materials = pending.pop(call.scope.identity, None)
            index = _OUTPUTS[call.name]
            result = (
                literal_object_code(call.arguments[index])
                if index < len(call.arguments)
                else ""
            )
            if materials is None or not materials.codes or not result:
                continue
            reasons: list[str] = []
            if materials.unknown:
                reasons.append("存在动态消耗参数，所列材料未必完整")
            if materials.inferred or call.conditional:
                reasons.append("消耗或产出位于条件/循环内，需结合执行路径核实")
            recipes.append(
                Recipe(
                    materials.codes,
                    result,
                    call.scope.name,
                    source,
                    call.line,
                    "可推断" if reasons else "已确认",
                    "\n".join((*materials.evidence, call.evidence)),
                    call.offset,
                    "；".join(reasons),
                )
            )
    return recipes


def _count(expression: str) -> int | None:
    expression = expression.strip()
    while expression.startswith("(") and expression.endswith(")"):
        if _closing_parens(expression).get(0) != len(expression) - 1:
            break
        expression = expression[1:-1].strip()
    try:
        if re.fullmatch(r"\$[0-9a-fA-F]+", expression):
            return int(expression[1:], 16)
        if re.fullmatch(r"0[xX][0-9a-fA-F]+", expression):
            return int(expression, 16)
        if not _COUNT.fullmatch(expression):
            return None
        number = Decimal(re.sub(r"^([+-])\s+", r"\1", expression))
        return int(number) if number == number.to_integral_value() else None
    except ValueError, InvalidOperation, OverflowError:
        return None


def formula_from_arguments(
    args: tuple[str, ...],
) -> tuple[str, tuple[tuple[str, int], ...]] | None:
    """Decode a complete formula without expanding repeated ingredients."""
    if len(args) < 3 or len(args) % 2 != 1:
        return None
    result = literal_object_code(args[-1])
    if not result:
        return None
    pairs: dict[str, int] = {}
    for index in range(0, len(args) - 1, 2):
        count = _count(args[index + 1])
        if count is None:
            return None
        if count <= 0:
            continue
        code = literal_object_code(args[index])
        if not code:
            return None
        pairs[code] = pairs.get(code, 0) + count
    return (result, tuple(pairs.items())) if pairs else None


def scan_formulas(
    script: str, *, source: str = "", lua: bool | None = None
) -> list[ScriptFormula]:
    """Read complete YDWE formulas; counts remain compact exact integers."""
    lua = script_language(source) if lua is None else lua
    formulas: list[ScriptFormula] = []
    for call in _calls(script, lua=lua):
        if call.name != "YDWENewItemsFormula":
            continue
        parsed = formula_from_arguments(call.arguments)
        if parsed is not None:
            result, pairs = parsed
            formulas.append(
                ScriptFormula(
                    result,
                    pairs,
                    call.scope.name,
                    source,
                    call.line,
                    call.evidence,
                    call.offset,
                )
            )
    return formulas
