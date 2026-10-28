"""CLI and complete report export for the local field/build reference."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Any

from .pack_query_options import parse_query_limit
from .reference_catalog import load_reference_catalog, search_reference_catalog
from .reference_models import ReferenceRecord, ReferenceSearchResult
from .safe_output import write_text_safely
from .safe_output_models import SafeWriteStatus


def reference_result_to_dict(result: ReferenceSearchResult) -> dict[str, Any]:
    """Lossless, JSON-compatible records plus full untruncated source diagnostics."""
    return {"schema_version": 1, **asdict(result)}


def format_reference_record(record: ReferenceRecord) -> str:
    """Render a whole object, field definition, or version record."""
    category = record.category or " / ".join(record.categories) or "类别未记录"
    lines = [
        f"[{record.id}] {record.label} · {category} · {record.state}",
        f"  范围: {record.scope}",
        "  build: " + " / ".join(record.builds),
    ]
    if record.aliases:
        lines.append("  别名: " + " / ".join(record.aliases))
    lines.extend(f"  {label}: {value}" for label, value in record.details if value)
    if record.sources:
        lines.append("  来源: " + " / ".join(record.sources))
    if record.coverage is not None:
        lines.append(
            "  声明覆盖（runtime_verified=False）: "
            + json.dumps(record.coverage, ensure_ascii=False)
        )
    for value in record.values:
        label = " / " + value.label if value.label and value.label != value.key else ""
        identity = f" · {value.category}:{value.object_id}" if value.object_id else ""
        lines.append(
            f"    {value.key}{label}: {value.value if value.value else '（显式空值）'}"
            f"  [{value.value_type or '类型未记录'} · {value.state}{identity}]"
        )
        if value.aliases:
            lines.append("      字段别名: " + " / ".join(value.aliases))
        lines.append(
            f"      来源: {value.source} · {value.provenance or '原字段来源未记录'}"
        )
        lines.extend(f"      {label}: {text}" for label, text in value.extras)
    lines.extend("  诊断: " + note for note in record.diagnostics)
    return "\n".join(lines)


def format_reference_result(result: ReferenceSearchResult) -> str:
    """Render all selected records and all source/coverage diagnostics."""
    lines = [
        "GameXRay 离线字段与版本参考",
        "静态定义、地图/知识包证据与外部未验证标签；实时值请使用 live 探针。",
        f"已确认目录记录 {result.total}，匹配 {result.matched}，显示 {len(result.records)}。",
        f"筛选: kind={result.kind} category={result.category or '全部'} "
        f"build={result.build or '全部'} source={result.source or '全部'}",
    ]
    if result.map_path:
        lines.extend(
            (
                f"地图归档: {result.map_path}",
                "地图证据按归档/章节分别计数；基础定义仍为独立静态参考。",
            )
        )
        for scope in result.map_scopes:
            counts = " / ".join(
                f"{category} {count}" for category, count in scope.category_counts
            )
            lines.append(
                f"  {scope.scope}: {counts or '无已确认对象'} · {'完整' if scope.complete else '不完整'}"
            )
            if scope.shared_scope:
                lines.append(
                    f"    战役共享来源: {scope.shared_scope}（共享定义仅在该范围展示一次）"
                )
            if scope.shared_references:
                lines.append(
                    "    共享引用: "
                    + " / ".join(
                        f"{category}:{code}"
                        for category, code in scope.shared_references
                    )
                )
    if not result.records:
        lines.append("未找到符合筛选条件的记录。")
    for kind, label in (
        ("objects", "对象"),
        ("fields", "字段定义"),
        ("versions", "版本档案"),
    ):
        records = [record for record in result.records if record.kind == kind]
        if records:
            lines.extend(("", f"== {label} ({len(records)}) =="))
            for record in records:
                lines.extend((format_reference_record(record), ""))
    if result.omitted:
        lines.append(
            f"显式 --limit {result.limit} 选择完整记录，另 {result.omitted} 条匹配未显示；"
            "去掉 --limit 或用 --limit all 查看全量。"
        )
    if result.recovery:
        lines.extend(("", "== 继续查证 ==", *result.recovery))
    lines.extend(("", "== 来源台账 =="))
    for source in result.sources:
        lines.extend(
            (
                f"{source.id} · build={source.build} · {source.state}",
                f"  文件: {source.path}",
                f"  SHA-256: {source.sha256}",
                f"  指纹边界: {source.fingerprint_basis}",
                f"  磁盘源码独立观测: {source.source_file_sha256 or '无独立文件'} · {source.source_file_state or '不适用'}",
                f"  溯源: {source.provenance}",
                *(
                    (
                        f"  归档成员: {source.member_path}",
                        f"  容器 SHA-256: {source.container_sha256}",
                    )
                    if source.member_path
                    else ()
                ),
            )
        )
    if result.diagnostics:
        lines.extend(("", "== 完整来源诊断 ==", *result.diagnostics))
        lines.append(
            "存在不完整/变化来源；以上计数只描述已确认记录，请修复来源后刷新。"
            if not result.catalog_complete
            else "完整保留以上来源/记录诊断；冲突记录独立展示，未裁决哪份外部标签有效。"
        )
    return "\n".join(lines) + "\n"


def _require_report_destination(
    destination: Path, result: ReferenceSearchResult
) -> None:
    """Reject both current input names and retained original archive identities."""
    resolved = destination.resolve()
    inputs = tuple(
        dict.fromkeys(
            (*result.input_files, *(source.path for source in result.sources))
        )
    )
    if any(
        resolved == Path(source).resolve()
        or destination.exists()
        and Path(source).exists()
        and destination.samefile(source)
        for source in inputs
    ):
        raise ValueError("导出路径是目录的输入源文件；请选择独立报告路径。")
    if destination.exists():
        details = destination.stat()
        identities = {source.source_file_identity for source in result.sources}
        if (details.st_dev, details.st_ino) in identities:
            raise ValueError("导出路径是目录的输入源文件的硬链接；请选择独立报告路径。")
    if any(
        resolved.is_relative_to(Path(root).resolve()) for root in result.input_roots
    ):
        raise ValueError(
            "知识包及外部 ID 表为只读输入；请将参考报告导出到输入目录之外。"
        )


def write_reference_export(
    path: str | Path, result: ReferenceSearchResult, *, as_json: bool | None = None
) -> None:
    """Export an explicit report without replacing a catalog source/input asset."""
    destination = Path(path).absolute()
    _require_report_destination(destination, result)
    json_output = (
        destination.suffix.casefold() == ".json" if as_json is None else as_json
    )
    content = (
        json.dumps(reference_result_to_dict(result), ensure_ascii=False, indent=2)
        + "\n"
        if json_output
        else format_reference_result(result)
    )
    _require_report_destination(destination, result)
    written = write_text_safely(str(destination.parent), destination.name, content)
    if written.status != SafeWriteStatus.WRITTEN:
        raise OSError(f"参考报告写入失败: {written.status.value} {written.error}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gamexray reference",
        description="完整离线字段/对象/版本参考；不连接游戏。空关键词列出全量。",
        epilog='例: reference "冷却 && real" --kind fields；reference --kind versions；'
        "reference ckng --pack DIR --json --export reference.json；reference --map MAP.w3x --kind objects。"
        'Boolean 关键词支持 &&、||、%、括号、="区分大小写的精准词"。'
        " build 仅精确匹配已记录标签，基础表缺 build 时标为 unrecorded。",
    )
    parser.add_argument(
        "keyword", nargs="?", default="", help="关键词/Boolean 表达式，省略=完整列表"
    )
    map_input = parser.add_mutually_exclusive_group()
    map_input.add_argument(
        "--pack", default=None, metavar="DIR", help="叠加知识包及战役的全部直接子包"
    )
    map_input.add_argument(
        "--map",
        default=None,
        metavar="PATH",
        help="直接只读 .w3x/.w3m/.w3n 的完整对象/字段及战役章节；无需预先导出知识包",
    )
    parser.add_argument(
        "--id-table",
        action="append",
        default=[],
        metavar="PATH",
        help="叠加本地盒子 ID 文本文件/目录，可重复；目录只读四个声明文件名，标签为外部未验证",
    )
    parser.add_argument(
        "--profile-json",
        default=None,
        metavar="PATH",
        help="验证纯数据只读档案并显示声明字段/来源；不读取游戏",
    )
    parser.add_argument(
        "--kind", choices=("all", "objects", "fields", "versions"), default="all"
    )
    parser.add_argument(
        "--category", default="", help="对象分类（支持 items/units 等既有别名）"
    )
    parser.add_argument(
        "--build",
        default="",
        help="精确 build 标签，或 unrecorded/classic-template/reforged-pending",
    )
    parser.add_argument(
        "--source", default="", help="来源 ID/路径/溯源/SHA-256 包含过滤"
    )
    parser.add_argument(
        "--limit", default="0", help="完整记录数；0/all/全部=全量（默认）"
    )
    parser.add_argument("--json", action="store_true", help="输出完整结构化 JSON")
    parser.add_argument(
        "--export",
        default="",
        metavar="PATH",
        help="导出报告；.json 为 JSON，其余为完整文本",
    )
    return parser


def run_reference_cli(argv: Sequence[str]) -> int:
    """Run the standalone offline command; return 2 on invalid/incomplete input."""
    parser = _parser()
    try:
        args = parser.parse_args(list(argv))
        limit = parse_query_limit(args.limit)
        catalog = load_reference_catalog(
            args.pack,
            profile_json=args.profile_json,
            id_tables=args.id_table,
            map_path=args.map,
        )
        result = search_reference_catalog(
            catalog,
            args.keyword,
            kind=args.kind,
            category=args.category,
            build=args.build,
            source=args.source,
            limit=limit,
        )
        if args.export:
            write_reference_export(args.export, result)
        if args.json:
            print(
                json.dumps(
                    reference_result_to_dict(result), ensure_ascii=False, indent=2
                )
            )
        else:
            print(format_reference_result(result), end="")
        return 0 if result.catalog_complete else 2
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    except (OSError, ValueError) as exc:
        print(f"reference: {exc}", file=sys.stderr)
        return 2
