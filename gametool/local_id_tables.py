"""Lossless, source-bound imports of explicitly selected local box ID tables.

These tables are external labels, not object definitions for the current map.
Only the four documented filenames declare a category during directory import.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
import hashlib
import os
from pathlib import Path
import stat

from .bounded_file import FileIdentity, read_bounded_regular_file
from .object_codes import valid_object_code
from .pack_query_objects import OBJECT_TABLES, object_category
from .reference_models import ReferenceCatalog, ReferenceRecord, ReferenceSource
from .save_source_paths import iter_save_source_files, save_source_path_error


BOX_ID_FILENAMES = {
    "单位ID.txt": "单位",
    "技能ID.txt": "技能",
    "物品ID.txt": "物品",
    "科技ID.txt": "科技",
}
_BOX_ID_CATEGORIES = {
    name.casefold(): category for name, category in BOX_ID_FILENAMES.items()
}
EXTERNAL_ID_STATE = "external-unverified"


@dataclass(frozen=True, slots=True)
class LocalIdTableInput:
    """An explicit format selection, with an optional declared object category."""

    path: str | Path
    category: str = ""


type LocalIdTablePath = str | Path | LocalIdTableInput
type _PathBinding = tuple[tuple[str, int, int, int, int], ...]


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    path: Path
    identity: FileIdentity
    metadata: tuple[int, ...]
    binding: _PathBinding
    sha256: str


@dataclass(frozen=True, slots=True)
class _DirectorySnapshot:
    path: Path
    files: tuple[Path, ...]
    diagnostics: tuple[str, ...]
    binding: _PathBinding


@dataclass(frozen=True, slots=True)
class _Line:
    content: str
    ending: str
    start: int
    end: int
    number: int


def _metadata(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_mode,
        getattr(value, "st_file_attributes", 0),
    )


def _path_binding(path: Path) -> _PathBinding:
    if problem := save_source_path_error(path):
        raise OSError(problem)
    binding = []
    for component in reversed((path, *path.parents)):
        value = component.lstat()
        binding.append(
            (
                str(component),
                value.st_dev,
                value.st_ino,
                value.st_mode,
                getattr(value, "st_file_attributes", 0),
            )
        )
    return tuple(binding)


def _decode(payload: bytes) -> tuple[str, str, int]:
    if payload.startswith(b"\xef\xbb\xbf"):
        return payload[3:].decode("utf-8", errors="strict"), "utf-8", 3
    errors = []
    for encoding in ("utf-8", "cp936", "gb18030"):
        try:
            return payload.decode(encoding, errors="strict"), encoding, 0
        except UnicodeError as exc:
            errors.append(f"{encoding}: {exc}")
    raise ValueError("不支持的严格文本编码；" + "；".join(errors))


def _lines(payload: bytes, encoding: str, bom_bytes: int) -> tuple[_Line, ...]:
    # The supported encodings cannot embed CR/LF inside a multibyte character.
    # Offsets are measured from original bytes, never from re-encoded Unicode.
    lines = []
    offset = bom_bytes
    for number, raw in enumerate(payload[bom_bytes:].splitlines(keepends=True), 1):
        text = raw.decode(encoding, errors="strict")
        ending = (
            "\r\n"
            if text.endswith("\r\n")
            else text[-1:]
            if text.endswith(("\r", "\n"))
            else ""
        )
        content = text[: -len(ending)] if ending else text
        lines.append(_Line(content, ending, offset, offset + len(raw), number))
        offset += len(raw)
    return tuple(lines)


def _raw_diagnostic(
    path: Path,
    reason: str,
    raw: str,
    payload: bytes,
    start: int,
    end: int,
    line_start: int,
    line_end: int,
) -> str:
    return (
        f"{path}: {reason}；字节 [{start}, {end})，物理行 {line_start}..{line_end}。"
        f"\n原始记录：\n{raw}\n原始字节 hex：{payload.hex()}"
    )


def _record_starts(lines: tuple[_Line, ...]) -> tuple[int, ...]:
    """Require declared roles before splitting arbitrary description text.

    A repeated name role followed by a description is a proved malformed
    record. Keep its boundary and ordinal so the full rejected block remains
    diagnostic evidence instead of becoming the preceding object's text.
    """
    starts = []
    for index, line in enumerate(lines):
        if not line.content.startswith("ID："):
            continue
        role = index + 1
        while role < len(lines) and lines[role].content.startswith("名字："):
            role += 1
        if (
            role > index + 1
            and role < len(lines)
            and lines[role].content.startswith("描述：")
        ):
            starts.append(index)
    return tuple(starts)


def _declared_category(
    path: Path, explicit: str, preamble: tuple[_Line, ...]
) -> tuple[str, tuple[str, ...]]:
    declarations: list[tuple[str, str]] = []
    if explicit:
        declarations.append(("显式分类参数", explicit))
    if filename_category := _BOX_ID_CATEGORIES.get(path.name.casefold()):
        declarations.append(("已声明文件名", filename_category))
    source_declarations = [
        line.content[3:]
        for line in preamble
        if line.content.startswith(("分类：", "类别："))
    ]
    diagnostics = []
    if len(source_declarations) > 1:
        diagnostics.append(
            f"文件头有多个分类角色 {source_declarations!r}，未选择其中任意一个分类声明。"
        )
    elif source_declarations:
        declarations.append(("文件头分类声明", source_declarations[0]))
    categories = {object_category(value) for _, value in declarations}
    invalid = [
        f"{role}={value!r}"
        for role, value in declarations
        if object_category(value) not in OBJECT_TABLES
    ]
    if invalid:
        diagnostics.append("分类声明无法识别：" + " / ".join(invalid))
    if len(categories) > 1:
        diagnostics.append(
            "分类声明冲突："
            + " / ".join(f"{role}={value!r}" for role, value in declarations)
        )
    category = (
        next(iter(categories)) if len(categories) == 1 and not diagnostics else ""
    )
    return category, tuple(diagnostics)


def _parse_records(
    path: Path, payload: bytes, category: str
) -> tuple[tuple[ReferenceRecord, ...], tuple[str, ...], str]:
    text, encoding, bom_bytes = _decode(payload)
    lines = _lines(payload, encoding, bom_bytes)
    starts = _record_starts(lines)
    if not starts:
        note = _raw_diagnostic(
            path,
            "没有可确认的 ID：/名字：/描述：连续角色记录，未将此文件导入对象目录",
            text,
            payload,
            0,
            len(payload),
            1,
            len(lines),
        )
        return (), (note,), encoding
    preamble = lines[: starts[0]]
    declared, category_notes = _declared_category(path, category, preamble)
    diagnostics = [f"{path}: {note}" for note in category_notes]
    if category_notes and preamble:
        end = preamble[-1].end
        diagnostics.append(
            _raw_diagnostic(
                path,
                "分类来源未确认，保留完整文件头证据",
                payload[bom_bytes:end].decode(encoding),
                payload[bom_bytes:end],
                bom_bytes,
                end,
                1,
                preamble[-1].number,
            )
        )
    unknown_preamble = [
        line
        for line in preamble
        if line.content and not line.content.startswith(("分类：", "类别："))
    ]
    if unknown_preamble:
        end = preamble[-1].end
        diagnostics.append(
            _raw_diagnostic(
                path,
                "记录前存在未识别内容，保留完整文件头证据",
                payload[bom_bytes:end].decode(encoding),
                payload[bom_bytes:end],
                bom_bytes,
                end,
                1,
                preamble[-1].number,
            )
        )
    records = []
    boundaries = (*starts, len(lines))
    for ordinal, (begin, end) in enumerate(zip(boundaries, boundaries[1:]), 1):
        block = list(lines[begin:end])
        start_byte, end_byte = block[0].start, block[-1].end
        raw_bytes = payload[start_byte:end_byte]
        raw = raw_bytes.decode(encoding, errors="strict")
        code = block[0].content[3:]
        problems = []
        if not valid_object_code(code):
            problems.append(f"ID={code!r} 不是完整四字节 Latin-1 身份")
        if (
            len(block) < 3
            or not block[1].content.startswith("名字：")
            or not block[2].content.startswith("描述：")
        ):
            problems.append(
                "记录必须按唯一位置声明 ID：、名字：、描述：；未猜测缺失或重复角色"
            )
        if problems:
            diagnostics.append(
                _raw_diagnostic(
                    path,
                    "；".join(problems),
                    raw,
                    raw_bytes,
                    start_byte,
                    end_byte,
                    block[0].number,
                    block[-1].number,
                )
            )
            continue
        name = block[1].content[3:]
        description = (
            block[2].content[3:]
            + block[2].ending
            + "".join(line.content + line.ending for line in block[3:])
        )
        records.append(
            ReferenceRecord(
                "objects",
                code,
                name,
                declared,
                scope="external",
                sources=(str(path),),
                state=EXTERNAL_ID_STATE,
                details=(
                    ("身份来源", "显式选择的本地盒子 ID 文本，外部未验证"),
                    ("描述", description),
                    ("来源", str(path)),
                    ("编码", encoding),
                    ("记录序号", str(ordinal)),
                    ("字节起点", str(start_byte)),
                    ("字节终点（不含）", str(end_byte)),
                    ("起始行", str(block[0].number)),
                    ("结束行", str(block[-1].number)),
                    ("记录SHA-256", hashlib.sha256(raw_bytes).hexdigest()),
                    (
                        "文件头声明",
                        "".join(line.content + line.ending for line in preamble),
                    ),
                    (
                        "可用性",
                        "build、基础ID、自定义标记及当前地图存在性均未知；请用知识包或 live 另行查证。",
                    ),
                ),
                diagnostics=category_notes,
                raw_rows=((raw, raw_bytes.hex()),),
            )
        )
    return tuple(records), tuple(diagnostics), encoding


class LocalIdTableSources:
    """One uncached import and its final source/namespace verification boundary."""

    def __init__(self, inputs: Iterable[LocalIdTablePath] = ()) -> None:
        self.records: list[ReferenceRecord] = []
        self.sources: dict[str, ReferenceSource] = {}
        self.diagnostics: list[str] = []
        self.input_roots: tuple[str, ...] = ()
        self._snapshots: list[_FileSnapshot] = []
        self._directories: list[_DirectorySnapshot] = []
        roots = []
        selections: dict[Path, list[str]] = defaultdict(list)
        for selected in inputs:
            request = (
                selected
                if isinstance(selected, LocalIdTableInput)
                else LocalIdTableInput(selected)
            )
            path = Path(request.path).absolute()
            roots.append(str(path))
            try:
                binding = _path_binding(path)
                directory = stat.S_ISDIR(path.lstat().st_mode)
            except OSError as exc:
                self.diagnostics.append(f"{path}: ID 表来源路径不可安全读取：{exc}")
                continue
            files, notes = iter_save_source_files(path)
            self.diagnostics.extend(notes)
            if directory:
                self._directories.append(
                    _DirectorySnapshot(path, files, tuple(notes), binding)
                )
            accepted = 0
            for file in files:
                if file.name.casefold() not in _BOX_ID_CATEGORIES and directory:
                    self.diagnostics.append(
                        f"{file}: 未导入；目录只识别单位ID.txt、技能ID.txt、物品ID.txt、科技ID.txt 四个声明的盒子 ID 文件名。"
                    )
                    continue
                if file.suffix.casefold() != ".txt":
                    self.diagnostics.append(
                        f"{file}: 未导入；显式盒子 ID 文件必须是 .txt 文本。"
                    )
                    continue
                accepted += 1
                if request.category:
                    selections[file].append(request.category)
                else:
                    selections.setdefault(file, [])
            if not accepted:
                self.diagnostics.append(
                    f"{path}: 没有导入可识别的盒子 ID 文本；请显式选择 ID 表文件或包含四个声明文件名的实际目录。"
                )
        for path, declarations in selections.items():
            categories = {object_category(value) for value in declarations}
            first_record = len(self.records)
            # Each pathname is read once. Multiple requests cannot replace its
            # original source hash while leaving records from an earlier read.
            self._read(path, next(iter(categories)) if len(categories) == 1 else "")
            if len(categories) > 1:
                note = (
                    f"{path}: 同一来源收到冲突的显式分类参数 {declarations!r}；"
                    "保留一次原始快照，全部记录保持未分类。"
                )
                self.diagnostics.append(note)
                for index in range(first_record, len(self.records)):
                    record = self.records[index]
                    self.records[index] = replace(
                        record,
                        category="",
                        diagnostics=(*record.diagnostics, note),
                    )
        self.input_roots = tuple(dict.fromkeys(roots))
        self._mark_duplicates()

    def _read(self, path: Path, category: str) -> None:
        try:
            binding = _path_binding(path)
            before = _metadata(path.lstat())
            payload, identity = read_bounded_regular_file(path)
            if binding != _path_binding(path) or before != _metadata(path.lstat()):
                raise OSError("来源路径或身份在读取时变化")
        except OSError as exc:
            self.diagnostics.append(f"{path}: ID 表读取失败：{exc}")
            return
        digest = hashlib.sha256(payload).hexdigest()
        self._snapshots.append(_FileSnapshot(path, identity, before, binding, digest))
        self.sources[str(path)] = ReferenceSource(
            str(path),
            str(path),
            digest,
            "调用方显式选择的盒子 ID 文本；SHA-256 绑定原始文件字节，所有标签均为外部未验证，未推断游戏 build/地图存在性/基础ID/自定义状态。",
            state=EXTERNAL_ID_STATE,
            source_file_sha256=digest,
            source_file_state="stable-snapshot",
        )
        try:
            records, notes, _ = _parse_records(path, payload, category)
        except (UnicodeError, ValueError) as exc:
            self.diagnostics.append(
                f"{path}: 盒子 ID 文本解码失败：{exc}；原始字节 hex：{payload.hex()}"
            )
            return
        self.records.extend(records)
        self.diagnostics.extend(notes)

    def _mark_duplicates(self) -> None:
        groups: dict[tuple[str, str], list[int]] = defaultdict(list)
        for index, record in enumerate(self.records):
            groups[(record.category, record.id)].append(index)
        for indexes in groups.values():
            if len(indexes) < 2:
                continue
            competing = [self.records[index] for index in indexes]
            evidence = {
                (record.label, dict(record.details)["描述"]) for record in competing
            }
            locations = " / ".join(
                f"{record.sources[0]}:行{dict(record.details)['起始行']}"
                for record in competing
            )
            note = (
                f"外部同类别同ID记录 {len(indexes)} 条"
                + ("，名字/描述冲突" if len(evidence) > 1 else "，重复原始记录")
                + f"；全部独立保留，未裁决覆盖顺序：{locations}"
            )
            for index in indexes:
                record = self.records[index]
                self.records[index] = replace(
                    record, diagnostics=(*record.diagnostics, note)
                )

    def verify(self) -> None:
        """Recheck complete hashes, identities and non-reparse lexical ancestry."""
        for directory in self._directories:
            try:
                files, notes = iter_save_source_files(directory.path)
                stable = (
                    _path_binding(directory.path) == directory.binding
                    and files == directory.files
                    and tuple(notes) == directory.diagnostics
                )
            except OSError:
                stable = False
            if not stable:
                self.diagnostics.append(
                    f"{directory.path}: ID 表目录的来源路径或完整文件清单在交付前变化；保留已读快照，请刷新。"
                )
        for snapshot in self._snapshots:
            try:
                payload, identity = read_bounded_regular_file(
                    snapshot.path, expected=snapshot.identity
                )
                stable = (
                    identity == snapshot.identity
                    and _metadata(snapshot.path.lstat()) == snapshot.metadata
                    and _path_binding(snapshot.path) == snapshot.binding
                    and hashlib.sha256(payload).hexdigest() == snapshot.sha256
                )
            except OSError:
                stable = False
            if not stable:
                self.diagnostics.append(
                    f"{snapshot.path}: ID 表来源字节、身份或路径在交付前变化；SHA-256 仅绑定以上已读原始快照，请刷新。"
                )
                source = self.sources[str(snapshot.path)]
                self.sources[str(snapshot.path)] = replace(
                    source, source_file_state="changed-before-delivery"
                )

    def catalog(self) -> ReferenceCatalog:
        """Expose all confirmed records and every rejected-source diagnostic."""
        return ReferenceCatalog(
            tuple(self.records),
            tuple(self.sources.values()),
            tuple(self.diagnostics),
            self.input_roots,
        )


def load_local_id_tables(inputs: Iterable[LocalIdTablePath] = ()) -> ReferenceCatalog:
    """Read explicitly selected tables and verify them before returning evidence."""
    sources = LocalIdTableSources(inputs)
    sources.verify()
    return sources.catalog()
