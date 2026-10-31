"""Provenance-preserving resource candidates confirmed by current source reads."""

from __future__ import annotations

from bisect import bisect_right
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, replace
import hashlib
import os
import re
import struct
from typing import TYPE_CHECKING

from .batch_tsv import format_tsv_rows
from .campaign_sources import open_map_source
from .resource_candidate_sources import (
    ResourcePathConflict,
    ResourceReadableSource,
    VerifiableResourceSource,
    open_resource_directory,
)
from .resource_types import RESOURCE_EXTS, resource_kind
from .safe_output import safe_relative_path
from .script_function_graph import script_functions
from .script_lexing import script_literals, script_views
from .script_literal_decoding import decode_script_literal
from .script_scopes import source_line_starts
from .script_sources import analysis_script_sources
from .slk_evidence_records import read_slk_records
from .war3_encoding import decode_warcraft_string

if TYPE_CHECKING:
    from .map_data import MapData

_TEXT_EXTS = frozenset(
    ("txt", "ini", "wts", "fdf", "toc", "slk", "json", "plist", "skin", "ai", "mdl")
)
_CONCAT_AFTER = re.compile(r"\s*(?:\+|\.\.)")


@dataclass(frozen=True, slots=True)
class ResourceCandidate:
    path: str
    source: str
    source_kind: str
    language: str
    line: int
    offset: int
    end_offset: int
    raw: str
    value: str
    source_fingerprint: str
    owner: str = ""
    binding: str = ""
    state: str = "candidate"
    size: int | None = None
    sha256: str = ""
    diagnostics: tuple[str, ...] = ()
    literal_bytes: bytes | None = None
    literal_encoding: str = ""
    literal_source_encoding: str = ""
    literal_complete: bool | None = None


@dataclass(frozen=True, slots=True)
class ResourceCandidateDiagnostic:
    source: str
    stage: str
    detail: str


@dataclass(frozen=True, slots=True)
class ResourceCandidateReport:
    items: tuple[ResourceCandidate, ...]
    diagnostics: tuple[ResourceCandidateDiagnostic, ...] = ()

    @property
    def confirmed_paths(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(item.path for item in self.items if item.state == "confirmed")
        )


@dataclass(frozen=True, slots=True)
class _CandidateRead:
    state: str
    payload: bytes | None = None
    size: int | None = None
    sha256: str = ""
    diagnostic: str = ""


def script_resource_candidates(
    source: str, text: str, *, lua: bool | None
) -> tuple[ResourceCandidate, ...]:
    """Use complete source literals, excluding comments and dynamic fragments."""
    functions = script_functions(text, lua=lua)
    fingerprint = "decoded-text-sha256:" + _digest(text.encode("utf-8"))
    parentheses = _parentheses(functions.views.syntax)
    call_opens = {call.open for call in functions.structure.calls}
    items: list[ResourceCandidate] = []
    for literal in script_literals(text, lua=lua):
        raw = text[literal.start : literal.end]
        # MapData exposes decoded text, not the original source-file encoding.
        # The shared decoder may prove ASCII/Unicode text but must retain
        # non-ASCII byte escapes as bytes until a caller supplies an encoding.
        decoded = decode_script_literal(raw, lua=lua, encoding="")
        value = (
            decoded.value
            if decoded.value is not None
            else raw[1:-1]
            if raw[:1] in {"'", '"'}
            else literal.value
        )
        if literal.object_code or not _looks_like_resource(value):
            continue
        function = functions.structure.scopes.at(literal.start)
        call = functions.structure.call_scopes.at(literal.start)
        binding = "literal"
        if call is not None:
            reference = functions.resolve(call.name, call.start, call.owner)
            binding = (
                call.name
                + ": "
                + (
                    "source-function "
                    + ", ".join(item.name for item in reference.functions)
                    if reference.functions
                    else "standard " + reference.builtin
                    if reference.builtin
                    else reference.diagnostic or "external"
                )
            )
        state, notes = _path_state(value)
        if not decoded.complete:
            state = "unknown"
            notes += (
                "字面量未完整解码；完整值保留原始编码内容，运行时路径未知，未读取该拼写",
                *decoded.diagnostics,
            )
        if _concatenated(
            functions.views.syntax, literal.start, literal.end, parentheses, call_opens
        ):
            state = "unknown"
            notes += ("字符串参与拼接，完整运行时路径未静态确定；未读取片段路径",)
        if call is not None and not call.complete:
            state = "unknown"
            notes += ("调用表达式范围未闭合，未读取未确认的参数路径",)
        if lua is None:
            state = "unknown"
            notes += ("脚本来源语言未知，字面量保留为候选，未按猜测语言确认资源",)
        items.append(
            ResourceCandidate(
                _path(value),
                source,
                "script",
                _language(lua),
                bisect_right(functions.lines, literal.start),
                literal.start,
                literal.end,
                raw,
                value,
                fingerprint,
                function.name if function else "<源码顶层>",
                binding,
                state=state,
                diagnostics=notes,
                literal_bytes=decoded.raw_bytes,
                literal_encoding=decoded.encoding,
                literal_source_encoding=decoded.source_encoding,
                literal_complete=decoded.complete,
            )
        )
    return tuple(items)


def data_resource_candidates(source: str, raw: bytes) -> tuple[ResourceCandidate, ...]:
    """Read complete quoted values, SLK K cells and explicit text field values."""
    text = decode_warcraft_string(raw, allow_latin1=True)
    fingerprint = "bytes-sha256:" + _digest(raw)
    lines = source_line_starts(text)
    items: list[ResourceCandidate] = []
    for start, end, value, form, uncertainty in _data_values(source, text):
        if not _looks_like_resource(value):
            continue
        state, notes = _path_state(value)
        if uncertainty:
            state = "unknown"
            notes += uncertainty
        items.append(
            ResourceCandidate(
                _path(value),
                source,
                "asset-body",
                "data",
                bisect_right(lines, start),
                start,
                end,
                text[start:end],
                value,
                fingerprint,
                binding=form,
                state=state,
                diagnostics=notes,
            )
        )
    return tuple(items)


def build_resource_candidate_report(md: MapData) -> ResourceCandidateReport:
    """Discover source-declared names and verify each through one held reader.

    Existence is confirmed only after ``read_file`` succeeds. Every occurrence
    retains its original spelling and provenance, even when reads are shared.
    The report never mutates ``all_files`` or claims recovery of unnamed blocks.
    """
    scripts = analysis_script_sources(md)
    names = tuple(md.all_files)
    initial = [
        item
        for source, text, lua in scripts
        for item in script_resource_candidates(source, text, lua=lua)
    ]
    for objects in md.objects.values():
        for obj in objects:
            values = (("图标", obj.icon), *obj.fields)
            for field, value in values:
                if not isinstance(value, str) or not _looks_like_resource(value):
                    continue
                state, notes = _path_state(value)
                initial.append(
                    ResourceCandidate(
                        _path(value),
                        f"对象 {obj.category}/{obj.obj_id}",
                        "object",
                        "data",
                        0,
                        0,
                        len(value),
                        value,
                        value,
                        "",
                        binding=str(field),
                        state=state,
                        diagnostics=notes,
                    )
                )
    diagnostics: list[ResourceCandidateDiagnostic] = []
    if not initial and not any(_extension(name) in _TEXT_EXTS for name in names):
        return ResourceCandidateReport(())
    items = initial
    try:
        context = (
            open_resource_directory(md.path)
            if md.path and os.path.isdir(md.path)
            else open_map_source(md)
        )
        with context as source:
            if isinstance(source, VerifiableResourceSource):
                source.verify_source()
            items = _discover(source, initial, names, diagnostics)
            if isinstance(source, VerifiableResourceSource):
                source.verify_source()
            if analysis_script_sources(md) != scripts or tuple(md.all_files) != names:
                raise OSError(
                    "loaded script texts or archive-name snapshot changed before delivery"
                )
    except (OSError, ValueError, struct.error) as exc:
        diagnostics.append(ResourceCandidateDiagnostic(md.path, "source", str(exc)))
        items = [
            replace(
                item,
                state="unstable"
                if item.state == "confirmed"
                else "unavailable"
                if item.state == "candidate"
                else item.state,
                diagnostics=(*item.diagnostics, f"归档来源未稳定确认: {exc}"),
            )
            for item in items
        ]
    return ResourceCandidateReport(tuple(items), tuple(diagnostics))


def _discover(
    source: ResourceReadableSource,
    initial: list[ResourceCandidate],
    names: tuple[str, ...],
    diagnostics: list[ResourceCandidateDiagnostic],
) -> list[ResourceCandidate]:
    items: list[ResourceCandidate] = []
    pending = deque(initial)
    bodies = deque(name for name in names if _extension(name) in _TEXT_EXTS)
    reads: dict[str, _CandidateRead] = {}
    scanned: set[str] = set()

    def read(path: str) -> _CandidateRead:
        if path in reads:
            return reads[path]
        try:
            data = source.read_file(path)
        except (KeyError, FileNotFoundError) as exc:
            result = _CandidateRead("missing", diagnostic=str(exc))
        except ResourcePathConflict as exc:
            result = _CandidateRead("conflict", diagnostic=str(exc))
        except (OSError, ValueError, struct.error) as exc:
            result = _CandidateRead("unreadable", diagnostic=str(exc))
        else:
            result = _CandidateRead(
                "confirmed",
                data if _extension(path) in _TEXT_EXTS else None,
                len(data),
                _digest(data),
            )
        reads[path] = result
        return result

    while pending or bodies:
        if pending:
            item = pending.popleft()
            if item.state != "candidate":
                items.append(item)
                continue
            result = read(item.path)
            items.append(
                replace(
                    item,
                    state=result.state,
                    size=result.size,
                    sha256=result.sha256,
                    diagnostics=(*item.diagnostics, result.diagnostic)
                    if result.diagnostic
                    else item.diagnostics,
                )
            )
            if result.payload is not None:
                bodies.append(item.path)
            continue
        path = _path(bodies.popleft())
        if path in scanned:
            continue
        scanned.add(path)
        if safe_relative_path(path) is None:
            diagnostics.append(
                ResourceCandidateDiagnostic(path, "body", "资源来源路径不安全，未读取")
            )
            continue
        result = read(path)
        if result.payload is None:
            diagnostics.append(
                ResourceCandidateDiagnostic(
                    path, "body", f"{result.state}: {result.diagnostic}"
                )
            )
            continue
        pending.extend(data_resource_candidates(path, result.payload))
    return items


def _data_values(
    source: str, text: str
) -> Iterable[tuple[int, int, str, str, tuple[str, ...]]]:
    if _extension(source) == "slk":
        records, cells, _diagnostics = read_slk_records(text)
        for cell in cells:
            if cell.value is None:
                continue
            record = records[cell.record_index]
            field = record.fields[cell.field_index]
            notes = (
                ()
                if cell.valid
                else (
                    "SLK 单元格含未确认的表达式或字段；未读取缓存路径。"
                    f"完整原始记录: {record.raw!r}",
                )
            )
            yield field.start, field.end, cell.value, "SLK K cell", notes
        return
    offset = 0
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        stripped = body.lstrip()
        if not stripped or stripped.startswith(("//", "--", "#", ";")):
            offset += len(line)
            continue
        literals = tuple(script_literals(body, lua=None))
        for literal in literals:
            yield (
                offset + literal.start,
                offset + literal.end,
                literal.value,
                "quoted data value",
                (),
            )
        if not literals:
            visible = script_views(body, lua=None).arguments.strip()
            value = visible.split("=", 1)[-1].strip() if "=" in visible else visible
            if _looks_like_resource(value):
                start = body.find(value)
                yield (
                    offset + start,
                    offset + start + len(value),
                    value,
                    "text field/line",
                    (),
                )
        offset += len(line)


def _path_state(value: str) -> tuple[str, tuple[str, ...]]:
    if safe_relative_path(value) is None or any(ord(char) < 32 for char in value):
        return "unsafe", ("非安全相对资源路径，保留原值但未读取",)
    return "candidate", ()


def _parentheses(syntax: str) -> dict[int, int]:
    """Index prepared syntax once; literal grouping has no nesting quota."""
    opened: list[int] = []
    pairs: dict[int, int] = {}
    for match in re.finditer(r"[()]", syntax):
        if match.group() == "(":
            opened.append(match.start())
        elif opened:
            pairs[opened.pop()] = match.start()
    return pairs


def _concatenated(
    syntax: str, start: int, end: int, parentheses: dict[int, int], call_opens: set[int]
) -> bool:
    # Strip only actual grouping parentheses, never a surrounding call's argument
    # list. Operators outside any number of transparent wrappers still apply to
    # the literal; concatenation of a call's *result* does not change its input.
    while True:
        left = start - 1
        while left >= 0 and syntax[left].isspace():
            left -= 1
        if (
            left >= 0
            and (syntax[left] == "+" or syntax[max(0, left - 1) : left + 1] == "..")
            or _CONCAT_AFTER.match(syntax, end) is not None
        ):
            return True
        right = end
        while right < len(syntax) and syntax[right].isspace():
            right += 1
        if left in call_opens or parentheses.get(left) != right:
            return False
        start, end = left, right + 1


def _looks_like_resource(value: str) -> bool:
    return _extension(value) in RESOURCE_EXTS


def _path(value: str) -> str:
    # Keep original path bytes/case in value; archive probes use its exact spelling.
    return value.replace("/", "\\")


def _extension(value: str) -> str:
    return value.rsplit(".", 1)[-1].lower() if "." in value else ""


def _language(lua: bool | None) -> str:
    return "Lua" if lua else "JASS" if lua is False else "unknown"


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def format_resource_candidate_report_tsv(report: ResourceCandidateReport) -> str:
    """Serialize every occurrence, failed read and source diagnostic reversibly."""
    rows = [
        (
            "候选路径",
            "类型",
            "状态",
            "来源",
            "来源类型",
            "语言",
            "行",
            "偏移",
            "结束偏移",
            "原始证据",
            "完整值",
            "来源指纹",
            "所属函数",
            "绑定",
            "实读字节",
            "实读SHA256",
            "诊断",
            "字面量结果字节HEX",
            "字面量字节解码编码",
            "字面量源编码",
            "字面量解码完整",
        )
    ]
    rows.extend(
        (
            item.path,
            resource_kind(item.path),
            item.state,
            item.source,
            item.source_kind,
            item.language,
            str(item.line),
            str(item.offset),
            str(item.end_offset),
            item.raw,
            item.value,
            item.source_fingerprint,
            item.owner,
            item.binding,
            str(item.size) if item.size is not None else "",
            item.sha256,
            "\n".join(item.diagnostics),
            item.literal_bytes.hex() if item.literal_bytes is not None else "",
            item.literal_encoding,
            item.literal_source_encoding,
            str(item.literal_complete).lower()
            if item.literal_complete is not None
            else "",
        )
        for item in report.items
    )
    rows.extend(
        (
            "",
            "",
            "diagnostic",
            item.source,
            item.stage,
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            item.detail,
            "",
            "",
            "",
            "",
        )
        for item in report.diagnostics
    )
    rows.append(
        (
            "",
            "",
            "coverage",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "仅按来源声明验证候选；未命名/未知块与既有提取缺口仍未确认",
            "",
            "",
            "",
            "",
        )
    )
    return format_tsv_rows(rows)
