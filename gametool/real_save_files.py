"""Bounded, read-only evidence extraction from real local save files."""

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

from .bounded_file import BoundedFileError, read_bounded_regular_file
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
from .save_source_paths import iter_save_source_files, save_source_path_error

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

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "files": [record.to_dict() for record in self.files],
            "warnings": list(self.warnings),
            "map": {"path": self.map_path, "name": self.map_name},
        }


def analyze_real_save_path(path: str | Path, md: MapData) -> RealSaveReport:
    """Inventory a save file/directory and correlate static evidence with one map."""
    source = Path(path)
    candidates, warnings = _candidate_files(source)
    expected_keys = _expected_save_keys(md)
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
        record = _analyze_file(candidate, relative, payload, expected_keys, md)
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
    stable: list[RealSaveFile] = []
    for record, (candidate, signature) in zip(records, identities, strict=True):
        try:
            after = candidate.lstat()
        except OSError as exc:
            warnings.append(f"来源在报告交付前不可读：{record.relative_path} ({exc})")
            continue
        if save_source_path_error(candidate) or signature != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_mode,
        ):
            warnings.append(
                f"来源在报告交付前改变：{record.relative_path}；未交付旧读取结果"
            )
            continue
        stable.append(record)
    return RealSaveReport(str(source), tuple(stable), tuple(warnings), md.path, md.name)


def format_real_save_report_tsv(report: RealSaveReport) -> str:
    """Render deterministic save evidence without modifying source files."""
    lines = [
        "文件\t类型\t大小\tSHA256\t匹配存档键\t匹配对象\t可读字符串\t诊断\t完整结构与来源JSON"
    ]
    for record in report.files:
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
    return "\n".join(lines) + "\n"


def _candidate_files(source: Path) -> tuple[tuple[Path, ...], list[str]]:
    return iter_save_source_files(source)


def _analyze_file(
    path: Path,
    relative: str,
    payload: bytes,
    expected_keys: tuple[str, ...],
    md: MapData,
    ancestors: frozenset[str] = frozenset(),
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
            )
        members, diagnostic = _read_mpq_members(
            payload, relative, expected_keys, md, ancestors | {digest}
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
        )
    text = _decode_text(payload)
    kind = _classify_text(path, text)
    diagnostic = _diagnostic(kind)
    if text is None:
        return RealSaveFile(
            relative, kind, len(payload), digest, (), (), (), diagnostic
        )
    keys, object_matches, strings = _text_evidence(text, expected_keys, md)
    decoded = decode_save_text(payload)
    encoding = decoded[1] if decoded is not None else ""
    carriers = (
        ()
        if decoded is None
        else tuple(
            extract_save_text_carriers(
                decoded[0],
                relative,
                lua=script_language(relative),
                encoding=decoded[1],
                bom_bytes=decoded[2],
                include_plain_prefixes=True,
                byte_source=payload,
            )
        )
    )
    codes = tuple(
        extract_save_codes_bytes(payload, relative, lua=script_language(relative))
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
    )


def _analyze_save_container(
    relative: str,
    payload: bytes,
    digest: str,
    expected_keys: tuple[str, ...],
    md: MapData,
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
        codes=tuple(extract_save_codes_bytes(raw, raw_source)),
        text_carriers=carriers,
    )


def _text_evidence(
    text: str,
    expected_keys: tuple[str, ...],
    md: MapData,
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
    md: MapData,
) -> tuple[tuple[str, ...], tuple[SaveObjectMatch, ...], tuple[str, ...]]:
    keys = tuple(key for key in expected_keys if key and _key_in_raw(key, raw))
    object_matches = tuple(
        SaveObjectMatch(code, obj.name, obj.category)
        for code, obj in _map_objects(md)
        if _code_in_raw(code, raw)
    )
    return keys, object_matches, _quoted_raw_strings(raw)


def _map_objects(md: MapData) -> tuple[tuple[str, GameObject], ...]:
    """Retain same-code definitions in different categories and aliases."""
    objects: list[tuple[str, GameObject]] = []
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
    caches: tuple[GameCacheEvidence, ...], md: MapData
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
    lowered = text.lower()
    if "preloadfiles" in lowered or "call preload(" in lowered:
        return SaveFileKind.PRELOAD
    if path.suffix.lower() == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError:
            return SaveFileKind.TEXT
        return SaveFileKind.JSON
    if path.suffix.lower() in {".ini", ".cfg"}:
        return SaveFileKind.INI
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


def _read_mpq_members(
    snapshot: bytes,
    source: str,
    expected_keys: tuple[str, ...],
    md: MapData,
    ancestors: frozenset[str],
) -> tuple[tuple[RealSaveFile, ...], str]:
    """Traverse named nested archives with an explicit stack and stable snapshots."""
    # Index identities preserve duplicate member names instead of overwriting them.
    stack: list[tuple[int, str, bytes, frozenset[str], bool]] = [
        (0, source, snapshot, ancestors - {hashlib.sha256(snapshot).hexdigest()}, False)
    ]
    records: dict[int, RealSaveFile] = {}
    children: dict[int, tuple[int, ...]] = {}
    notes: dict[int, str] = {}
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
            )
            continue
        snapshots, note = _mpq_snapshots(payload)
        notes[index] = note
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
                )
        children[index] = tuple(child_ids)
    return records[0].members, records[0].diagnostic


def _mpq_snapshots(snapshot: bytes) -> tuple[tuple[tuple[str, bytes], ...], str]:
    descriptor, temporary_path = tempfile.mkstemp(
        prefix="gamexray-save-", suffix=".mpq"
    )
    members: list[tuple[str, bytes]] = []
    diagnostics: list[str] = []
    try:
        with os.fdopen(descriptor, "wb") as handle:
            _ = handle.write(snapshot)
        with MPQArchive(temporary_path) as archive:
            for name in archive.list_files():
                if archive.block_index_of(name) is None:
                    diagnostics.append(f"{name}: named member has no block identity")
                    continue
                try:
                    members.append((name, archive.read_file(name)))
                except (KeyError, OSError, ValueError) as exc:
                    diagnostics.append(f"{name}: {type(exc).__name__}: {exc}")
    except (OSError, ValueError) as exc:
        diagnostics.append(f"MPQ 只读打开失败，未解密：{exc}")
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary_path)
    note = f"MPQ 可读命名成员 {len(members)} 个；未执行平台 API 或解密"
    return tuple(members), "；".join((note, *diagnostics))


def _diagnostic(kind: SaveFileKind) -> str:
    if kind is SaveFileKind.BINARY:
        return "不透明二进制，仅记录哈希和大小；未解密"
    return "只读静态证据；未执行平台 API，未修改原文件"
