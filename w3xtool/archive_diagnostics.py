"""Bounded, read-only diagnosis for MPQ archive-open failures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import errno
import os
from typing import BinaryIO, Final

from .archive_layout_probe import MPQ_HEADER, validate_mpq_candidate
from .mpq_constants import WAR3_MAP_MAGIC
from .mpq_storage import open_regular_binary

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
    if os.path.isdir(path):
        return ArchiveOpenDiagnosis(
            ArchiveDiagnosisKind.READ_ERROR,
            "原始地图路径不是可读取的普通文件，无法完成有界 MPQ 诊断。",
            (f"path={path}", "path_type=directory") + _error_evidence(error),
        )
    try:
        handle, file_size = open_regular_binary(path)
        with handle:
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
    war3_map = False
    offset = 0
    try:
        while offset < scan_end:
            handle.seek(offset)
            raw = handle.read(MPQ_HEADER.size)
            if offset == 0:
                war3_map = raw[:4] == WAR3_MAP_MAGIC
            if raw[:4] == _MAGIC:
                evidence = validate_mpq_candidate(
                    raw,
                    offset,
                    file_size,
                    war3_map=war3_map,
                )
                if "structure=valid" in evidence:
                    return ArchiveOpenDiagnosis(
                        ArchiveDiagnosisKind.READ_ERROR,
                        "MPQ 头和表边界可读，但有界诊断无法确定开档失败原因。",
                        evidence + _error_evidence(error),
                    )
                if "format_unsupported" in evidence:
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
