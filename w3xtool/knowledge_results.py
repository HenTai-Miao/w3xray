"""Structured outcomes for knowledge-pack publication."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from .presentation_safety import tsv_cell as _tsv


class KnowledgeWriteStatus(StrEnum):
    """Overall publication outcome."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class KnowledgeWriteItem:
    """Final write outcome for one pack-relative path."""

    path: str
    written: bool
    size: int
    error: str | None


@dataclass(frozen=True, slots=True)
class KnowledgeWriteReport:
    """Final write outcomes for a knowledge-pack publication session."""

    items: tuple[KnowledgeWriteItem, ...]

    @property
    def written_count(self) -> int:
        """Return the number of successfully written paths."""
        return sum(item.written for item in self.items)

    @property
    def failed_count(self) -> int:
        """Return the number of paths whose final write failed."""
        return sum(not item.written for item in self.items)

    @property
    def status(self) -> KnowledgeWriteStatus:
        """Classify the session as complete, partial, or failed."""
        if self.failed_count == 0:
            return KnowledgeWriteStatus.COMPLETE
        if self.written_count == 0:
            return KnowledgeWriteStatus.FAILED
        return KnowledgeWriteStatus.PARTIAL

    @property
    def items_by_path(self) -> Mapping[str, KnowledgeWriteItem]:
        """Index final outcomes by their pack-relative path."""
        return {item.path: item for item in self.items}

    @property
    def first_failure(self) -> KnowledgeWriteItem | None:
        """Return the first deterministic failed path, when present."""
        return next((item for item in self.items if not item.written), None)


def format_knowledge_write_report(report: KnowledgeWriteReport) -> str:
    """Format final publication outcomes as TSV."""
    rows = ["路径\t状态\t字节\t错误"]
    for item in report.items:
        rows.append("\t".join((
            _tsv(item.path),
            "已写入" if item.written else "失败",
            str(item.size),
            _tsv(item.error or ""),
        )))
    return "\n".join(rows) + "\n"
