"""控制命令 / Order 分析：检测命令串引用与冲突。"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from .order_ids import order_name_from_id

if TYPE_CHECKING:
    from .api import GameObject, MapData

_ISSUE_ORDER_RE: Final = re.compile(
    r"\bIssue(?:Immediate|Point|Target|NeutralImmediate|NeutralPoint|NeutralTarget)"
    r"Order(?:BJ)?\s*\([^\"\n]*\"([A-Za-z0-9_]+)\"",
)
_ISSUE_ORDER_ID_RE: Final = re.compile(
    r"\bIssue(?:Immediate|Point|Target|NeutralImmediate|NeutralPoint|NeutralTarget)"
    r"OrderById\s*\(([^)\n]*)\)",
)
_ORDER_ID_RE: Final = re.compile(r"\b(85\d{4})\b")
_EMPTY_ORDERS: Final = {"", "_", "none", "null", "0", "0000"}

@dataclass(frozen=True, slots=True)
class OrderUse:
    order: str
    source: str
    detail: str
    object_id: str = ""


@dataclass(frozen=True, slots=True)
class OrderCollision:
    order: str
    uses: tuple[OrderUse, ...]


@dataclass(frozen=True, slots=True)
class OrderReport:
    uses: tuple[OrderUse, ...]
    collisions: tuple[OrderCollision, ...]

    @property
    def by_order(self) -> dict[str, tuple[OrderUse, ...]]:
        grouped: dict[str, list[OrderUse]] = defaultdict(list)
        for use in self.uses:
            grouped[use.order].append(use)
        return {order: tuple(items) for order, items in sorted(grouped.items())}


def build_order_report(md: MapData) -> OrderReport:
    """构建命令串报告；只读取对象字段和脚本文本。"""
    uses: list[OrderUse] = []
    for obj in _all_objects(md):
        uses.extend(_object_order_uses(obj))
    for script_name, text in sorted(md.scripts.items()):
        uses.extend(_script_order_uses(script_name, text))
    ordered_uses = tuple(sorted(uses, key=lambda use: (use.order, use.source, use.detail)))
    return OrderReport(ordered_uses, _collisions(ordered_uses))


def _all_objects(md: MapData) -> list[GameObject]:
    return [obj for group in md.objects.values() for obj in group]


def _object_order_uses(obj: GameObject) -> tuple[OrderUse, ...]:
    out: list[OrderUse] = []
    for label, value in obj.fields:
        if not _is_order_label(str(label)):
            continue
        order = _normalize_order(str(value))
        if order in _EMPTY_ORDERS:
            continue
        out.append(OrderUse(order, f"对象 {obj.obj_id}", f"{obj.name} · {label}", obj.obj_id))
    return tuple(out)


def _script_order_uses(script_name: str, text: str) -> tuple[OrderUse, ...]:
    out: list[OrderUse] = []
    for match in _ISSUE_ORDER_RE.finditer(text):
        order = _normalize_order(match.group(1))
        if order in _EMPTY_ORDERS:
            continue
        out.append(OrderUse(order, f"脚本 {script_name}", "IssueOrder 字符串"))
    for match in _ISSUE_ORDER_ID_RE.finditer(text):
        id_match = _ORDER_ID_RE.search(match.group(1))
        if id_match is None:
            continue
        order_id = id_match.group(1)
        order = order_name_from_id(order_id)
        out.append(OrderUse(order, f"脚本 {script_name}", f"IssueOrderById {order_id}"))
    return tuple(out)


def _collisions(uses: tuple[OrderUse, ...]) -> tuple[OrderCollision, ...]:
    by_order: dict[str, list[OrderUse]] = defaultdict(list)
    for use in uses:
        if not use.object_id:
            continue
        by_order[use.order].append(use)
    collisions: list[OrderCollision] = []
    for order, items in sorted(by_order.items()):
        object_ids = {item.object_id for item in items}
        if len(object_ids) < 2:
            continue
        collisions.append(OrderCollision(order, tuple(items)))
    return tuple(collisions)


def _is_order_label(label: str) -> bool:
    lowered = label.lower()
    return "命令串" in label or "orderstring" in lowered or lowered == "order"


def _normalize_order(value: str) -> str:
    return value.strip().strip('"').strip("'").lower()
