"""File identity and complete-payload proofs for publishing new reports."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat

from . import windows_output_paths
from .windows_output_paths import native_output_path


def report_parent_proof(destination: Path) -> tuple[tuple[str, int, int], ...]:
    """Capture every ordinary output ancestor without following reparse points."""
    proof: list[tuple[str, int, int]] = []
    for parent in reversed(destination.parents):
        value = os.lstat(native_output_path(str(parent)))
        if (
            not stat.S_ISDIR(value.st_mode)
            or getattr(value, "st_file_attributes", 0)
            & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError(f"报告父目录不是独立普通目录: {parent}")
        proof.append((str(parent), value.st_dev, value.st_ino))
    return tuple(proof)


def report_metadata(details: os.stat_result) -> tuple[int, ...]:
    """Keep the complete metadata used to compare held and named file identity."""
    return (
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
        details.st_mode,
    )


def require_report_payload(
    path: str,
    descriptor: int,
    expected: tuple[int, ...],
    expected_sha256: str,
    *,
    expected_named: tuple[int, ...] | None = None,
    allow_link_change_time: bool = False,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Bind one name to the held descriptor and verify the complete payload."""
    before = report_metadata(os.fstat(descriptor))
    named = os.lstat(native_output_path(path))
    named_metadata = report_metadata(named)
    if (
        (
            before != expected
            and not (
                allow_link_change_time
                and before[:4] + before[5:] == expected[:4] + expected[5:]
            )
        )
        or (expected_named is not None and named_metadata != expected_named)
        or not stat.S_ISREG(named.st_mode)
        or getattr(named, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        or named_metadata[:4] + named_metadata[5:] != before[:4] + before[5:]
    ):
        raise OSError(f"报告文件身份或元数据变化，未确认完整发布: {path}")
    _ = os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    total = 0
    while data := os.read(descriptor, 1024 * 1024):
        digest.update(data)
        total += len(data)
    if (
        report_metadata(os.fstat(descriptor)) != before
        or report_metadata(os.lstat(native_output_path(path))) != named_metadata
        or total != expected[2]
        or digest.hexdigest() != expected_sha256
    ):
        raise OSError(f"报告完整 payload/元数据复验失败，未确认成功发布: {path}")
    return before, named_metadata


def cleanup_report_paths(
    paths: tuple[str, ...], expected: tuple[int, int]
) -> tuple[str, ...]:
    """Remove only owned files and retain diagnostics for replaced names."""
    retained: list[str] = []
    for path in paths:
        try:
            removed = windows_output_paths.remove_owned_output(path, expected)
            if not removed and os.path.lexists(native_output_path(path)):
                retained.append(
                    f"身份不符，保留恢复路径 {path}（期望 FileId {expected!r}）"
                )
        except OSError as exc:
            retained.append(f"清理未完成，保留恢复路径 {path}: {exc}")
    return tuple(retained)


__all__ = (
    "cleanup_report_paths",
    "report_metadata",
    "report_parent_proof",
    "require_report_payload",
)
