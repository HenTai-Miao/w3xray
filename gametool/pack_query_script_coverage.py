"""Typed, source-backed coverage for script-dependent pack queries."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json
from pathlib import Path

from .script_lexing import script_views
from .script_sources import AnalysisScriptSource


SCRIPT_QUERY_COMMANDS = frozenset(
    {
        "refs",
        "locate",
        "recipe",
        "synth",
        "quest",
        "cmd",
        "where",
        "drop",
        "doc",
        "export",
    }
)


@dataclass(frozen=True, slots=True)
class ScriptCoverageSource:
    path: str
    state: str
    records: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True, slots=True)
class ScriptCoverage:
    # None preserves the unknown source contract of legacy index-only packs.
    complete: bool | None
    diagnostics: tuple[str, ...] = ()
    sources: tuple[ScriptCoverageSource, ...] = ()


def combine_script_coverage(coverages: Sequence[ScriptCoverage]) -> ScriptCoverage:
    return ScriptCoverage(
        False
        if any(value.complete is False for value in coverages)
        else None
        if any(value.complete is None for value in coverages)
        else True,
        tuple(dict.fromkeys(note for value in coverages for note in value.diagnostics)),
        tuple(dict.fromkeys(source for value in coverages for source in value.sources)),
    )


def build_script_coverage(
    pack: Path,
    contexts: Sequence[AnalysisScriptSource],
    *,
    source_directory: str,
    encrypted_report: Sequence[Sequence[str]] | None = None,
    manifest: Sequence[Sequence[str]] = (),
    component_rows: Sequence[Sequence[str]] = (),
    read_failures: Sequence[str] = (),
) -> ScriptCoverage:
    """Keep explicit coverage gaps; empty or comment-only code proves no gap."""
    sources: list[ScriptCoverageSource] = []
    diagnostics: list[str] = []
    for source, text, lua in contexts:
        unknown_language = lua is None and bool(text.strip())
        comment_only = (
            lua is not None and not script_views(text, lua=lua).syntax.strip()
        )
        sources.append(
            ScriptCoverageSource(
                str(pack / source_directory / source),
                "unknown_language"
                if unknown_language
                else "comment_only"
                if comment_only
                else "readable",
            )
        )
        if unknown_language:
            diagnostics.append(
                f"[⚠ 脚本逻辑覆盖不足：分析来源的语言尚未确认，未将其猜作 JASS；"
                f"来源: {pack / source_directory / source}；"
                "未用未分类逻辑的空索引证明机制不存在，可用 text <词> 查原文或重新导出。]"
            )
    declared = bool(
        manifest and manifest[0] and manifest[0][0].startswith("脚本文件：")
    )
    if manifest:
        problem = ""
        if declared:
            count = manifest[0][0].removeprefix("脚本文件：").strip()
            actual = sum(1 for row in manifest[1:] if row and row[0])
            # Compare encoded decimal spelling; never allocate from the count
            # or rely on Python's integer-string conversion quota.
            valid_count = count.isascii() and count.isdecimal()
            if not valid_count or (count.lstrip("0") or "0") != str(actual):
                problem = f"清单声明脚本数 {count}，实际编码清单记录 {actual} 条"
        sources.append(
            ScriptCoverageSource(
                str(pack / "脚本清单.txt"),
                "manifest_incomplete" if problem else "manifest",
                tuple(tuple(row) for row in manifest),
            )
        )
        if problem:
            diagnostics.append(
                f"[⚠ 脚本逻辑覆盖不足：{problem}；"
                f"原始记录: {json.dumps(tuple(tuple(row) for row in manifest), ensure_ascii=False)}；"
                f"来源: {pack / '脚本清单.txt'}；未猜测缺失来源，可用 text <词> 或重新导出。]"
            )
    if encrypted_report is not None:
        relative = "未知文件/加密脚本检测.txt"
        records = tuple(tuple(row) for row in encrypted_report)
        sources.append(ScriptCoverageSource(str(pack / relative), "encrypted", records))
        report = "\n".join("\t".join(row) for row in records)
        diagnostics.append(
            f"[⚠ 脚本逻辑覆盖不足：存在平台加密脚本检测报告，未用静态空结果证明机制不存在。"
            f"来源: {pack / relative}\n完整报告:\n{report}\n"
            "可用 text <词> 查已提取原文；需要完整脚本证据时，请使用作者提供的明文来源或重新导出。]"
        )
    if declared:
        present = {
            source.replace("\\", "/").casefold() for source, _text, _lua in contexts
        }
        for row in manifest[1:]:
            if not row:
                continue
            name = row[0].replace("\\", "/")
            if Path(name).suffix.casefold() not in {".j", ".lua", ".txt"}:
                continue
            if name.casefold() not in present:
                sources.append(
                    ScriptCoverageSource(
                        str(pack / "脚本清单.txt"), "declared_missing", (tuple(row),)
                    )
                )
                diagnostics.append(
                    f"[⚠ 脚本逻辑覆盖不足：清单已声明的来源 {name} 未能读取；"
                    f"原始记录: {json.dumps(tuple(row), ensure_ascii=False)}；"
                    f"来源: {pack / '脚本清单.txt'}；未用缺失来源证明没有机制，可用 text <词> 或重新导出。]"
                )
    if component_rows:
        records = tuple(tuple(row) for row in component_rows)
        sources.append(
            ScriptCoverageSource(
                str(pack / "组件诊断.tsv"), "component_report", records
            )
        )
        header = records[0]
        positions = {
            role: [index for index, cell in enumerate(header) if cell == role]
            for role in ("组件", "来源", "级别")
        }
        if all(len(columns) == 1 for columns in positions.values()):
            component, origin, level = (
                positions[role][0] for role in ("组件", "来源", "级别")
            )
            for row in records[1:]:
                if max(component, origin, level) >= len(row):
                    continue
                script_component = row[component].casefold() in {
                    "script",
                    "scripts",
                    "wct",
                    "jass",
                    "lua",
                }
                script_source = Path(row[origin]).suffix.casefold() in {
                    ".j",
                    ".lua",
                    ".wct",
                }
                if row[level].casefold() not in {"warning", "error"} or not (
                    script_component or script_source
                ):
                    continue
                diagnostics.append(
                    f"[⚠ 脚本逻辑覆盖不足：来源有读取或解析诊断；"
                    f"原始记录: {json.dumps(row, ensure_ascii=False)}；"
                    f"来源: {pack / '组件诊断.tsv'}；未用不完整来源证明没有机制，可用 text <词> 或重新导出。]"
                )
    for relative in dict.fromkeys(read_failures):
        sources.append(ScriptCoverageSource(str(pack / relative), "read_failed"))
        diagnostics.append(
            f"[⚠ 脚本逻辑覆盖不足：来源读取失败 {pack / relative}；"
            "未用空索引证明机制不存在，请核对文件权限或重新导出；可用 text <词> 查其余已确认原文。]"
        )
    return ScriptCoverage(
        False if diagnostics else True if contexts or declared else None,
        tuple(dict.fromkeys(diagnostics)),
        tuple(dict.fromkeys(sources)),
    )
