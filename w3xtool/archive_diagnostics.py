"""Bounded, read-only diagnosis for MPQ archive-open failures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import errno
import os
import struct
from typing import BinaryIO, Final

_HEADER: Final = struct.Struct("<4sIIHHIIII")
_MAGIC: Final = b"MPQ\x1a"
_ALIGNMENT: Final = 512
_SCAN_LIMIT: Final = 16 * 1024 * 1024


class ArchiveDiagnosisKind(StrEnum):
    """Conservative outcomes available before an archive is open."""

    MISSING = "missing"
    PERMISSION = "permission"
    READ_ERROR = "read_error"
    NO_HEADER = "no_header"
    TABLE_DAMAGE = "table_damage"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class ArchiveOpenDiagnosis:
    kind: ArchiveDiagnosisKind
    message: str
    evidence: tuple[str, ...]


def diagnose_archive_open(
    path: str,
    error: BaseException | None = None,
) -> ArchiveOpenDiagnosis:
    """Probe aligned MPQ headers without mmap, full-file reads, or payload scans."""
    try:
        with open(path, "rb") as handle:
            file_size = os.fstat(handle.fileno()).st_size
            return _diagnose_readable(handle, path, file_size, error)
    except FileNotFoundError as exc:
        return _diagnosis(
            ArchiveDiagnosisKind.MISSING,
            "原始地图文件不存在，无法进行 MPQ 诊断。",
            path,
            exc,
            error,
        )
    except PermissionError as exc:
        return _diagnosis(
            ArchiveDiagnosisKind.PERMISSION,
            "原始地图文件当前不可读取（权限或占用限制）。",
            path,
            exc,
            error,
        )
    except OSError as exc:
        if _is_permission_error(exc):
            return _diagnosis(
                ArchiveDiagnosisKind.PERMISSION,
                "原始地图文件当前不可读取（权限或占用限制）。",
                path,
                exc,
                error,
            )
        return _diagnosis(
            ArchiveDiagnosisKind.READ_ERROR,
            "读取原始地图文件失败，无法完成有界 MPQ 诊断。",
            path,
            exc,
            error,
        )


def _diagnose_readable(
    handle: BinaryIO,
    path: str,
    file_size: int,
    error: BaseException | None,
) -> ArchiveOpenDiagnosis:
    scan_end = min(file_size, _SCAN_LIMIT)
    first_damage: tuple[str, ...] | None = None
    first_unsupported: tuple[str, ...] | None = None
    offset = 0
    try:
        while offset < scan_end:
            handle.seek(offset)
            raw = handle.read(_HEADER.size)
            if raw[:4] == _MAGIC:
                evidence = _validate_candidate(raw, offset, file_size)
                if "structure=valid" in evidence:
                    return ArchiveOpenDiagnosis(
                        ArchiveDiagnosisKind.READ_ERROR,
                        "MPQ 头和表边界可读，但有界诊断无法确定开档失败原因。",
                        evidence + _error_evidence(error),
                    )
                if any(item.startswith("format_version=") for item in evidence):
                    if first_unsupported is None:
                        first_unsupported = evidence
                elif first_damage is None:
                    first_damage = evidence
            offset += _ALIGNMENT
    except OSError as exc:
        return _diagnosis(
            ArchiveDiagnosisKind.READ_ERROR,
            "读取原始地图文件失败，无法完成有界 MPQ 诊断。",
            path,
            exc,
            error,
        )

    if first_unsupported is not None:
        return ArchiveOpenDiagnosis(
            ArchiveDiagnosisKind.UNSUPPORTED,
            "MPQ 头结构存在，但版本超出当前只读诊断/解析支持范围。",
            first_unsupported + _error_evidence(error),
        )
    if first_damage is not None:
        return ArchiveOpenDiagnosis(
            ArchiveDiagnosisKind.TABLE_DAMAGE,
            "MPQ 头已找到，但 hash/block 表结构损坏、截断或与文件边界不一致。",
            first_damage + _error_evidence(error),
        )
    return ArchiveOpenDiagnosis(
        ArchiveDiagnosisKind.NO_HEADER,
        "未找到可用的 MPQ 头，文件不像可直接读取的 Warcraft III MPQ 地图。",
        (
            f"path={path}",
            f"searched_bytes={scan_end}",
            "alignment=512",
        ) + _error_evidence(error),
    )


def _validate_candidate(raw: bytes, offset: int, file_size: int) -> tuple[str, ...]:
    base = (f"candidate_offset={offset}", f"file_size={file_size}")
    if len(raw) < _HEADER.size:
        return base + ("header_truncated",)
    (
        _magic,
        header_size,
        _archive_size,
        format_version,
        sector_shift,
        hash_pos,
        block_pos,
        hash_count,
        block_count,
    ) = _HEADER.unpack(raw)
    fields = base + (
        f"header_size={header_size}",
        f"hash_count={hash_count}",
        f"block_count={block_count}",
    )
    if sector_shift > 20:
        return fields + (f"sector_shift={sector_shift}", "sector_shift_invalid")
    if hash_count <= 0 or hash_count & (hash_count - 1):
        return fields + ("hash_count_not_power_of_two",)
    hash_start = offset + hash_pos
    hash_end = hash_start + hash_count * 16
    if hash_end > file_size:
        return fields + (
            f"hash_table_start={hash_start}",
            f"hash_table_end={hash_end}",
            "hash_table_oob",
        )
    block_start = offset + block_pos
    if block_start > file_size:
        return fields + (f"block_table_start={block_start}", "block_table_start_oob")
    if format_version != 0:
        return fields + (f"format_version={format_version}",)
    return fields + ("structure=valid",)


def _diagnosis(
    kind: ArchiveDiagnosisKind,
    message: str,
    path: str,
    probe_error: OSError,
    original_error: BaseException | None,
) -> ArchiveOpenDiagnosis:
    evidence = (
        f"path={path}",
        f"os_error={type(probe_error).__name__}",
        f"errno={probe_error.errno}",
    )
    return ArchiveOpenDiagnosis(kind, message, evidence + _error_evidence(original_error))


def _error_evidence(error: BaseException | None) -> tuple[str, ...]:
    if error is None:
        return ()
    return (f"open_error={type(error).__name__}: {error}",)


def _is_permission_error(error: OSError) -> bool:
    permission_errnos = {errno.EACCES, errno.EPERM, errno.EBUSY, errno.ETXTBSY}
    return error.errno in permission_errnos or getattr(error, "winerror", None) in {32, 33}
