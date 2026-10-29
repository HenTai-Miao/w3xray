"""Read-only save evidence, optional map correlation and complete source proof."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final

from .bounded_file import (
    BoundedFileError,
    read_bounded_regular_file,
    sha256_regular_file,
)
from .mpq import MPQArchive
from .mpq_layout import locate_mpq_layout
from .presentation_safety import tsv_cell as _tsv
from .save_analysis import build_save_report
from .save_container import inspect_save_container, looks_like_save_container
from .save_codes import (
    SaveCode,
    SaveTextCarrier,
    decode_save_text,
    extract_save_codes_bytes,
    extract_save_text_carriers,
)
from .save_gamecache import (
    GameCacheEvidence,
    extract_embedded_gamecaches,
    parse_gamecache,
)
from .pack_query_objects import object_category
from .script_sources import script_language
from .script_lexing import script_views
from .save_source_paths import iter_save_source_files, save_source_path_error
from .save_text_encoding import inspect_save_text, normalize_save_text_encoding

if TYPE_CHECKING:
    from .api import GameObject, MapData

# 唯一保留的是与 MPQ 解压层一致的分配炸弹护栏 (响亮报错, 不静默丢数据);
# 存档是用户自己的数据, 累计预算/文件条数/内嵌MPQ文本预算/证据串截断全部删除。
MAX_SAVE_FILE_SIZE: Final[int | None] = None
_QUOTED_STRING_RE: Final = re.compile(r"['\"]([^'\"\r\n]+)['\"]")
_QUOTED_BYTES_RE: Final = re.compile(rb"['\"]([^'\"\x00\r\n]+)['\"]")
_KEY_ENCODINGS: Final = ("utf-8", "gb18030")


class SaveFileKind(StrEnum):
    PRELOAD = "preload"
    JSON = "json"
    INI = "ini"
    TEXT = "text"
    MPQ = "mpq"
    W3Z = "w3z"
    GAMECACHE = "gamecache"
    BINARY = "binary"


@dataclass(frozen=True, slots=True)
class SaveObjectMatch:
    code: str
    name: str
    category: str
    state: str = "unclassified-code-candidate"
    source: str = ""
    offset: int | None = None


@dataclass(frozen=True, slots=True)
class RealSaveFile:
    relative_path: str
    kind: SaveFileKind
    size: int
    sha256: str
    matched_keys: tuple[str, ...]
    object_matches: tuple[SaveObjectMatch, ...]
    printable_strings: tuple[str, ...]
    diagnostic: str
    caches: tuple[GameCacheEvidence, ...] = ()
    codes: tuple[SaveCode, ...] = ()
    text_carriers: tuple[SaveTextCarrier, ...] = ()
    container: dict[str, object] | None = None
    members: tuple[RealSaveFile, ...] = ()
    encoding: str = ""
    source_identity: dict[str, int] | None = None
    complete: bool = True
    diagnostics: tuple[str, ...] = ()
    source_stable: bool = True
    raw_text: str | None = None
    unknown_ranges: tuple[dict[str, object], ...] = ()
    text_decoding: dict[str, object] | None = None

    def _record_dict(self) -> dict[str, object]:
        return {
            "source": self.relative_path,
            "kind": self.kind.value,
            "size": self.size,
            "sha256": self.sha256,
            "matched_keys": list(self.matched_keys),
            "object_matches": [
                {
                    "code": match.code,
                    "name": match.name,
                    "category": match.category,
                    "state": match.state,
                    "source": match.source,
                    "offset": match.offset,
                }
                for match in self.object_matches
            ],
            "printable_strings": list(self.printable_strings),
            "diagnostic": self.diagnostic,
            "encoding": self.encoding,
            "source_identity": self.source_identity,
            "complete": self.complete,
            "diagnostics": list(self.diagnostics),
            "source_stable": self.source_stable,
            "raw_text": self.raw_text,
            "unknown_ranges": list(self.unknown_ranges),
            "text_decoding": self.text_decoding,
            "caches": [cache.to_dict() for cache in self.caches],
            "codes": [code.to_dict() for code in self.codes],
            "text_carriers": [carrier.to_dict() for carrier in self.text_carriers],
            "container": self.container,
            "members": [],
        }

    def to_dict(self) -> dict[str, object]:
        """Serialize nested named archives without a Python/JSON depth ceiling."""
        result = self._record_dict()
        flattened: list[dict[str, object]] = []
        stack: list[tuple[RealSaveFile, int | None]] = [
            (member, None) for member in reversed(self.members)
        ]
        while stack:
            member, parent = stack.pop()
            index = len(flattened)
            row = member._record_dict()
            row["member_index"] = index
            row["parent_member_index"] = parent
            flattened.append(row)
            stack.extend((child, index) for child in reversed(member.members))
        result["members"] = flattened
        result["member_tree_encoding"] = "flat-parent-index"
        return result


@dataclass(frozen=True, slots=True)
class RealSaveReport:
    source: str
    files: tuple[RealSaveFile, ...]
    warnings: tuple[str, ...]
    map_path: str = ""
    map_name: str = ""
    complete: bool = True
    inventory_complete: bool = True
    expected_keys: tuple[str, ...] = ()
    map_associated: bool = False
    source_files: tuple[str, ...] = ()
    source_is_directory: bool = False
    unverified_files: tuple[RealSaveFile, ...] = ()
    text_encoding: str = "auto"

    def metadata_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "warnings": list(self.warnings),
            "map": {"path": self.map_path, "name": self.map_name},
            "complete": self.complete,
            "inventory_complete": self.inventory_complete,
            "expected_keys": list(self.expected_keys),
            "map_association": "performed" if self.map_associated else "not_performed",
            "map_association_note": (
                "已与所选地图的静态键和对象关联；匹配不证明运行时状态。"
                if self.map_associated
                else "未选择地图，未做地图关联；存档键和对象匹配为空。可选择地图后重新分析。"
            ),
            "source_files": list(self.source_files),
            "source_is_directory": self.source_is_directory,
            "text_encoding": self.text_encoding,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.metadata_dict(),
            "files": [record.to_dict() for record in self.files],
            "unverified_files": [record.to_dict() for record in self.unverified_files],
        }


def analyze_real_save_path(
    path: str | Path, md: MapData | None = None, *, text_encoding: str = "auto"
) -> RealSaveReport:
    """Read every physical source; preserve partial evidence and re-prove its SHA."""
    text_encoding = normalize_save_text_encoding(text_encoding)
    source = Path(path).absolute()
    candidates, warnings = _candidate_files(source)
    if not candidates and not warnings:
        warnings.append(
            "来源目录为空，没有可分析的普通文件；请选择包含存档的目录或文件。"
        )
    expected_keys = _expected_save_keys(md) if md is not None else ()
    records: list[RealSaveFile] = []
    identities: list[tuple[Path, tuple[int, ...]]] = []
    root = source if source.is_dir() else source.parent
    for candidate in candidates:
        relative = candidate.relative_to(root).as_posix()
        try:
            problem = save_source_path_error(candidate)
            if problem:
                warnings.append(problem)
                continue
            before = candidate.lstat()
            payload, _identity = read_bounded_regular_file(
                candidate,
                MAX_SAVE_FILE_SIZE,
            )
        except (BoundedFileError, OSError) as exc:
            warnings.append(f"跳过不安全或不可读文件：{relative} ({exc})")
            continue
        signature = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
            before.st_mode,
        )
        record = _analyze_file(
            candidate,
            relative,
            payload,
            expected_keys,
            md,
            text_encoding=text_encoding,
        )
        record = replace(
            record,
            source_identity=dict(
                zip(
                    ("device", "inode", "size", "mtime_ns", "ctime_ns", "mode"),
                    signature,
                    strict=True,
                )
            ),
        )
        records.append(record)
        identities.append((candidate, signature))
    verified: list[RealSaveFile] = []
    unverified: list[RealSaveFile] = []
    for record, (candidate, signature) in zip(records, identities, strict=True):
        problem = ""
        try:
            problem = save_source_path_error(candidate)
            if problem:
                raise ValueError(problem)
            after = candidate.lstat()
            if signature != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
                after.st_mode,
            ):
                raise ValueError("文件身份或元数据改变")
            digest, _identity = sha256_regular_file(candidate)
            if digest != record.sha256:
                raise ValueError("完整输入 SHA256 改变")
            problem = save_source_path_error(candidate)
            if problem:
                raise ValueError(problem)
        except (OSError, ValueError) as exc:
            problem = (
                f"来源在报告交付前改变或不可读：{record.relative_path} ({exc})；"
                "保留读取时的证据，不能视为当前来源的完整结果。"
            )
            warnings.append(problem)
            record = replace(
                record,
                complete=False,
                source_stable=False,
                diagnostics=(*record.diagnostics, problem),
            )
            unverified.append(record)
            continue
        verified.append(record)
    final_candidates, final_warnings = _candidate_files(source)
    warnings.extend(note for note in final_warnings if note not in warnings)
    if candidates != final_candidates:
        warnings.append("来源文件清单在分析期间改变；请刷新后重新读取完整目录。")
    inventory_complete = bool(verified) and not warnings
    return RealSaveReport(
        str(source),
        tuple(verified),
        tuple(warnings),
        md.path if md is not None else "",
        md.name if md is not None else "",
        complete=inventory_complete and all(record.complete for record in verified),
        inventory_complete=inventory_complete,
        expected_keys=expected_keys,
        map_associated=md is not None,
        source_files=tuple(
            candidate.relative_to(root).as_posix() for candidate in candidates
        ),
        source_is_directory=source == root,
        unverified_files=tuple(unverified),
        text_encoding=text_encoding,
    )


def format_real_save_report_tsv(report: RealSaveReport) -> str:
    """Render deterministic save evidence without modifying source files."""
    lines = [
        "文件\t类型\t大小\tSHA256\t匹配存档键\t匹配对象\t可读字符串\t诊断\t完整结构与来源JSON"
    ]
    for record in (*report.files, *report.unverified_files):
        objects = ",".join(f"{item.code}:{item.name}" for item in record.object_matches)
        lines.append(
            "\t".join(
                (
                    _tsv(record.relative_path),
                    record.kind.value,
                    str(record.size),
                    record.sha256,
                    _tsv(",".join(record.matched_keys)),
                    _tsv(objects),
                    _tsv(" | ".join(record.printable_strings)),
                    _tsv(record.diagnostic),
                    _tsv(
                        json.dumps(
                            record.to_dict(), ensure_ascii=False, allow_nan=False
                        )
                    ),
                )
            )
        )
    for warning in report.warnings:
        lines.append("\t".join(("[诊断]", "", "", "", "", "", "", _tsv(warning), "")))
    lines.append(
        "\t".join(
            (
                "[报告状态]",
                "complete" if report.complete else "incomplete",
                "",
                "",
                "",
                "",
                "",
                "已关联地图" if report.map_associated else "未做地图关联",
                _tsv(
                    json.dumps(
                        {key: value for key, value in report.metadata_dict().items()},
                        ensure_ascii=False,
                    )
                ),
            )
        )
    )
    return "\n".join(lines) + "\n"


def _candidate_files(source: Path) -> tuple[tuple[Path, ...], list[str]]:
    return iter_save_source_files(source)


def _analyze_file(
    path: Path,
    relative: str,
    payload: bytes,
    expected_keys: tuple[str, ...],
    md: MapData | None,
    ancestors: frozenset[str] = frozenset(),
    *,
    text_encoding: str = "auto",
) -> RealSaveFile:
    digest = hashlib.sha256(payload).hexdigest()
    if looks_like_save_container(payload):
        return _analyze_save_container(relative, payload, digest, expected_keys, md)
    if path.suffix.lower() == ".w3v":
        cache = parse_gamecache(payload, source=relative)
        if cache.complete or not _has_mpq_layout(payload):
            keys, matches, strings = _binary_evidence(payload, expected_keys, md)
            matches = (*_cache_object_matches((cache,), md), *matches)
            return RealSaveFile(
                relative,
                SaveFileKind.GAMECACHE,
                len(payload),
                digest,
                keys,
                tuple(matches),
                strings,
                "保存时 GameCache 字段；未推断当前英雄状态；"
                + "；".join(cache.diagnostics),
                caches=(cache,),
                complete=cache.complete,
                diagnostics=cache.diagnostics,
                unknown_ranges=_unknown_ranges(payload, cache.consumed, relative)
                if not cache.complete
                else (),
            )
    if _looks_like_mpq(payload):
        if digest in ancestors:
            return RealSaveFile(
                relative,
                SaveFileKind.MPQ,
                len(payload),
                digest,
                (),
                (),
                (),
                "nested archive repeats an ancestor identity; raw member hash retained",
                complete=False,
                diagnostics=("嵌套归档重复祖先身份，未猜测其记录。",),
            )
        members, diagnostic, diagnostics = _read_mpq_members(
            payload,
            relative,
            expected_keys,
            md,
            ancestors | {digest},
            text_encoding=text_encoding,
        )
        return RealSaveFile(
            relative,
            SaveFileKind.MPQ,
            len(payload),
            digest,
            tuple(
                dict.fromkeys(key for member in members for key in member.matched_keys)
            ),
            tuple(match for member in members for match in member.object_matches),
            tuple(
                dict.fromkeys(
                    value for member in members for value in member.printable_strings
                )
            ),
            diagnostic,
            members=members,
            complete=not diagnostics and all(member.complete for member in members),
            diagnostics=diagnostics,
        )
    decoded = inspect_save_text(payload, text_encoding)
    text = decoded.text
    kind = _classify_text(path, text)
    diagnostic = _diagnostic(kind)
    text_diagnostics: tuple[str, ...] = ()
    if (
        text is not None
        and path.suffix.lower() == ".json"
        and kind is not SaveFileKind.JSON
    ):
        text_diagnostics = (
            "来源扩展名为 .json，但 JSON 结构无效；保留完整原文，未猜测字段。",
        )
        diagnostic += "；" + text_diagnostics[0]
    if text is None:
        return RealSaveFile(
            relative,
            kind,
            len(payload),
            digest,
            (),
            (),
            (),
            diagnostic,
            complete=False,
            diagnostics=(diagnostic, *decoded.diagnostics),
            unknown_ranges=_unknown_ranges(payload, 0, relative),
            text_decoding=decoded.to_dict(payload),
        )
    keys, object_matches, strings = _text_evidence(text, expected_keys, md)
    encoding = decoded.encoding
    diagnostic += f"；文本编码 {encoding}（{'自动识别' if text_encoding == 'auto' else '明确指定'}），完整字节往返校验通过"
    carriers = tuple(
        extract_save_text_carriers(
            text,
            relative,
            lua=script_language(relative),
            encoding=encoding,
            bom_bytes=decoded.bom_bytes,
            include_plain_prefixes=True,
            byte_source=payload,
        )
    )
    codes = tuple(
        extract_save_codes_bytes(
            payload,
            relative,
            lua=script_language(relative),
            text_encoding=text_encoding,
        )
    )
    if any(not carrier.literal_complete for carrier in (*carriers, *codes)):
        text_diagnostics = (
            *text_diagnostics,
            "文本载体含未确认的字面量或转义；完整原文、原始字节与偏移已保留。",
        )
    return RealSaveFile(
        relative,
        kind,
        len(payload),
        digest,
        keys,
        object_matches,
        strings,
        diagnostic,
        codes=codes,
        text_carriers=carriers,
        encoding=encoding,
        raw_text=text,
        complete=not text_diagnostics,
        diagnostics=text_diagnostics,
        text_decoding=decoded.to_dict(payload),
    )


def _analyze_save_container(
    relative: str,
    payload: bytes,
    digest: str,
    expected_keys: tuple[str, ...],
    md: MapData | None,
) -> RealSaveFile:
    """Decode the recorded-save outer container without modifying the source."""
    inspected = inspect_save_container(payload)
    container = inspected.to_dict(payload)
    if not inspected.raw:
        return RealSaveFile(
            relative,
            SaveFileKind.W3Z,
            len(payload),
            digest,
            (),
            (),
            (),
            f"w3z 容器校验失败：{'; '.join(inspected.diagnostics)}；仅记录哈希和大小",
            container=container,
            complete=False,
            diagnostics=inspected.diagnostics,
            unknown_ranges=_unknown_ranges(payload, inspected.consumed, relative),
        )
    raw = inspected.raw
    raw_source = f"{relative}::decompressed"
    caches = (
        (parse_gamecache(raw, source=raw_source),)
        if relative.lower().endswith(".w3v")
        else extract_embedded_gamecaches(raw, source=raw_source)
    )
    text = _decode_text(raw)
    if text is not None:
        keys, object_matches, strings = _text_evidence(text, expected_keys, md)
    else:
        keys, object_matches, strings = _binary_evidence(raw, expected_keys, md)
    matches = (*_cache_object_matches(caches, md), *object_matches)
    diagnostic = (
        f"w3z 容器解压 {len(inspected.blocks)} 块共 {len(raw)} 字节；"
        "只读证据；未修改原文件"
    )
    if not inspected.complete:
        diagnostic += "；容器不完整，仅保留已校验块：" + "；".join(
            inspected.diagnostics
        )
    diagnostic += (
        "；" + "；".join(message for cache in caches for message in cache.diagnostics)
        if caches
        else ""
    )
    decoded = decode_save_text(raw)
    carriers = (
        ()
        if decoded is None
        else tuple(
            extract_save_text_carriers(
                decoded[0],
                raw_source,
                encoding=decoded[1],
                bom_bytes=decoded[2],
                include_plain_prefixes=True,
                byte_source=raw,
            )
        )
    )
    codes = tuple(extract_save_codes_bytes(raw, raw_source))
    text_complete = all(carrier.literal_complete for carrier in (*carriers, *codes))
    unknown_ranges = (
        _cache_unknown_ranges(raw, caches, raw_source) if text is None else ()
    )
    text_diagnostics = (
        ()
        if text_complete
        else ("文本载体含未确认的字面量或转义；完整原文、原始字节与偏移已保留。",)
    )
    return RealSaveFile(
        relative,
        SaveFileKind.W3Z,
        len(payload),
        digest,
        keys,
        tuple(matches),
        strings,
        diagnostic,
        caches=caches,
        container=container,
        codes=codes,
        text_carriers=carriers,
        encoding=decoded[1] if decoded is not None else "",
        raw_text=text,
        complete=inspected.complete
        and bool(caches or text is not None)
        and all(cache.complete for cache in caches)
        and text_complete
        and not unknown_ranges,
        diagnostics=(
            *inspected.diagnostics,
            *(message for cache in caches for message in cache.diagnostics),
            *text_diagnostics,
        ),
        unknown_ranges=unknown_ranges,
    )


def _text_evidence(
    text: str,
    expected_keys: tuple[str, ...],
    md: MapData | None,
) -> tuple[tuple[str, ...], tuple[SaveObjectMatch, ...], tuple[str, ...]]:
    keys = tuple(key for key in expected_keys if key and key in text)
    object_matches = tuple(
        SaveObjectMatch(code, obj.name, obj.category)
        for code, obj in _map_objects(md)
        if len(code) == 4 and code in text
    )
    strings = tuple(dict.fromkeys(_QUOTED_STRING_RE.findall(text)))
    return keys, object_matches, strings


def _binary_evidence(
    raw: bytes,
    expected_keys: tuple[str, ...],
    md: MapData | None,
) -> tuple[tuple[str, ...], tuple[SaveObjectMatch, ...], tuple[str, ...]]:
    keys = tuple(key for key in expected_keys if key and _key_in_raw(key, raw))
    object_matches = tuple(
        SaveObjectMatch(code, obj.name, obj.category)
        for code, obj in _map_objects(md)
        if _code_in_raw(code, raw)
    )
    return keys, object_matches, _quoted_raw_strings(raw)


def _map_objects(md: MapData | None) -> tuple[tuple[str, GameObject], ...]:
    """Retain same-code definitions in different categories and aliases."""
    objects: list[tuple[str, GameObject]] = []
    if md is None:
        return ()
    seen: set[tuple[str, str, str]] = set()
    for entries in (*md.objects.values(), list(md.obj_index.values())):
        for obj in entries:
            identity = (object_category(obj.category), obj.obj_id, obj.name)
            if identity not in seen:
                seen.add(identity)
                objects.append((obj.obj_id, obj))
    return tuple(
        sorted(objects, key=lambda entry: (entry[0], entry[1].category, entry[1].name))
    )


def _cache_object_matches(
    caches: tuple[GameCacheEvidence, ...], md: MapData | None
) -> tuple[SaveObjectMatch, ...]:
    definitions: dict[tuple[str, str], list[GameObject]] = {}
    for code, obj in _map_objects(md):
        category = object_category(obj.category)
        if category == "英雄":
            category = "单位"
        definitions.setdefault((category, code), []).append(obj)
    matches: list[SaveObjectMatch] = []
    for cache in caches:
        for record in cache.fields:
            if record.value_type != "unit":
                continue
            for field in record.fields:
                if field.value_type != "rawcode" or not isinstance(field.value, str):
                    continue
                if field.name == "unit_id":
                    category = "单位"
                elif field.name.startswith("inventory.") and field.name.endswith(
                    ".item"
                ):
                    category = "物品"
                elif field.name.startswith("skills.") and field.name.endswith(
                    ".ability"
                ):
                    category = "技能"
                else:
                    # The secondary ID is retained verbatim; its semantic
                    # category is not established by this serialization shape.
                    continue
                for obj in definitions.get((category, field.value), ()):
                    matches.append(
                        SaveObjectMatch(
                            field.value,
                            obj.name,
                            obj.category,
                            "saved-field"
                            if record.state == "confirmed"
                            else record.state,
                            cache.source,
                            field.offset,
                        )
                    )
    return tuple(matches)


def _key_in_raw(key: str, raw: bytes) -> bool:
    for encoding in _KEY_ENCODINGS:
        try:
            if key.encode(encoding) in raw:
                return True
        except UnicodeEncodeError:
            continue
    return False


def _code_in_raw(code: str, raw: bytes) -> bool:
    if len(code) != 4:
        return False
    try:
        return code.encode("latin-1") in raw
    except UnicodeEncodeError:
        return False


def _quoted_raw_strings(raw: bytes) -> tuple[str, ...]:
    strings: list[str] = []
    seen: set[str] = set()
    for match in _QUOTED_BYTES_RE.finditer(raw):
        for encoding in _KEY_ENCODINGS:
            try:
                value = match.group(1).decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            value = "未识别编码的原字节:0x" + match.group(1).hex()
        if value in seen:
            continue
        seen.add(value)
        strings.append(value)
    return tuple(strings)


def _expected_save_keys(md: MapData) -> tuple[str, ...]:
    report = build_save_report(md)
    return tuple(
        dict.fromkeys(
            (*report.keys, *report.sections, *report.local_files, *report.sync_prefixes)
        )
    )


def _decode_text(payload: bytes) -> str | None:
    decoded = decode_save_text(payload)
    return None if decoded is None else decoded[0]


def _classify_text(path: Path, text: str | None) -> SaveFileKind:
    if text is None:
        return SaveFileKind.BINARY
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError:
            return SaveFileKind.TEXT
        return SaveFileKind.JSON
    if suffix in {".ini", ".cfg"}:
        return SaveFileKind.INI
    if suffix == ".pld":
        return SaveFileKind.PRELOAD
    syntax = script_views(text, lua=script_language(path.as_posix())).syntax
    if re.search(
        r"\bfunction\s+PreloadFiles(?:\s+takes\b|\s*\()|(?<![\w.:])call\s+(?:_G\s*\.\s*)?Preload\s*\(",
        syntax,
    ):
        return SaveFileKind.PRELOAD
    return SaveFileKind.TEXT


def _looks_like_mpq(payload: bytes) -> bool:
    # A leading wrapper remains a diagnosable archive candidate even if its
    # header is damaged. Embedded signatures need a physically valid layout.
    return payload.startswith((b"MPQ\x1a", b"MPQ\x1b")) or _has_mpq_layout(payload)


def _has_mpq_layout(payload: bytes) -> bool:
    try:
        locate_mpq_layout(payload)
    except ValueError:
        return False
    return True


def _named_mpq_member(name: str, payload: bytes) -> bool:
    if Path(name).suffix.lower() == ".w3v":
        return (
            _has_mpq_layout(payload)
            and not parse_gamecache(payload, source=name).complete
        )
    return _looks_like_mpq(payload)


def _unknown_ranges(
    raw: bytes, start: int, source: str, *, end: int | None = None
) -> tuple[dict[str, object], ...]:
    stop = len(raw) if end is None else end
    if start >= stop:
        return ()
    return (
        {
            "source": source,
            "offset": start,
            "end": stop,
            "state": "unknown",
            "sha256": hashlib.sha256(raw[start:stop]).hexdigest(),
            "raw_hex": raw[start:stop].hex(),
            "diagnostic": "此字节范围的私有记录格式未验证；未推断字段含义。",
        },
    )


def _cache_unknown_ranges(
    raw: bytes, caches: tuple[GameCacheEvidence, ...], source: str
) -> tuple[dict[str, object], ...]:
    """Account for every decoded byte; opaque frame data stays explicitly unknown."""
    known: list[tuple[int, int]] = []
    for cache in caches:
        if cache.complete:
            known.append((cache.offset, cache.offset + cache.consumed))
        else:
            known.extend(
                (field.offset, field.end)
                for field in cache.structure
                if field.state == "confirmed"
            )
            known.extend(
                (record.record_offset, record.end)
                for record in cache.fields
                if record.state == "confirmed"
            )
        known.extend(
            (field.offset, field.end)
            for field in cache.frame
            if field.name != "frame.opaque" and field.state == "confirmed"
        )
    cursor = 0
    unknown: list[dict[str, object]] = []
    for start, stop in sorted(known):
        start, stop = max(0, start), min(len(raw), stop)
        if start > cursor:
            unknown.extend(_unknown_ranges(raw, cursor, source, end=start))
        cursor = max(cursor, stop)
    unknown.extend(_unknown_ranges(raw, cursor, source))
    return tuple(unknown)


def _read_mpq_members(
    snapshot: bytes,
    source: str,
    expected_keys: tuple[str, ...],
    md: MapData | None,
    ancestors: frozenset[str],
    *,
    text_encoding: str = "auto",
) -> tuple[tuple[RealSaveFile, ...], str, tuple[str, ...]]:
    """Traverse named nested archives with an explicit stack and stable snapshots."""
    # Index identities preserve duplicate member names instead of overwriting them.
    stack: list[tuple[int, str, bytes, frozenset[str], bool]] = [
        (0, source, snapshot, ancestors - {hashlib.sha256(snapshot).hexdigest()}, False)
    ]
    records: dict[int, RealSaveFile] = {}
    children: dict[int, tuple[int, ...]] = {}
    notes: dict[int, str] = {}
    issues: dict[int, tuple[str, ...]] = {}
    next_index = 1
    while stack:
        index, name, payload, parents, visited = stack.pop()
        digest = hashlib.sha256(payload).hexdigest()
        if visited:
            members = tuple(records[child] for child in children[index])
            records[index] = RealSaveFile(
                name,
                SaveFileKind.MPQ,
                len(payload),
                digest,
                tuple(
                    dict.fromkeys(
                        key for member in members for key in member.matched_keys
                    )
                ),
                tuple(match for member in members for match in member.object_matches),
                tuple(
                    dict.fromkeys(
                        value
                        for member in members
                        for value in member.printable_strings
                    )
                ),
                notes[index],
                members=members,
                complete=not issues[index]
                and all(member.complete for member in members),
                diagnostics=issues[index],
            )
            continue
        if digest in parents:
            records[index] = RealSaveFile(
                name,
                SaveFileKind.MPQ,
                len(payload),
                digest,
                (),
                (),
                (),
                "nested archive repeats an ancestor identity; no guessed recursion",
                complete=False,
                diagnostics=("嵌套归档重复祖先身份，未猜测其记录。",),
            )
            continue
        snapshots, note, diagnostics = _mpq_snapshots(payload)
        notes[index] = note
        issues[index] = diagnostics
        child_ids: list[int] = []
        stack.append((index, name, payload, parents, True))
        for member_name, member_payload in snapshots:
            child = next_index
            next_index += 1
            child_ids.append(child)
            child_name = f"{name}::{member_name}"
            if _named_mpq_member(
                member_name, member_payload
            ) and not looks_like_save_container(member_payload):
                stack.append(
                    (child, child_name, member_payload, parents | {digest}, False)
                )
            else:
                records[child] = _analyze_file(
                    Path(member_name),
                    child_name,
                    member_payload,
                    expected_keys,
                    md,
                    parents | {digest},
                    text_encoding=text_encoding,
                )
        children[index] = tuple(child_ids)
    return records[0].members, records[0].diagnostic, records[0].diagnostics


def _mpq_snapshots(
    snapshot: bytes,
) -> tuple[tuple[tuple[str, bytes], ...], str, tuple[str, ...]]:
    descriptor, temporary_path = tempfile.mkstemp(
        prefix="gamexray-save-", suffix=".mpq"
    )
    members: list[tuple[str, bytes]] = []
    diagnostics: list[str] = []
    try:
        with os.fdopen(descriptor, "wb") as handle:
            _ = handle.write(snapshot)
        with MPQArchive(temporary_path) as archive:
            named_blocks: set[int] = set()
            for name in archive.list_files():
                block_index = archive.block_index_of(name)
                if block_index is None:
                    diagnostics.append(f"{name}: named member has no block identity")
                    continue
                named_blocks.add(block_index)
                try:
                    members.append((name, archive.read_file(name)))
                except (KeyError, OSError, ValueError) as exc:
                    diagnostics.append(f"{name}: {type(exc).__name__}: {exc}")
            if callable(getattr(archive, "iter_blocks", None)):
                diagnostics.extend(
                    f"未具名 MPQ 块 {index}，声明大小 {block.file_size}；内部记录格式未验证，原始归档 SHA256 保留。"
                    for index, block in archive.iter_blocks()
                    if index not in named_blocks
                )
    except (OSError, ValueError) as exc:
        diagnostics.append(f"MPQ 只读打开失败，未解密：{exc}")
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary_path)
    note = f"MPQ 可读命名成员 {len(members)} 个；未执行平台 API 或解密"
    if not members and not diagnostics:
        diagnostics.append("MPQ 没有可读取的命名成员，未证明内部记录覆盖。")
    return tuple(members), "；".join((note, *diagnostics)), tuple(diagnostics)


def _diagnostic(kind: SaveFileKind) -> str:
    if kind is SaveFileKind.BINARY:
        return "不透明二进制，仅记录哈希和大小；未解密"
    return "只读静态证据；未执行平台 API，未修改原文件"
