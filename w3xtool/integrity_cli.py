"""Typed CLI boundary for integrity snapshots and retained-cache reports."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Final, assert_never

from .bounded_file import BoundedFileError, read_bounded_regular_file
from .description_cache_retained_integrity import (
    DescriptionCacheRetentionError,
    RetainedArtifactValidation,
    format_description_cache_retention_report,
    inspect_bound_retained_description_caches,
)
from .description_cache_retained_binding import bind_active_cache
from .integrity_snapshot import (
    IntegritySnapshotError,
    SnapshotRoot,
    build_integrity_snapshot,
    compare_integrity_snapshot,
    format_integrity_snapshot,
    parse_integrity_snapshot,
)
from .integrity_cli_options import (
    IntegrityCliOptionError,
    RetainedCacheCliOptions,
    SnapshotCliOptions,
    VerifyCliOptions,
    parse_integrity_cli_options,
)
from .integrity_output import (
    bind_retained_output,
    bind_snapshot_output,
)
from .safe_output import SafeWriteStatus


_MAX_SNAPSHOT_BYTES: Final = 64 * 1024 * 1024


def run_integrity_cli(argv: tuple[str, ...]) -> int:
    """Run one integrity action and map request/difference boundaries to 2/1."""
    try:
        options = parse_integrity_cli_options(argv)
    except IntegrityCliOptionError as exc:
        print(f"完整性参数错误：{exc}", file=sys.stderr)
        return 2
    match options:
        case SnapshotCliOptions(roots=roots, output=output):
            return _run_snapshot(roots, output)
        case VerifyCliOptions(snapshot=snapshot):
            return _run_verify(snapshot)
        case RetainedCacheCliOptions(active_root=active_root, output=output):
            return _run_retained_cache(active_root, output)
        case unreachable:
            assert_never(unreachable)


def _run_snapshot(roots: tuple[SnapshotRoot, ...], output: Path) -> int:
    destination = Path(os.path.abspath(output.expanduser()))
    try:
        with bind_snapshot_output(
            destination,
            tuple(root.path for root in roots),
        ) as bound_output:
            snapshot = build_integrity_snapshot(roots)
            result = bound_output.write_text(format_integrity_snapshot(snapshot))
    except OSError as exc:
        print(f"完整性快照写入失败：{exc}", file=sys.stderr)
        return 2
    except IntegritySnapshotError as exc:
        print(f"完整性快照失败：{exc}", file=sys.stderr)
        return 2
    match result.status:
        case SafeWriteStatus.WRITTEN:
            print(f"完整性快照已写入：{destination}")
            return 0
        case SafeWriteStatus.FAILED | SafeWriteStatus.UNSAFE:
            print(f"完整性快照写入失败：{result.error}", file=sys.stderr)
            return 2
        case unreachable:
            assert_never(unreachable)


def _run_verify(snapshot_path: Path) -> int:
    try:
        payload, _identity = read_bounded_regular_file(
            snapshot_path,
            _MAX_SNAPSHOT_BYTES,
        )
        expected = parse_integrity_snapshot(payload.decode("utf-8"))
        actual = build_integrity_snapshot(
            tuple(SnapshotRoot(root.label, Path(root.path)) for root in expected.roots)
        )
    except (BoundedFileError, UnicodeError, IntegritySnapshotError) as exc:
        print(f"完整性验证失败：{exc}", file=sys.stderr)
        return 2
    differences = compare_integrity_snapshot(expected, actual)
    if not differences:
        print("完整性验证通过")
        return 0
    for difference in differences:
        print(
            f"完整性差异：{difference.code.value} "
            f"{difference.root_label} {difference.relative_path}",
            file=sys.stderr,
        )
    return 1


def _run_retained_cache(active_root: Path, output: Path) -> int:
    destination = Path(os.path.abspath(output.expanduser()))
    try:
        with bind_retained_output(destination, active_root) as bound_output:
            with bind_active_cache(active_root) as bound_active:
                inspection = inspect_bound_retained_description_caches(bound_active)
                report = inspection.report
                payload = format_description_cache_retention_report(report)
                result = bound_output.write_text(
                    payload,
                    lambda: inspection.require_current(bound_active),
                )
    except OSError as exc:
        print(f"保留缓存报告写入失败：{exc}", file=sys.stderr)
        return 2
    except DescriptionCacheRetentionError as exc:
        print(f"保留缓存完整性检查失败：{exc}", file=sys.stderr)
        return 2
    match result.status:
        case SafeWriteStatus.WRITTEN:
            pass
        case SafeWriteStatus.FAILED | SafeWriteStatus.UNSAFE:
            print(f"保留缓存报告写入失败：{result.error}", file=sys.stderr)
            return 2
        case unreachable:
            assert_never(unreachable)
    if (
        report.transient
        or report.malformed
        or any(_retained_violation(item.validation) for item in report.retained)
    ):
        print(f"保留缓存完整性发现违规：{destination}", file=sys.stderr)
        return 1
    print(f"保留缓存完整性通过：{destination}")
    return 0


def _retained_violation(validation: RetainedArtifactValidation) -> bool:
    match validation:
        case (
            RetainedArtifactValidation.VALID_CACHE
            | RetainedArtifactValidation.PARTIAL_EVIDENCE
        ):
            return False
        case (
            RetainedArtifactValidation.INVALID_PREVIOUS
            | RetainedArtifactValidation.UNSAFE_OBJECT
            | RetainedArtifactValidation.OVERSIZED
            | RetainedArtifactValidation.UNSTABLE
            | RetainedArtifactValidation.UNREADABLE
        ):
            return True
        case unreachable:
            assert_never(unreachable)


__all__ = (
    "IntegrityCliOptionError",
    "RetainedCacheCliOptions",
    "SnapshotCliOptions",
    "VerifyCliOptions",
    "parse_integrity_cli_options",
    "run_integrity_cli",
)
