"""Explicit object export coverage shared by producers and pack consumers."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import io
import os
from pathlib import Path
from typing import TYPE_CHECKING

from .batch_tsv import decode_tsv_cell, format_tsv_rows
from .csv_fields import full_csv_fields
from .extraction_ledger import BlockState
from .pack_query_objects import OBJECT_TABLES

if TYPE_CHECKING:
    from .map_data import MapData


OBJECT_COVERAGE_FILE = "对象来源覆盖.tsv"
OBJECT_COVERAGE_COLUMN = f"来源覆盖表:{OBJECT_COVERAGE_FILE}"
_HEADER = ("记录类型", "分类", "选择状态", "完整性", "来源", "诊断")


@dataclass(frozen=True, slots=True)
class ObjectExportCoverage:
    states: tuple[tuple[str, str], ...]
    diagnostics: tuple[tuple[str, str], ...] = ()

    def for_table(self, category: str = "") -> tuple[str, ...]:
        """Keep every relevant source note and the explicit selection boundary."""
        requested = (category,) if category else OBJECT_TABLES
        states = dict(self.states)
        notes = [
            note for owner, note in self.diagnostics if not owner or owner in requested
        ]
        for name in requested:
            state = states.get(name, "partial")
            if state == "disabled":
                notes.append(f"{name}: 提取配置未选择对象导出；未用缺表证明类别为空。")
            elif state != "complete":
                notes.append(f"{name}: 对象来源完整性未确认；计数仅描述已确认记录。")
        return tuple(dict.fromkeys(notes))


@dataclass(frozen=True, slots=True)
class ObjectCoverageInput:
    path: Path
    coverage: ObjectExportCoverage | None
    identity: tuple[int, int, int, int] | None = None
    digest: str = ""
    error: str = ""

    def verify(self) -> str:
        current = read_object_coverage_input(self.path.parent)
        if (self.identity, self.digest, self.error) == (
            current.identity,
            current.digest,
            current.error,
        ):
            return ""
        return f"{self.path}: 来源覆盖在查询交付前变化；完整性未确认，请刷新。"


def _identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def read_object_coverage_input(pack: Path) -> ObjectCoverageInput:
    """Read fresh bytes; a missing optional legacy sidecar is also observed."""
    path = pack / OBJECT_COVERAGE_FILE
    try:
        if path.is_symlink():
            raise OSError("来源覆盖表为符号链接，未越过资料包路径边界。")
        with path.open("rb") as handle:
            before = _identity(os.fstat(handle.fileno()))
            payload = handle.read()
            after = _identity(os.fstat(handle.fileno()))
        if before != after or after != _identity(path.stat()) or path.is_symlink():
            raise OSError("来源覆盖表在读取期间变化。")
        return ObjectCoverageInput(
            path,
            object_export_coverage_bytes(payload),
            after,
            hashlib.sha256(payload).hexdigest(),
        )
    except FileNotFoundError:
        return ObjectCoverageInput(path, None)
    except OSError as exc:
        message = f"来源覆盖表读取失败: {exc}"
        return ObjectCoverageInput(
            path, ObjectExportCoverage((), (("", message),)), error=message
        )


def format_object_export_coverage(md: MapData, *, selected: bool) -> str:
    """A selected empty table proves zero only with complete source evidence."""
    notes: list[tuple[str, str]] = []
    if md.archive_source is None:
        notes.append(
            (md.path, "未记录已加载的归档来源；不能确认未列出的对象类别为空。")
        )
    elif md.extraction_ledger is None:
        notes.append(
            (md.path, "未记录归档读取台账；仅有来源引用不能证明对象读取完整。")
        )
    notes.extend(
        (
            note.source,
            f"[{note.component}/{note.stage}/{note.severity.value}] {note.message} "
            f"(recoverable={note.recoverable}, exception={note.exception_type or 'none'})",
        )
        for note in md.diagnostics
    )
    if md.extraction_ledger is not None:
        notes.extend(
            (
                entry.internal_path,
                f"[archive/{entry.state.value}] {entry.error_code}: {entry.detail} "
                f"(source={entry.source.value}, declared_size={entry.declared_size}, "
                f"written_size={entry.written_size}, sha256={entry.sha256})",
            )
            for entry in md.extraction_ledger.entries
            if entry.state
            in {BlockState.RAW_ONLY, BlockState.ENCRYPTED_BLOCKED, BlockState.DAMAGED}
        )
        notes.extend((md.path, note) for note in md.extraction_ledger.warnings)
    state = "disabled" if not selected else "partial" if notes else "complete"
    rows = [
        _HEADER,
        *(
            (
                "coverage",
                category,
                "selected" if selected else "disabled",
                state,
                md.path,
                "",
            )
            for category in OBJECT_TABLES
        ),
        *(("diagnostic", "", "", "", source, note) for source, note in notes),
    ]
    return format_tsv_rows(rows)


def object_export_coverage_bytes(payload: bytes) -> ObjectExportCoverage:
    try:
        with full_csv_fields():
            rows = tuple(
                tuple(row)
                for row in csv.reader(
                    io.StringIO(payload.decode("utf-8-sig"), newline=""),
                    delimiter="\t",
                    strict=True,
                )
            )
        return object_export_coverage(rows)
    except (UnicodeError, csv.Error) as exc:
        return ObjectExportCoverage((), (("", f"来源覆盖表读取失败: {exc}"),))


@lru_cache(maxsize=8)
def object_export_coverage(raw: tuple[tuple[str, ...], ...]) -> ObjectExportCoverage:
    """Validate the complete declared schema without guessing missing states."""
    rows = tuple(tuple(decode_tsv_cell(value) for value in row) for row in raw)
    if not rows or rows[0] != _HEADER:
        return ObjectExportCoverage(
            (), (("", f"来源覆盖表缺少完整的已声明表头；原始记录: {raw!r}"),)
        )
    states: dict[str, str] = {}
    notes: list[tuple[str, str]] = []
    for ordinal, row in enumerate(rows[1:], 2):
        if len(row) != len(_HEADER):
            notes.append(("", f"来源覆盖表第 {ordinal} 条记录字段不完整: {row!r}"))
            continue
        kind, category, selection, state, source, message = row
        if kind == "coverage" and category in OBJECT_TABLES:
            if (
                category in states
                or selection not in {"selected", "disabled"}
                or state not in {"complete", "partial", "disabled"}
                or (selection == "disabled") != (state == "disabled")
                or state == "complete"
                and not source
                or message
            ):
                notes.append((category, f"来源覆盖表第 {ordinal} 条状态冲突: {row!r}"))
                states[category] = "partial"
            else:
                states[category] = state
        elif kind == "diagnostic" and (not category or category in OBJECT_TABLES):
            if selection or state or not message:
                notes.append(("", f"来源覆盖表第 {ordinal} 条诊断无效: {row!r}"))
            else:
                notes.append((category, f"{source}: {message}"))
        else:
            notes.append(("", f"来源覆盖表第 {ordinal} 条记录无法确认: {row!r}"))
    for category in OBJECT_TABLES:
        if category not in states:
            notes.append((category, f"来源覆盖表未声明 {category} 的提取状态。"))
    return ObjectExportCoverage(tuple(states.items()), tuple(notes))
