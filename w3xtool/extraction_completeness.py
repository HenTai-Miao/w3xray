"""Extraction completeness diagnostics for MPQ-backed maps."""

from __future__ import annotations

import os
import struct
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from .archive_diagnostics import diagnose_archive_open
from .campaign_sources import open_map_source
from .mpq import FLAG_ENCRYPTED

if TYPE_CHECKING:
    from .archive_source import ArchiveSource


class MapExtractionInput(Protocol):
    path: str
    all_files: list[str]
    archive_source: ArchiveSource | None


class BlockProbe(Protocol):
    flags: int


class ExtractionArchive(Protocol):
    path: str

    def list_files(self) -> Sequence[str]: ...

    def has_file(self, name: str) -> bool: ...

    def iter_blocks(self) -> Iterable[tuple[int, BlockProbe]]: ...

    def block_index_of(self, name: str) -> int | None: ...

    def recover_block_key(self, block: BlockProbe) -> int | None: ...


@dataclass(frozen=True, slots=True)
class ExtractionCompletenessReport:
    source_path: str
    source_readable: bool
    named_file_count: int
    block_count: int | None
    named_block_count: int | None
    anonymous_block_count: int | None
    recoverable_anonymous_count: int | None
    raw_fallback_count: int | None
    listfile_present: bool | None
    import_table_present: bool | None
    warnings: tuple[str, ...]
    notes: tuple[str, ...]
    archive_diagnosis_kind: str = ""

    @property
    def named_coverage_percent(self) -> float | None:
        if self.block_count is None or self.named_block_count is None:
            return None
        if self.block_count == 0:
            return None
        return self.named_block_count / self.block_count * 100


def build_extraction_completeness_report(
    md: MapExtractionInput,
) -> ExtractionCompletenessReport:
    """Build a completeness report from the original archive when available."""
    if md.archive_source is None and (not md.path or not os.path.exists(md.path)):
        diagnosis = diagnose_archive_open(md.path)
        return _fallback_report(
            md.path,
            md.all_files,
            diagnosis.message,
            diagnosis.kind.value,
        )
    try:
        with open_map_source(md) as archive:
            return build_extraction_completeness_from_archive(md, archive)
    except (OSError, ValueError, struct.error) as err:
        diagnosis = diagnose_archive_open(md.path, err)
        return _fallback_report(
            md.path,
            md.all_files,
            diagnosis.message,
            diagnosis.kind.value,
        )
def build_extraction_completeness_from_archive(
    md: MapExtractionInput,
    archive: ExtractionArchive,
) -> ExtractionCompletenessReport:
    """Summarize how many MPQ blocks are covered by known names or fallbacks."""
    names = _unique_sorted(archive.list_files())
    blocks = tuple(archive.iter_blocks())
    valid_block_indexes = {idx for idx, _block in blocks}
    named_block_indexes: set[int] = set()
    for name in names:
        block_index = archive.block_index_of(name)
        if block_index is not None and block_index in valid_block_indexes:
            named_block_indexes.add(block_index)

    anonymous_blocks = tuple(
        (idx, block) for idx, block in blocks if idx not in named_block_indexes
    )
    recoverable = sum(
        1 for _idx, block in anonymous_blocks if _can_export_unknown(archive, block)
    )
    raw_fallback = len(anonymous_blocks) - recoverable
    encrypted_raw = sum(
        1 for _idx, block in anonymous_blocks
        if block.flags & FLAG_ENCRYPTED and not _can_export_unknown(archive, block)
    )
    return ExtractionCompletenessReport(
        source_path=md.path,
        source_readable=True,
        named_file_count=len(names),
        block_count=len(blocks),
        named_block_count=len(named_block_indexes),
        anonymous_block_count=len(anonymous_blocks),
        recoverable_anonymous_count=recoverable,
        raw_fallback_count=raw_fallback,
        listfile_present=archive.has_file("(listfile)"),
        import_table_present=(
            archive.has_file("war3map.imp") or archive.has_file("war3campaign.imp")
        ),
        warnings=_warnings(len(blocks), len(anonymous_blocks), raw_fallback, encrypted_raw),
        notes=_notes(recoverable, raw_fallback, encrypted_raw),
    )


def format_extraction_completeness_report(
    report: ExtractionCompletenessReport,
) -> str:
    """Format diagnostics as a compact user-facing text report."""
    lines = [
        f"源文件：{report.source_path}",
        f"源状态：{'可读取' if report.source_readable else '源文件不可读'}",
        f"命名文件：{report.named_file_count}",
    ]
    if report.block_count is None:
        lines.append("命名覆盖：无法计算")
    else:
        lines.extend((
            f"MPQ 块：{report.block_count}",
            _format_coverage(report),
            f"无名块：{report.anonymous_block_count or 0}",
            f"Unknown 可解包：{report.recoverable_anonymous_count or 0}",
            f"UnknownRaw 兜底：{report.raw_fallback_count or 0}",
            f"(listfile)：{_presence(report.listfile_present)}",
            f"war3map.imp/war3campaign.imp：{_presence(report.import_table_present)}",
        ))
    if report.warnings:
        lines.append("")
        lines.append("警告：")
        lines.extend(f"- {warning}" for warning in report.warnings)
    if report.notes:
        lines.append("")
        lines.append("说明：")
        lines.extend(f"- {note}" for note in report.notes)
    return "\n".join(lines) + "\n"


def _fallback_report(
    source_path: str,
    names: Sequence[str],
    warning: str,
    archive_diagnosis_kind: str,
) -> ExtractionCompletenessReport:
    return ExtractionCompletenessReport(
        source_path=source_path,
        source_readable=False,
        named_file_count=len(_unique_sorted(names)),
        block_count=None,
        named_block_count=None,
        anonymous_block_count=None,
        recoverable_anonymous_count=None,
        raw_fallback_count=None,
        listfile_present=None,
        import_table_present=None,
        warnings=(warning,),
        notes=("只能根据已加载的内部文件清单展示结果；重新选择原始地图可得到块覆盖诊断。",),
        archive_diagnosis_kind=archive_diagnosis_kind,
    )


def _can_export_unknown(archive: ExtractionArchive, block: BlockProbe) -> bool:
    if not block.flags & FLAG_ENCRYPTED:
        return True
    return archive.recover_block_key(block) is not None


def _warnings(
    block_count: int,
    anonymous_count: int,
    raw_fallback: int,
    encrypted_raw: int = 0,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if block_count == 0:
        warnings.append("块表没有可导出的有效块。")
    if anonymous_count:
        warnings.append(f"仍有 {anonymous_count} 个块没有可靠文件名，知识包会放入 未知文件/Unknown/ 或 未知文件/UnknownRaw/。")
    if raw_fallback:
        warnings.append(f"{raw_fallback} 个无名块无法按内容解包，只能保留原始 MPQ 负载。")
    if _looks_protected(block_count, raw_fallback, encrypted_raw):
        warnings.append("疑似数据级加密或运行时解密保护：大量匿名加密块无法通过静态 MPQ 表恢复。")
    return tuple(warnings)


def _notes(recoverable: int, raw_fallback: int, encrypted_raw: int = 0) -> tuple[str, ...]:
    notes = ["命名文件来自 (listfile)、固定地图文件名和地图/战役导入表的并集。"]
    if recoverable:
        notes.append("未知文件/Unknown/ 里的文件是可按块直接解出的无名资源，扩展名按文件头推断。")
    if raw_fallback:
        notes.append("未知文件/UnknownRaw/ 保留无法解密或无法识别的原始块，避免静默丢数据。")
    if encrypted_raw:
        notes.append("对真正数据级加密地图，工具只做静态诊断；请提供未保护文件、作者给出的明文/listfile/key，不执行运行时内存 dump 或绕过。")
    return tuple(notes)


def _looks_protected(block_count: int, raw_fallback: int, encrypted_raw: int) -> bool:
    if encrypted_raw < 8:
        return False
    if block_count == 0:
        return True
    return raw_fallback / block_count >= 0.25


def _format_coverage(report: ExtractionCompletenessReport) -> str:
    if report.block_count is None or report.named_block_count is None:
        return "命名覆盖：无法计算"
    percent = report.named_coverage_percent
    if percent is None:
        return f"命名覆盖：{report.named_block_count}/{report.block_count}"
    return f"命名覆盖：{report.named_block_count}/{report.block_count} ({percent:.1f}%)"


def _presence(value: bool | None) -> str:
    if value is None:
        return "未知"
    return "存在" if value else "缺失"


def _unique_sorted(names: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({name for name in names if name}, key=str.lower))
