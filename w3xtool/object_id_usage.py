"""Line-level object ID usage clues for investigation exports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .script_scan import _codes_in, scan_all_referenced_codes, scan_object_refs
from .script_sources import analysis_script_texts
from .script_tokens import script_code_text

if TYPE_CHECKING:
    from .api import MapData


@dataclass(frozen=True, slots=True)
class ObjectIdUsage:
    code: str
    source: str
    line: int
    category: str
    channel: str

    @property
    def detail(self) -> str:
        if self.line > 0:
            return f"{self.source}:{self.line}:{self.category}"
        if self.channel:
            return f"{self.source}:{self.channel}:{self.category}"
        return f"{self.source}:{self.category}"


@dataclass(frozen=True, slots=True)
class ObjectIdUsageReport:
    entries: tuple[ObjectIdUsage, ...]
    # 按码预聚合的详情；details_for 原来每个码全量扫 entries，
    # 导出索引时对几千个码是平方级。
    _details_by_code: Mapping[str, tuple[str, ...]] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        collected: dict[str, set[str]] = {}
        for entry in self.entries:
            collected.setdefault(entry.code, set()).add(entry.detail)
        object.__setattr__(
            self,
            "_details_by_code",
            {code: tuple(sorted(values)) for code, values in collected.items()},
        )

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(sorted({entry.code for entry in self.entries}))

    def details_for(self, code: str) -> tuple[str, ...]:
        return self._details_by_code.get(code, ())


def build_object_id_usage(md: MapData) -> ObjectIdUsageReport:
    """Return script-side object ID usage details keyed by rawcode."""
    entries: list[ObjectIdUsage] = []
    for source, text in analysis_script_texts(md):
        category_map = _category_map(text)
        line_entries = tuple(_line_entries(source, text, category_map))
        entries.extend(line_entries)
        explicit_codes = {entry.code for entry in line_entries}
        entries.extend(_implicit_entries(source, category_map, explicit_codes))
        entries.extend(_unclassified_entries(source, text, explicit_codes, set(category_map)))
    return ObjectIdUsageReport(_dedupe(entries))


def code_decimal(code: str) -> int:
    """Return Warcraft 4cc decimal representation."""
    raw = code.encode("latin-1", "ignore")[:4].ljust(4, b"\x00")
    return int.from_bytes(raw, "big")


def _line_entries(
    source: str,
    text: str,
    category_map: Mapping[str, frozenset[str]],
) -> Iterable[ObjectIdUsage]:
    code_text = script_code_text(text)
    for line_no, line in enumerate(code_text.splitlines(), start=1):
        for code in sorted(set(_codes_in(line))):
            yield ObjectIdUsage(
                code=code,
                source=source,
                line=line_no,
                category=_category_for(code, category_map),
                channel="脚本引用",
            )


def _implicit_entries(
    source: str,
    category_map: Mapping[str, frozenset[str]],
    explicit_codes: set[str],
) -> Iterable[ObjectIdUsage]:
    for code, categories in category_map.items():
        if code in explicit_codes:
            continue
        yield ObjectIdUsage(
            code=code,
            source=source,
            line=0,
            category=_category_label(categories),
            channel="脚本隐式",
        )


def _unclassified_entries(
    source: str,
    text: str,
    explicit_codes: set[str],
    classified_codes: set[str],
) -> Iterable[ObjectIdUsage]:
    for code in scan_all_referenced_codes(text) - explicit_codes - classified_codes:
        yield ObjectIdUsage(
            code=code,
            source=source,
            line=0,
            category="未知",
            channel="脚本引用",
        )


def _category_map(text: str) -> Mapping[str, frozenset[str]]:
    by_code: dict[str, set[str]] = {}
    for category, codes in scan_object_refs(text).items():
        for code in codes:
            by_code.setdefault(code, set()).add(category)
    return {code: frozenset(categories) for code, categories in by_code.items()}


def _category_for(code: str, category_map: Mapping[str, frozenset[str]]) -> str:
    return _category_label(category_map.get(code, frozenset()))


def _category_label(categories: frozenset[str]) -> str:
    if len(categories) == 1:
        return next(iter(categories))
    if categories:
        return "/".join(sorted(categories))
    return "未知"


def _dedupe(entries: Iterable[ObjectIdUsage]) -> tuple[ObjectIdUsage, ...]:
    seen: set[ObjectIdUsage] = set()
    result: list[ObjectIdUsage] = []
    for entry in entries:
        if entry in seen:
            continue
        seen.add(entry)
        result.append(entry)
    return tuple(result)
