"""Structured diagnostics for war3map.wtg parsing."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable


@dataclass(frozen=True, slots=True)
class UnknownTriggerFunction:
    trigger_name: str
    function_name: str
    function_type: int
    offset: int


@dataclass(frozen=True, slots=True)
class TriggerParseFailure:
    trigger_name: str
    function_name: str
    offset: int
    reason: str


@dataclass(frozen=True, slots=True)
class WtgReadError(Exception):
    offset: int
    reason: str

    def __str__(self) -> str:
        return f"WTG read failed at 0x{self.offset:x}: {self.reason}"


@dataclass(frozen=True, slots=True)
class EcaParseError(Exception):
    trigger_name: str
    function_name: str
    offset: int
    reason: str

    def __str__(self) -> str:
        return f"{self.trigger_name}/{self.function_name} @ 0x{self.offset:x}: {self.reason}"


def format_summary_diagnostics(summary) -> tuple[str, ...]:
    """Return user-facing diagnostic lines for a WTG summary."""
    lines: list[str] = []
    for item in _iter_or_empty(getattr(summary, "missing_schema_functions", ())):
        lines.append(
            "缺少 TriggerData/TriggerStrings：只读取触发器头"
            f"（{item.trigger_name}/{item.function_name} @ 0x{item.offset:x}）"
        )
    for failure in _iter_or_empty(getattr(summary, "parse_failures", ())):
        lines.append(
            "WTG 解析失败："
            f"{failure.trigger_name}/{failure.function_name} @ 0x{failure.offset:x}：{failure.reason}"
        )
    if getattr(summary, "has_unexpanded_functions", False) and not lines:
        lines.append("WTG ECA 未完整展开：缺少结构化诊断。")
    return tuple(lines)


def _iter_or_empty(items: Iterable) -> Iterable:
    return items
