"""Source-first, read-only call evidence over an immutable knowledge-pack snapshot."""

from __future__ import annotations

from collections.abc import Iterator
import csv
from dataclasses import dataclass, replace
import io
import json
from pathlib import Path
import re

from .csv_fields import full_csv_fields
from .pack_query_call_records import CallRecord, call_argument_index
from .pack_query_options import query_limit_error
from .pack_query_script_coverage import (
    ScriptCoverage,
    ScriptCoverageSource,
    build_script_coverage,
)
from .pack_query_script_snapshot import (
    SCRIPT_INDEX,
    ScriptFileSnapshot,
    ScriptPackSnapshot,
    capture_script_pack,
    verify_script_pack,
)
from .pack_query_text_records import TextRecord
from .presentation_safety import tsv_cell
from .script_assignments import expression_key
from .script_behavior_index import build_script_behavior_index
from .script_call_query_models import (
    ScriptCallIndexRow,
    ScriptCallQueryDiagnostic,
    ScriptCallQueryRecord,
    ScriptCallQueryResult,
)
from .script_source_identity import ScriptSourceNames
from .script_sources import (
    AnalysisScriptSource,
    analysis_script_text,
    script_language,
    script_type_from_report,
)
from .search import compile_query


@dataclass(slots=True)
class _IndexGroup:
    source: str
    offset: str
    rows: list[tuple[CallRecord, ScriptCallIndexRow]]


def _raw_bytes(payload: bytes) -> str:
    return payload.decode("utf-8", errors="backslashreplace")


def _decoded(
    item: ScriptFileSnapshot, diagnostics: list[ScriptCallQueryDiagnostic], *, bom: bool
) -> str | None:
    if item.state != "file":
        return None
    try:
        return item.payload.decode("utf-8-sig" if bom else "utf-8")
    except UnicodeError as error:
        diagnostics.append(
            ScriptCallQueryDiagnostic(
                item.relative,
                "source.encoding",
                f"UTF-8 解码失败，未猜测文本或调用；完整字节以反斜杠转义展示: {error}",
                _raw_bytes(item.payload),
            )
        )
        return None


def _table_records(
    item: ScriptFileSnapshot, diagnostics: list[ScriptCallQueryDiagnostic]
) -> tuple[TextRecord, ...]:
    text = _decoded(item, diagnostics, bom=True)
    if text is None:
        return ()
    pending: list[str] = []
    stream = io.StringIO(text, newline="")

    def lines() -> Iterator[str]:
        for line in stream:
            pending.append(line)
            yield line

    reader = csv.reader(lines(), delimiter="\t", strict=True)
    records: list[TextRecord] = []
    while True:
        try:
            with full_csv_fields():
                cells = next(reader)
        except StopIteration:
            return tuple(records)
        except csv.Error as error:
            # The pending suffix and every confirmed preceding record survive.
            diagnostics.append(
                ScriptCallQueryDiagnostic(
                    item.relative,
                    "index.csv",
                    f"逻辑 TSV 记录解析失败；保留已确认记录和未解析原文: {error}",
                    "".join(pending) + stream.read(),
                    len(records) + 1,
                )
            )
            return tuple(records)
        raw = "".join(pending)
        pending.clear()
        if raw.endswith("\r\n"):
            raw = raw[:-2]
        elif raw.endswith(("\r", "\n")):
            raw = raw[:-1]
        records.append(TextRecord(tuple(cells), raw))


def _load_snapshot(
    snapshot: ScriptPackSnapshot, diagnostics: list[ScriptCallQueryDiagnostic]
) -> tuple[tuple[AnalysisScriptSource, ...], tuple[TextRecord, ...], ScriptCoverage]:
    files = {item.relative: item for item in snapshot.files}
    info = _decoded(files["地图信息.txt"], diagnostics, bom=True) or ""
    declared = script_type_from_report(info)
    prefix = snapshot.source_directory + "/"
    decoded: list[tuple[str, str]] = []
    failures = [item.source for item in snapshot.problems]
    for item in snapshot.files:
        if not item.relative.startswith(prefix) or item.state != "file":
            continue
        text = _decoded(item, diagnostics, bom=False)
        if text is None:
            failures.append(item.relative)
            continue
        if not snapshot.original:
            text = text.replace("\r\n", "\n").replace("\r", "\n")
        decoded.append((item.relative.removeprefix(prefix), text))
    names = tuple(name for name, _text in decoded)
    contexts = tuple(
        AnalysisScriptSource(
            name,
            analysis_script_text(
                name,
                text,
                lua := script_language(
                    name, available_sources=names, declared_script_type=declared
                ),
            ),
            lua,
        )
        for name, text in decoded
    )
    if snapshot.original:
        original_names = {
            item.relative.removeprefix(prefix)
            for item in snapshot.files
            if item.relative.startswith(prefix)
        }
        readable_prefix = "脚本可读文本/"
        failures.extend(
            prefix + item.relative.removeprefix(readable_prefix)
            for item in snapshot.files
            if item.relative.startswith(readable_prefix)
            and item.relative.removeprefix(readable_prefix) not in original_names
        )
        if not contexts:
            failures.append(snapshot.source_directory)
    rows = {
        relative: _table_records(files[relative], diagnostics)
        for relative in (SCRIPT_INDEX, "脚本清单.txt", "组件诊断.tsv")
    }
    encrypted_file = files["未知文件/加密脚本检测.txt"]
    encrypted = _decoded(encrypted_file, diagnostics, bom=True)
    coverage = build_script_coverage(
        snapshot.pack,
        contexts,
        source_directory=snapshot.source_directory,
        encrypted_report=(
            tuple((line,) for line in encrypted.splitlines())
            if encrypted is not None
            else None
        ),
        manifest=tuple(row.cells for row in rows["脚本清单.txt"]),
        component_rows=tuple(row.cells for row in rows["组件诊断.tsv"]),
        read_failures=tuple(dict.fromkeys(failures)),
    )
    return contexts, rows[SCRIPT_INDEX], coverage


def _index_groups(
    rows: tuple[TextRecord, ...],
    fingerprint: str,
    names: ScriptSourceNames,
    diagnostics: list[ScriptCallQueryDiagnostic],
) -> tuple[list[_IndexGroup], list[ScriptCallQueryRecord]]:
    parsed = call_argument_index(tuple(row.cells for row in rows))
    diagnostics.extend(
        ScriptCallQueryDiagnostic(SCRIPT_INDEX, "index.schema", note)
        for note in parsed.diagnostics
    )
    groups: list[_IndexGroup] = []
    explicit: dict[tuple[str, str], _IndexGroup] = {}
    previous: tuple[str, ...] = ()
    consecutive: _IndexGroup | None = None
    for record in parsed.records:
        original = rows[record.ordinal - 1]
        evidence = ScriptCallIndexRow(
            SCRIPT_INDEX,
            record.ordinal,
            original.cells,
            original.text,
            record.row,
            fingerprint,
        )
        source = names.resolve(record.row[0]).key
        if record.offset:
            previous, consecutive = (), None
            key = source, record.offset
            group = explicit.get(key)
            if group is None:
                group = explicit[key] = _IndexGroup(source, record.offset, [])
                groups.append(group)
        else:
            identity = (source, *record.row[1:4])
            position = _decimal(record.row[4])
            if (
                consecutive is None
                or previous != identity
                or position == "1"
                or not position
                or position != str(len(consecutive.rows) + 1)
            ):
                consecutive = _IndexGroup(source, "", [])
                groups.append(consecutive)
            previous, group = identity, consecutive
        group.rows.append((record, evidence))
    retained = {record.ordinal for record in parsed.records}
    first_nonempty = next(
        (
            ordinal
            for ordinal, row in enumerate(rows, 1)
            if any(cell.strip() for cell in row.cells)
        ),
        None,
    )
    header_probe = (
        call_argument_index((rows[first_nonempty - 1].cells,))
        if first_nonempty is not None
        else None
    )
    declared_header = (
        first_nonempty
        if header_probe is not None
        and not header_probe.records
        and not header_probe.diagnostics
        else None
    )
    # A schema may be unusable, but none of its original evidence disappears.
    unparsed = []
    for ordinal, row in enumerate(rows, 1):
        if ordinal in retained or not any(cell.strip() for cell in row.cells):
            continue
        # A valid declared header is schema metadata, not a fabricated call.
        if ordinal == declared_header:
            continue
        note = ScriptCallQueryDiagnostic(
            SCRIPT_INDEX,
            "index.unparsed",
            "未能确认此逻辑记录的调用角色；保留完整原始单元格，可用 text 核对。",
            row.text,
            ordinal,
        )
        diagnostics.append(note)
        unparsed.append(
            ScriptCallQueryRecord(
                "index-unparsed",
                SCRIPT_INDEX,
                "unknown",
                "",
                "",
                "",
                "",
                "unknown",
                (),
                row.text,
                index_rows=(
                    ScriptCallIndexRow(
                        SCRIPT_INDEX,
                        ordinal,
                        row.cells,
                        row.text,
                        file_fingerprint=fingerprint,
                    ),
                ),
                diagnostics=(note,),
            )
        )
    return groups, unparsed


def _decimal(value: str) -> str:
    stripped = value.strip()
    return (
        stripped.lstrip("0") or "0"
        if stripped and stripped.isascii() and stripped.isdecimal()
        else ""
    )


def _unique(values: Iterator[str]) -> str:
    choices = set(filter(None, values))
    return next(iter(choices)) if len(choices) == 1 else ""


def _group_record(group: _IndexGroup) -> ScriptCallQueryRecord:
    rows = tuple(item for _record, item in group.rows)
    semantic = [record for record, _item in group.rows]
    problems: list[ScriptCallQueryDiagnostic] = []

    def problem(message: str) -> None:
        problems.append(
            ScriptCallQueryDiagnostic(
                SCRIPT_INDEX,
                "index.conflict",
                message,
                "\n".join(row.raw for row in rows),
                rows[0].ordinal,
            )
        )

    for column, label in ((0, "来源"), (2, "所属函数"), (3, "调用名称")):
        values = {record.row[column] for record in semantic if record.row[column]}
        if column != 0 and len(values) > 1:
            problem(f"同一索引调用的{label}存在冲突，未选择其中一个值。")
    arguments: dict[str, str] = {}
    for record in semantic:
        if not record.row[4]:
            continue
        position = _decimal(record.row[4])
        if not position or position == "0":
            problem("参数序号不是正十进制数，未据此推断参数位置。")
        elif position in arguments and arguments[position] != record.row[5]:
            problem(f"参数序号 {position} 的值存在冲突，未选择其中一个值。")
        else:
            arguments[position] = record.row[5]
    ordered = tuple(str(index) for index in range(1, len(arguments) + 1))
    if arguments and any(position not in arguments for position in ordered):
        problem("参数序号不连续，未填充缺失参数或按编码序号分配内存。")
    summaries = tuple(
        dict.fromkeys(record.summary for record in semantic if record.summary)
    )
    lua = script_language(group.source)
    distinct = (
        {_summary_key(summary, lua) for summary in summaries}
        if lua is not None
        else set(summaries)
    )
    if len(distinct) > 1:
        problem("同一索引调用有不一致的完整摘要，未选择其中一份作为源码。")
    return ScriptCallQueryRecord(
        "index",
        group.source,
        "unknown",
        _unique(record.row[1] for record in semantic),
        group.offset,
        _unique(record.row[3] for record in semantic),
        _unique(record.row[2] for record in semantic),
        "index-declared",
        tuple(arguments[position] for position in ordered) if not problems else (),
        "\n".join(summaries),
        index_rows=rows,
        diagnostics=tuple(dict.fromkeys(problems)),
    )


def _summary_key(summary: str, lua: bool) -> str:
    if not lua:
        summary = re.sub(r"^\s*call\s+", "", summary)
    return expression_key(summary, lua=lua)


def _merge_indexes(
    source_records: list[ScriptCallQueryRecord],
    groups: list[_IndexGroup],
    names: ScriptSourceNames,
    original: bool,
    diagnostics: list[ScriptCallQueryDiagnostic],
) -> list[ScriptCallQueryRecord]:
    offsets: dict[tuple[str, str], list[int]] = {}
    expressions: dict[tuple[str, str], list[int]] = {}
    languages: dict[str, str] = {}
    for index, record in enumerate(source_records):
        if record.call is None:
            continue
        offsets.setdefault((record.source, record.offset), []).append(index)
        languages[record.source] = record.language
        if record.language in {"Lua", "JASS"}:
            key = expression_key(record.raw, lua=record.language == "Lua")
            expressions.setdefault((record.source, key), []).append(index)
    result = list(source_records)
    for group in groups:
        indexed = _group_record(group)
        notes = list(indexed.diagnostics)
        source_labels = tuple(
            dict.fromkeys(record.row[0] for record, _row in group.rows)
        )
        matches = [names.resolve(label) for label in source_labels]
        unique_sources = {source for match in matches for source in match.sources}
        ambiguous = (
            any(match.diagnostic for match in matches) or len(unique_sources) > 1
        )
        candidate: int | None = None
        if ambiguous:
            notes.append(
                ScriptCallQueryDiagnostic(
                    SCRIPT_INDEX,
                    "index.source_ambiguous",
                    "；".join(
                        dict.fromkeys(
                            match.diagnostic for match in matches if match.diagnostic
                        )
                    ),
                    "\n".join(row.raw for row in indexed.index_rows),
                )
            )
        elif names.exact and any(not label.strip() for label in source_labels):
            notes.append(
                ScriptCallQueryDiagnostic(
                    SCRIPT_INDEX,
                    "index.source_missing",
                    "索引未记录来源，无法确认是源码镜像还是独立记录，未猜测原生绑定。",
                    "\n".join(row.raw for row in indexed.index_rows),
                )
            )
        elif len(unique_sources) == 1:
            source = next(iter(unique_sources))
            if original and group.offset:
                candidates = offsets.get((source, group.offset), [])
                # Chained dynamic calls can share their first character. Use
                # declared identity only to distinguish candidates at that site.
                if len(candidates) > 1 and indexed.callee:
                    candidates = [
                        item
                        for item in candidates
                        if source_records[item].callee == indexed.callee
                    ]
                if len(candidates) > 1:
                    summaries = {
                        item.summary for item, _row in group.rows if item.summary
                    }
                    candidates = [
                        item
                        for item in candidates
                        if any(
                            summary
                            in {
                                source_records[item].raw,
                                tsv_cell(source_records[item].raw),
                            }
                            for summary in summaries
                        )
                    ]
            else:
                candidates_set: set[int] = set()
                language = languages.get(source, "unknown")
                if language in {"Lua", "JASS"}:
                    for record, _row in group.rows:
                        if record.summary:
                            key = _summary_key(record.summary, language == "Lua")
                            candidates_set.update(expressions.get((source, key), ()))
                candidates = sorted(candidates_set)
            if len(candidates) == 1:
                candidate = candidates[0]
            else:
                notes.append(
                    ScriptCallQueryDiagnostic(
                        SCRIPT_INDEX,
                        "index.site_unverified",
                        "索引与源码的调用位置未唯一对应，保留索引证据但未计为已确认的独立源码调用。",
                        "\n".join(row.raw for row in indexed.index_rows),
                    )
                )
        elif original:
            notes.append(
                ScriptCallQueryDiagnostic(
                    SCRIPT_INDEX,
                    "index.source_missing",
                    "原始脚本边界已存在，但索引来源缺失或读取失败；未从摘要推断原生绑定或控制流。",
                    "\n".join(row.raw for row in indexed.index_rows),
                )
            )
        if candidate is None:
            if not notes:
                notes.append(
                    ScriptCallQueryDiagnostic(
                        SCRIPT_INDEX,
                        "index.unverified",
                        "仅有索引声明，未确认源码位置、标准 API 绑定、控制条件或运行效果。",
                    )
                )
            result.append(replace(indexed, diagnostics=tuple(notes)))
        else:
            source_record = result[candidate]
            source_call = source_record.call
            assert source_call is not None
            actual = {
                str(index): value
                for index, value in enumerate(source_call.arguments, 1)
            }
            for parsed, _row in group.rows:
                if parsed.row[3] and parsed.row[3] != source_call.callee:
                    notes.append(
                        ScriptCallQueryDiagnostic(
                            SCRIPT_INDEX,
                            "index.conflict",
                            "同一来源偏移的调用名与源码不一致；保留源码绑定和全部索引证据。",
                            _row.raw,
                            _row.ordinal,
                        )
                    )
                if parsed.row[2] and parsed.row[2] != source_call.owner:
                    notes.append(
                        ScriptCallQueryDiagnostic(
                            SCRIPT_INDEX,
                            "index.conflict",
                            "同一来源偏移的所属函数与源码不一致；未改写源码所属范围。",
                            _row.raw,
                            _row.ordinal,
                        )
                    )
                if parsed.summary and parsed.summary not in {
                    source_call.raw,
                    tsv_cell(source_call.raw),
                }:
                    notes.append(
                        ScriptCallQueryDiagnostic(
                            SCRIPT_INDEX,
                            "index.summary_unverified",
                            "索引摘要与源码原文或既有显示编码不一致；原始源码仍为调用证据，索引原文完整保留。",
                            _row.raw,
                            _row.ordinal,
                        )
                    )
                position = _decimal(parsed.row[4])
                if position and (
                    position not in actual
                    or parsed.row[5]
                    not in {actual[position], tsv_cell(actual[position])}
                ):
                    notes.append(
                        ScriptCallQueryDiagnostic(
                            SCRIPT_INDEX,
                            "index.conflict",
                            "索引参数与对应源码参数不一致；未根据索引重建或覆盖源码参数。",
                            _row.raw,
                            _row.ordinal,
                        )
                    )
            result[candidate] = replace(
                source_record,
                index_rows=(*source_record.index_rows, *indexed.index_rows),
                diagnostics=(*source_record.diagnostics, *tuple(dict.fromkeys(notes))),
            )
        diagnostics.extend(notes)
    return result


def _search_fields(record: ScriptCallQueryRecord) -> Iterator[str]:
    yield from (
        record.source,
        record.language,
        record.line,
        record.offset,
        record.callee,
        record.owner,
        record.binding,
        record.raw,
        *record.arguments,
    )
    if record.call is not None:
        call = record.call
        yield from (call.canonical, call.category, *call.diagnostics)
        for control in call.controls:
            yield from (control.kind, control.condition, control.selector)
            for predicate in control.predicates:
                yield from (predicate.raw, predicate.role)
        for target in call.targets:
            yield target.name
    for row in record.index_rows:
        yield row.raw
        yield from row.cells
    for note in record.diagnostics:
        yield from (note.code, note.message, note.raw)


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _render_records(
    records: tuple[ScriptCallQueryRecord, ...], total: int, omitted: int
) -> tuple[str, ...]:
    lines = [
        f"脚本调用证据: 匹配 {total} 条；源码调用与未验证索引分别标明。",
        "静态调用、绑定和控制条件不证明该路径已执行或游戏效果成立。",
    ]
    for record in records:
        lines.append(
            f"  [{record.origin}] {_quoted(record.source)}:{record.line or '未记录'} / 偏移 {record.offset or '未记录'} / 调用 {_quoted(record.callee)} / 绑定 {record.binding}"
        )
        lines.append(f"    所属函数: {_quoted(record.owner)}；语言: {record.language}")
        if record.call is not None:
            call = record.call
            lines.append(
                f"    标准名称: {_quoted(call.canonical)}；分类: {_quoted(call.category)}；完整范围: {call.complete}；主调用: {call.primary}"
            )
            lines.append(
                f"    源码字符范围: {call.offset}:{call.end_offset}；文本 SHA-256: {call.source_fingerprint}；文件 SHA-256: {record.source_file_fingerprint}"
            )
            for control in call.controls:
                lines.append(
                    f"    控制 {control.kind} / {control.offset}:{control.end_offset} / 完整: {control.complete} / 条件 {_quoted(control.condition)} / 选择器 {_quoted(control.selector)}"
                )
                for predicate in control.predicates:
                    lines.append(
                        f"      谓词 {predicate.role} / 第 {predicate.line} 行 / {predicate.offset}:{predicate.end_offset} / 否定: {predicate.negated} / 原文 {_quoted(predicate.raw)}"
                    )
            for target in call.targets:
                lines.append(
                    f"    源码目标: {_quoted(target.name)} / 第 {target.line} 行 / {target.offset}:{target.end_offset} / 完整: {target.complete}"
                )
        lines.extend(
            f"    参数 {index}: {_quoted(argument)}"
            for index, argument in enumerate(record.arguments, 1)
        )
        lines.append("    原文: " + _quoted(record.raw))
        for row in record.index_rows:
            lines.append(
                f"    索引 {row.path} / 逻辑记录 {row.ordinal} / SHA-256: {row.file_fingerprint}"
            )
            lines.append(
                "      原始单元格: " + json.dumps(row.cells, ensure_ascii=False)
            )
            lines.append("      完整逻辑记录: " + _quoted(row.raw))
    if omitted:
        lines.append(
            f"  已按显式 --limit 选取完整记录；其余 {omitted} 条未显示，去掉 --limit 查看全量。"
        )
    if not total:
        lines.extend(
            (
                "未找到匹配的调用证据；这不证明地图没有对应行为。",
                "可缩短查询词、空词列出全部，或用 text <词> 查看原始索引证据。",
            )
        )
    return tuple(lines)


def _error(message: str) -> ScriptCallQueryResult:
    return ScriptCallQueryResult(
        (message,), (), 0, 0, (), False, True, True, ScriptCoverage(None)
    )


def query_script_calls(pack: Path, query: str, limit: int = 0) -> ScriptCallQueryResult:
    """Search whole evidence records and revalidate every source before returning."""
    if note := query_limit_error(limit):
        return _error(note)
    compiled = compile_query(query)
    if query.strip() and compiled.is_empty:
        return _error(
            'calls 查询表达式没有关键词；可用 &&、||、%、括号或 ="精准词"，空词列出全部。'
        )
    pack = pack.absolute()
    if not pack.is_dir():
        return _error("资料包目录不存在: " + str(pack))
    snapshot = capture_script_pack(pack)
    diagnostics = [
        ScriptCallQueryDiagnostic(problem.source, problem.code, problem.message)
        for problem in snapshot.problems
    ]
    contexts, rows, coverage = _load_snapshot(snapshot, diagnostics)
    index = build_script_behavior_index(contexts)
    files = {item.relative: item for item in snapshot.files}
    records = [
        ScriptCallQueryRecord(
            "source",
            call.source,
            call.language,
            str(call.line),
            str(call.offset),
            call.callee,
            call.owner,
            call.binding,
            call.arguments,
            call.raw,
            call,
            source_file_fingerprint=files[
                snapshot.source_directory + "/" + call.source
            ].fingerprint,
        )
        for call in index.calls
    ]
    source_sites = {(call.source, call.offset, call.end_offset) for call in index.calls}
    for note in index.diagnostics:
        diagnostic = ScriptCallQueryDiagnostic(
            note.source, note.code, note.message, note.raw, core=note
        )
        diagnostics.append(diagnostic)
        if (note.source, note.offset, note.end_offset) not in source_sites:
            records.append(
                ScriptCallQueryRecord(
                    "diagnostic",
                    note.source,
                    note.language,
                    str(note.line),
                    str(note.offset),
                    "",
                    "",
                    "unknown",
                    (),
                    note.raw,
                    diagnostics=(diagnostic,),
                    source_file_fingerprint=files[
                        snapshot.source_directory + "/" + note.source
                    ].fingerprint,
                )
            )
    names = ScriptSourceNames(source.source for source in contexts)
    groups, unparsed = _index_groups(
        rows, files[SCRIPT_INDEX].fingerprint, names, diagnostics
    )
    records = _merge_indexes(records, groups, names, snapshot.original, diagnostics)
    records.extend(unparsed)
    # Unparsed source/table bytes remain independently searchable recovery evidence.
    for note in tuple(diagnostics):
        if note.raw and note.code in {"source.encoding", "index.csv"}:
            records.append(
                ScriptCallQueryRecord(
                    "diagnostic",
                    note.source,
                    "unknown",
                    "",
                    "",
                    "",
                    "",
                    "unknown",
                    (),
                    note.raw,
                    diagnostics=(note,),
                )
            )
    matched = tuple(
        record
        for record in records
        if compiled.score_fields(_search_fields(record)) is not None
    )
    selected = matched[:limit] if limit else matched
    omitted = len(matched) - len(selected)
    lines = _render_records(selected, len(matched), omitted)
    changed = snapshot.verify()
    diagnostics.extend(
        ScriptCallQueryDiagnostic(problem.source, problem.code, problem.message)
        for problem in changed
    )
    diagnostics = list(dict.fromkeys(diagnostics))
    stable = snapshot.initially_stable and not changed
    rendered_diagnostics = tuple(note.render() for note in diagnostics)
    incomplete = (
        not stable
        or bool(unparsed)
        or any(not call.complete for call in index.calls)
        or any(
            note.code.startswith("script.call.syntax")
            or note.code in {"script.function.incomplete", "script.control.incomplete"}
            for note in diagnostics
        )
        or any(
            note.code.startswith(
                (
                    "source.",
                    "index.csv",
                    "index.schema",
                    "index.conflict",
                    "index.source_",
                    "index.site_",
                    "index.summary_",
                )
            )
            for note in diagnostics
        )
    )
    coverage = ScriptCoverage(
        False if incomplete else coverage.complete,
        tuple(dict.fromkeys((*coverage.diagnostics, *rendered_diagnostics))),
        (
            *coverage.sources,
            *(
                ScriptCoverageSource(str(pack / note.source), note.code)
                for note in diagnostics
            ),
        ),
    )
    lines = (*lines, *(note for note in coverage.diagnostics if note not in lines))
    return ScriptCallQueryResult(
        lines,
        selected,
        len(matched),
        omitted,
        tuple(diagnostics),
        bool(matched),
        not stable,
        stable,
        coverage,
        snapshot.observed_identity(),
    )


def revalidate_script_calls(result: ScriptCallQueryResult) -> ScriptCallQueryResult:
    """Verify the original section snapshot again at final campaign delivery."""
    identity = result.snapshot_identity
    if identity is None:
        return result
    changed = verify_script_pack(identity)
    if not changed:
        return result
    notes = tuple(
        ScriptCallQueryDiagnostic(problem.source, problem.code, problem.message)
        for problem in changed
    )
    diagnostics = tuple(dict.fromkeys((*result.diagnostics, *notes)))
    messages = tuple(note.render() for note in notes)
    coverage = ScriptCoverage(
        False,
        tuple(dict.fromkeys((*result.script_coverage.diagnostics, *messages))),
        tuple(
            dict.fromkeys(
                (
                    *result.script_coverage.sources,
                    *(
                        ScriptCoverageSource(
                            str(Path(identity.pack) / note.source), note.code
                        )
                        for note in notes
                    ),
                )
            )
        ),
    )
    return replace(
        result,
        lines=(*result.lines, *(note for note in messages if note not in result.lines)),
        diagnostics=diagnostics,
        script_coverage=coverage,
        source_stable=False,
        input_error=True,
    )
