"""CLI, full reports and exclusive new-file exports for offline hotkey checks."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any

from .hotkey_config import (
    diff_hotkey_configs,
    inspect_hotkey_config,
    raw_hotkey_node,
    revalidate_hotkey_source,
)
from .hotkey_config_models import HotkeyDiagnostic, HotkeyDiff, HotkeyInspection
from .live_report_io import _parents as _held_report_parents
from . import windows_output_paths
from .windows_output_paths import native_output_path, validate_output_root


type HotkeyReport = HotkeyInspection | HotkeyDiff


def hotkey_result_to_dict(result: HotkeyReport) -> dict[str, Any]:
    """Flat AST plus original bytes retain every key, number and extension."""
    return {
        "schema_version": 1,
        "report_type": "hotkeys_diff"
        if isinstance(result, HotkeyDiff)
        else "hotkeys_inspection",
        "report_is_configuration": False,
        "exit_code": result.exit_code,
        **asdict(result),
    }


def _diagnostic_lines(diagnostics: tuple[HotkeyDiagnostic, ...]) -> list[str]:
    lines: list[str] = []
    for row in diagnostics:
        lines.append(
            f"[{row.severity}/{row.code}/{row.basis}] {row.path}: {row.message}"
        )
        lines.extend("  相关声明: " + path for path in row.related)
    return lines or ["无已确认诊断。"]


def format_hotkey_inspection(result: HotkeyInspection) -> str:
    """Full declared profiles, separate projection and untruncated diagnostics."""
    lines = [
        "GameXRay 离线改键方案检查",
        result.contract_basis,
        f"输入: {result.source.path}",
        f"输入 SHA-256: {result.source.sha256 or '未取得'}",
        f"字节数: {result.source.size}；稳定复验: {result.source.stable}；完整: {result.inspection_complete}；退出码: {result.exit_code}",
        f"原声明方案 {result.profiles_total}；本次展示 {len(result.profiles)}；选择: {result.selected_profile if result.selected_profile is not None else '全部'}",
        "差异身份按原方案名/原 binding_id；兼容迁移只在独立投影中展示。",
        "",
        "== 原声明 ==",
    ]
    if not result.profiles:
        lines.append(
            "未取得唯一可展示方案；请查看完整诊断和来源原文，核对 profiles 对象及 --profile 名称。"
        )
    for profile in result.profiles:
        lines.append(
            f"方案 {json.dumps(profile.name, ensure_ascii=True)} · 第{profile.occurrence}处 · {profile.path} · 原绑定 {len(profile.bindings)} · 原绑定身份覆盖完整: {profile.bindings_coverage_complete}"
        )
        lines.append(raw_hotkey_node(result, profile.node))
        for binding in profile.bindings:
            lines.append(
                f"  声明#{binding.ordinal}: ID={binding.binding_id!r}, group={binding.declared_group!r}, source={binding.source!r}, target={binding.target!r}"
            )
            lines.append(
                f"    仅用于比较的按键规范形式: source={binding.canonical_source!r}, target={binding.canonical_target!r}"
            )
    lines.extend(
        (
            "",
            "== 原工具兼容推导 ==",
            "以下是原 v2.0.0 读取/normalize 行为的独立静态投影；不会写回或应用。",
        )
    )
    for profile in result.profiles:
        lines.append(
            f"方案 {profile.name!r} · 推导完整: {profile.compatibility_complete}"
        )
        if not profile.compatibility_complete:
            lines.append("无法推导确定方案；请先解决类型/歧义诊断。")
        for binding in profile.compatibility_bindings:
            lines.append(json.dumps(asdict(binding), ensure_ascii=True))
    lines.extend(("", "== 完整诊断 ==", *_diagnostic_lines(result.diagnostics)))
    lines.extend(
        (
            "",
            "== 来源与完整原文 ==",
            f"重建依据样本 SHA-256: {result.contract_sample_sha256}",
            f"静态模型根字节码 SHA-256: {result.contract_model_sha256}",
            "文件标识 (dev, ino, size, mtime_ns, ctime_ns, mode): "
            + repr(result.source.identity),
            "原文（保留前导 BOM；JSON 导出另附完整 raw_base64 与无递归平面语法树）:",
        )
    )
    if result.source.utf8_text is None:
        lines.append("UTF-8 解码失败，完整原始字节 Base64:")
        lines.append(result.source.raw_base64)
    else:
        lines.append(result.source.utf8_text)
    lines.extend(
        (
            "",
            "== 继续查证 ==",
            "选择实际配置 JSON 后重新检查；可用 --profile 唯一方案名缩小展示，完整来源诊断仍保留。",
            "使用 hotkeys diff OLD NEW 比较原声明。报告 JSON 不是可导入改键配置；使用独立的新路径导出报告。",
        )
    )
    return "\n".join(lines) + "\n"


def format_hotkey_diff(result: HotkeyDiff) -> str:
    """Render complete differences and both input reports, including raw evidence."""
    lines = [
        "GameXRay 离线改键方案比较",
        result.contract_basis,
        f"旧: {result.old.source.path}",
        f"新: {result.new.source.path}",
        f"比较完整: {result.comparison_complete}；确认差异 {len(result.differences)}；has_changes={result.has_changes}；退出码: {result.exit_code}",
        "== 方案差异 ==",
    ]
    for difference in result.differences:
        lines.extend(
            (
                f"[{difference.kind}] {difference.path}",
                "  旧声明: "
                + (
                    difference.before if difference.before is not None else "（未声明）"
                ),
                "  新声明: "
                + (difference.after if difference.after is not None else "（未声明）"),
            )
        )
    if not result.differences:
        lines.append(
            "未确认差异。"
            if result.comparison_complete
            else "来源/身份存在不完整证据，不能据此声称方案相同；请先修复以下诊断。"
        )
    lines.extend(
        (
            "",
            "== 比较诊断 ==",
            *_diagnostic_lines(result.diagnostics),
            "",
            "== 旧文件完整检查 ==",
            format_hotkey_inspection(result.old),
            "== 新文件完整检查 ==",
            format_hotkey_inspection(result.new),
        )
    )
    return "\n".join(lines) + "\n"


def format_hotkey_result(result: HotkeyReport) -> str:
    return (
        format_hotkey_diff(result)
        if isinstance(result, HotkeyDiff)
        else format_hotkey_inspection(result)
    )


def _sources(result: HotkeyReport):
    return (
        (result.old.source, result.new.source)
        if isinstance(result, HotkeyDiff)
        else (result.source,)
    )


def _parent_proof(destination: Path) -> tuple[tuple[str, int, int], ...]:
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


def _report_metadata(details: os.stat_result) -> tuple[int, ...]:
    return (
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
        details.st_mode,
    )


def _require_report_payload(
    path: str,
    descriptor: int,
    expected: tuple[int, ...],
    expected_sha256: str,
    *,
    expected_named: tuple[int, ...] | None = None,
    allow_link_change_time: bool = False,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Bind one name to the held descriptor and verify the complete payload."""
    before = _report_metadata(os.fstat(descriptor))
    named = os.lstat(native_output_path(path))
    named_metadata = _report_metadata(named)
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
        _report_metadata(os.fstat(descriptor)) != before
        or _report_metadata(os.lstat(native_output_path(path))) != named_metadata
        or total != expected[2]
        or digest.hexdigest() != expected_sha256
    ):
        raise OSError(f"报告完整 payload/元数据复验失败，未确认成功发布: {path}")
    return before, named_metadata


def _cleanup_report_paths(
    paths: tuple[str, ...], expected: tuple[int, int]
) -> tuple[str, ...]:
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


def write_hotkey_export(
    path: str | Path, result: HotkeyReport, *, as_json: bool | None = None
) -> None:
    """Publish a complete new report with no overwrite, including alias races."""
    validate_output_root(os.fspath(path))
    destination = Path(os.path.abspath(path))
    destination_io = native_output_path(str(destination))
    if os.path.lexists(destination_io):
        raise ValueError("报告输出必须是不存在的新文件；不会覆盖原配置或已有报告。")
    sources = _sources(result)
    if any(destination.resolve() == Path(source.path).resolve() for source in sources):
        raise ValueError("报告路径指向源配置；请选择独立的新文件。")
    if any(
        source.stable and not revalidate_hotkey_source(source) for source in sources
    ):
        raise ValueError("报告导出前源文件已变化；请重新检查后导出。")
    proof = _parent_proof(destination)
    json_output = (
        destination.suffix.casefold() == ".json" if as_json is None else as_json
    )
    content = (
        json.dumps(hotkey_result_to_dict(result), ensure_ascii=True, indent=2) + "\n"
        if json_output
        else format_hotkey_result(result)
    )
    data = content.encode("utf-8", errors="strict")
    expected_digest = hashlib.sha256(data).hexdigest()
    with _held_report_parents(Path(destination_io)):
        descriptor, stage = tempfile.mkstemp(
            prefix=".gamexray-hotkeys-",
            suffix=".tmp",
            dir=native_output_path(str(destination.parent)),
        )
        owned = os.fstat(descriptor)
        owned_identity = owned.st_dev, owned.st_ino
        completed = False
        destination_created = False
        try:
            # Keep this descriptor across publication. Its sharing permits the
            # atomic hard link, while complete proofs detect concurrent writes.
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                _ = stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            expected_metadata = _report_metadata(os.fstat(descriptor))
            if expected_metadata[2] != len(data) or _parent_proof(destination) != proof:
                raise OSError("报告长度或父目录在写入时变化；未发布报告。")
            _, named_metadata = _require_report_payload(
                stage, descriptor, expected_metadata, expected_digest
            )
            # Existing/concurrent destination names are never replaced.
            os.link(stage, destination_io)
            destination_created = True
            # Creating our hard link updates Windows descriptor ChangeTime.
            # Bind every other field and the original pathname clock, and prove
            # the full payload across this one known namespace transition.
            linked_metadata, _ = _require_report_payload(
                stage,
                descriptor,
                expected_metadata,
                expected_digest,
                expected_named=named_metadata,
                allow_link_change_time=True,
            )
            _require_report_payload(
                destination_io,
                descriptor,
                linked_metadata,
                expected_digest,
                expected_named=named_metadata,
            )
            if _parent_proof(destination) != proof:
                raise OSError("报告父目录在发布时变化；未确认成功发布。")
            if any(
                source.stable and not revalidate_hotkey_source(source)
                for source in sources
            ):
                raise ValueError("来源在报告发布期间变化；请重新检查后导出。")
            completed = True
        finally:
            primary = sys.exc_info()[1]
            os.close(descriptor)
            # Mature Windows handle cleanup binds and deletes the exact FileId;
            # a replaced name is retained rather than rechecked then unlinked.
            cleanup_paths = (
                (destination_io, stage)
                if destination_created and not completed
                else (stage,)
            )
            retained = list(_cleanup_report_paths(cleanup_paths, owned_identity))
            if (
                not destination_created
                and not completed
                and os.path.lexists(destination_io)
            ):
                retained.append(
                    f"本次原子发布未确认创建目标命名项，即使 FileId 相同也不能回滚；保留恢复路径 {destination_io}"
                )
            if retained:
                detail = "; ".join(retained)
                raise OSError(
                    f"{primary}; {detail}" if primary is not None else detail
                ) from primary


def run_hotkeys_cli(argv: Sequence[str] | None = None) -> int:
    """Dispatch an explicit offline inspection or comparison; never discover files."""
    parser = argparse.ArgumentParser(
        prog="gamexray hotkeys",
        description="离线检查与比较用户选择的改键 JSON；静态重建合同，不应用改键。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser(
        "inspect", help="检查一个配置文件的完整原声明"
    )
    inspect_parser.add_argument("path")
    inspect_parser.add_argument("--profile", help="精确、唯一的方案名称")
    diff_parser = subparsers.add_parser("diff", help="比较两个配置文件的原声明")
    diff_parser.add_argument("old")
    diff_parser.add_argument("new")
    for command_parser in (inspect_parser, diff_parser):
        command_parser.add_argument(
            "--json",
            action="store_true",
            help="输出含原字节与重复键语法树的完整报告 JSON",
        )
        command_parser.add_argument(
            "--output", metavar="NEW", help="导出完整报告到不存在的新文件"
        )
    args = parser.parse_args(argv)
    try:
        result = (
            inspect_hotkey_config(args.path, profile=args.profile)
            if args.command == "inspect"
            else diff_hotkey_configs(args.old, args.new)
        )
        text = (
            json.dumps(hotkey_result_to_dict(result), ensure_ascii=True, indent=2)
            + "\n"
            if args.json
            else format_hotkey_result(result)
        )
        if args.output:
            write_hotkey_export(
                args.output,
                result,
                as_json=args.json or Path(args.output).suffix.casefold() == ".json",
            )
        _ = sys.stdout.write(text)
        return result.exit_code
    except (OSError, ValueError, UnicodeError) as exc:
        _ = sys.stderr.write(
            f"离线改键检查失败: {exc}\n请选择可读的配置文件，并将报告导出到独立新路径。\n"
        )
        return 2
