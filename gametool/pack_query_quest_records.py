"""Source-declared quest/message calls over complete script-string records."""

from collections.abc import Iterable, Iterator
from itertools import chain
import re

from .pack_query_text_records import TextRecord

# Standard definitions, read as source rather than executed:
# https://jass.sourceforge.net/doc/api/common_j-source.shtml
# https://jass.sourceforge.net/doc/api/Blizzard_j-source.shtml
QUEST_TEXT_APIS = frozenset(
    """CreateQuestBJ QuestSetTitle QuestSetTitleBJ
QuestSetDescription QuestSetDescriptionBJ CreateQuestItemBJ
QuestItemSetDescription QuestItemSetDescriptionBJ QuestMessageBJ
CreateDefeatConditionBJ DefeatConditionSetDescription DefeatConditionSetDescriptionBJ
DisplayTextToPlayer DisplayTimedTextToPlayer DisplayTimedTextFromPlayer
DisplayTextToForce DisplayTimedTextToForce""".split()
)
_CALL_HEADERS = frozenset(("调用", "call", "api", "call_name"))
_SOURCE_HEADERS = frozenset(("来源", "source", "source_file"))
_LINE_HEADERS = frozenset(("行号", "line", "line_number"))
_OTHER_HEADERS = frozenset(
    (
        "函数",
        "function",
        "字符串",
        "解析文本",
        "文本",
        "text",
        "value",
        "resolved",
        "摘要",
        "summary",
    )
)
_HEADERS = _CALL_HEADERS | _SOURCE_HEADERS | _LINE_HEADERS | _OTHER_HEADERS
_CALLEE = re.compile(r"(?:_G\.)?[A-Za-z_][A-Za-z_0-9]*\Z")


def _standard_call(value: str) -> bool:
    return value.strip().removeprefix("_G.") in QUEST_TEXT_APIS


def _legacy_column(cells: tuple[str, ...]) -> int | None:
    if len(cells) == 2 and _CALLEE.fullmatch(cells[0].strip()):
        return 0
    if len(cells) >= 2 and cells[1].strip().isdecimal():
        if len(cells) == 4:
            return 2
        if len(cells) >= 8:
            return 3
    return None


def _declared_column(cells: tuple[str, ...]) -> tuple[bool, int | None, str]:
    legacy = _legacy_column(cells)
    if legacy is not None and (len(cells) != 2 or _standard_call(cells[0])):
        return False, None, ""
    names = tuple(value.strip().casefold() for value in cells)
    columns = [index for index, name in enumerate(names) if name in _CALL_HEADERS]
    header = bool(columns) or (
        any(name in _SOURCE_HEADERS for name in names)
        and any(name in _LINE_HEADERS for name in names)
    )
    if not header:
        return False, None, ""
    if sum(name in _HEADERS for name in names) < 2:
        return (
            True,
            None,
            "首记录的表头/数据边界不明确；未猜测调用列，请添加明确的调用与文本表头。",
        )
    if not columns:
        return (
            True,
            None,
            "表头缺少调用列；未猜测调用身份，请添加 调用/call/api 列，不以外层函数或正文代替。",
        )
    if len(columns) != 1:
        return (
            True,
            None,
            (
                "表头有重复调用列（第 "
                + ", ".join(str(index + 1) for index in columns)
                + " 列）；未猜测调用列，请核对表头。"
            ),
        )
    return True, columns[0], ""


class QuestRecordReader:
    """Stream confirmed calls; disclose every unclassifiable logical record."""

    def __init__(self, records: Iterable[TextRecord]) -> None:
        self._records = iter(records)
        self.diagnostics: list[str] = []

    def __iter__(self) -> Iterator[TextRecord]:
        indexed = enumerate(self._records, 1)
        first = next(
            (pair for pair in indexed if any(value.strip() for value in pair[1].cells)),
            None,
        )
        if first is None:
            return
        declared, column, note = _declared_column(first[1].cells)
        if note:
            self.diagnostics.append(note)
        rows = indexed if declared else chain((first,), indexed)
        bad: list[int] = []
        for index, record in rows:
            if not any(value.strip() for value in record.cells):
                continue
            if declared and column is None:
                # Still consume the source so its parsing diagnostics survive.
                continue
            call_column = column if declared else _legacy_column(record.cells)
            if call_column is None or call_column >= len(record.cells):
                bad.append(index)
                continue
            if _standard_call(record.cells[call_column]):
                yield record
        if bad:
            self.diagnostics.append(
                f"有 {len(bad)} 条记录缺少调用列或不符合已知旧格式；记录序号: "
                + ", ".join(map(str, bad))
                + "；未猜测调用列，可用 text <词> 查完整原文或补充明确表头。"
            )
