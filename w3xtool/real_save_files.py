"""Bounded, read-only evidence extraction from real local save files."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final

from .bounded_file import BoundedFileError, read_bounded_regular_file
from .mpq import MPQArchive
from .presentation_safety import tsv_cell as _tsv
from .save_analysis import build_save_report
from .save_container import (
    SaveContainerError,
    looks_like_save_container,
    unpack_save_container,
)

if TYPE_CHECKING:
    from .api import MapData

MAX_SAVE_FILE_SIZE: Final = 40 * 1024 * 1024
MAX_SAVE_TOTAL_SIZE: Final = 512 * 1024 * 1024
MAX_SAVE_FILES: Final = 10_000
MAX_MPQ_TEXT_FILES: Final = 500
MAX_MPQ_TEXT_TOTAL_SIZE: Final = 8 * 1024 * 1024
MAX_EVIDENCE_STRINGS: Final = 200
_QUOTED_STRING_RE: Final = re.compile(r"['\"]([^'\"\r\n]{2,512})['\"]")
_QUOTED_BYTES_RE: Final = re.compile(rb"['\"]([^'\"\x00\r\n]{2,512})['\"]")
_KEY_ENCODINGS: Final = ("utf-8", "gb18030")


class SaveFileKind(StrEnum):
    PRELOAD = "preload"
    JSON = "json"
    INI = "ini"
    TEXT = "text"
    MPQ = "mpq"
    W3Z = "w3z"
    BINARY = "binary"


@dataclass(frozen=True, slots=True)
class SaveObjectMatch:
    code: str
    name: str
    category: str


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


@dataclass(frozen=True, slots=True)
class RealSaveReport:
    source: str
    files: tuple[RealSaveFile, ...]
    warnings: tuple[str, ...]


def analyze_real_save_path(path: str | Path, md: MapData) -> RealSaveReport:
    """Inventory a save file/directory and correlate static evidence with one map."""
    source = Path(path)
    candidates, warnings = _candidate_files(source)
    expected_keys = _expected_save_keys(md)
    records: list[RealSaveFile] = []
    total_size = 0
    root = source if source.is_dir() else source.parent
    for candidate in candidates:
        remaining = MAX_SAVE_TOTAL_SIZE - total_size
        if remaining < 1:
            warnings.append(f"跳过超限文件：{candidate.name}")
            break
        relative = candidate.relative_to(root).as_posix()
        try:
            payload, _identity = read_bounded_regular_file(
                candidate,
                min(MAX_SAVE_FILE_SIZE, remaining),
            )
        except BoundedFileError as exc:
            warnings.append(f"跳过不安全或超限文件：{relative} ({exc.reason})")
            continue
        total_size += len(payload)
        records.append(_analyze_file(candidate, relative, payload, expected_keys, md))
    return RealSaveReport(str(source), tuple(records), tuple(warnings))


def format_real_save_report_tsv(report: RealSaveReport) -> str:
    """Render deterministic save evidence without modifying source files."""
    lines = ["文件\t类型\t大小\tSHA256\t匹配存档键\t匹配对象\t可读字符串\t诊断"]
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
                )
            )
        )
    return "\n".join(lines) + "\n"


def _candidate_files(source: Path) -> tuple[tuple[Path, ...], list[str]]:
    if source.is_file() and not source.is_symlink():
        return (source,), []
    if not source.is_dir():
        return (), ([]) if source.exists() else ([f"路径不存在：{source}"])
    files: list[Path] = []
    warnings: list[str] = []
    for dirpath, dirs, names in os.walk(source, followlinks=False):
        dirs[:] = sorted(name for name in dirs if not Path(dirpath, name).is_symlink())
        for name in sorted(names):
            path = Path(dirpath, name)
            if path.is_symlink() or not path.is_file():
                warnings.append(f"跳过符号链接：{path.relative_to(source).as_posix()}")
                continue
            files.append(path)
            if len(files) >= MAX_SAVE_FILES:
                warnings.append(f"文件数量达到上限：{MAX_SAVE_FILES}")
                return tuple(files), warnings
    return tuple(files), warnings


def _analyze_file(
    path: Path,
    relative: str,
    payload: bytes,
    expected_keys: tuple[str, ...],
    md: MapData,
) -> RealSaveFile:
    digest = hashlib.sha256(payload).hexdigest()
    if looks_like_save_container(payload):
        return _analyze_save_container(relative, payload, digest, expected_keys, md)
    if _looks_like_mpq(payload):
        text, diagnostic = _read_mpq_text(payload)
        kind = SaveFileKind.MPQ
    else:
        text = _decode_text(payload)
        kind = _classify_text(path, text)
        diagnostic = _diagnostic(kind)
    if text is None:
        return RealSaveFile(
            relative, kind, len(payload), digest, (), (), (), diagnostic
        )
    keys, object_matches, strings = _text_evidence(text, expected_keys, md)
    return RealSaveFile(
        relative,
        kind,
        len(payload),
        digest,
        keys,
        object_matches,
        strings,
        diagnostic,
    )


def _analyze_save_container(
    relative: str,
    payload: bytes,
    digest: str,
    expected_keys: tuple[str, ...],
    md: MapData,
) -> RealSaveFile:
    """Decode the recorded-save outer container without modifying the source."""
    try:
        unpacked = unpack_save_container(payload)
    except SaveContainerError as exc:
        return RealSaveFile(
            relative,
            SaveFileKind.W3Z,
            len(payload),
            digest,
            (),
            (),
            (),
            f"w3z 容器校验失败：{exc.reason}；仅记录哈希和大小",
        )
    raw = unpacked.raw
    text = _decode_text(raw)
    if text is not None:
        keys, object_matches, strings = _text_evidence(text, expected_keys, md)
    else:
        keys, object_matches, strings = _binary_evidence(raw, expected_keys, md)
    diagnostic = (
        f"w3z 容器解压 {len(unpacked.blocks)} 块共 {len(raw)} 字节；"
        "只读证据；未修改原文件"
    )
    return RealSaveFile(
        relative,
        SaveFileKind.W3Z,
        len(payload),
        digest,
        keys,
        object_matches,
        strings,
        diagnostic,
    )


def _text_evidence(
    text: str,
    expected_keys: tuple[str, ...],
    md: MapData,
) -> tuple[tuple[str, ...], tuple[SaveObjectMatch, ...], tuple[str, ...]]:
    keys = tuple(key for key in expected_keys if key and key in text)
    object_matches = tuple(
        SaveObjectMatch(code, obj.name, obj.category)
        for code, obj in sorted(md.obj_index.items())
        if len(code) == 4 and code in text
    )
    strings = tuple(dict.fromkeys(_QUOTED_STRING_RE.findall(text)))[
        :MAX_EVIDENCE_STRINGS
    ]
    return keys, object_matches, strings


def _binary_evidence(
    raw: bytes,
    expected_keys: tuple[str, ...],
    md: MapData,
) -> tuple[tuple[str, ...], tuple[SaveObjectMatch, ...], tuple[str, ...]]:
    keys = tuple(key for key in expected_keys if key and _key_in_raw(key, raw))
    object_matches = tuple(
        SaveObjectMatch(code, obj.name, obj.category)
        for code, obj in sorted(md.obj_index.items())
        if _code_in_raw(code, raw)
    )
    return keys, object_matches, _quoted_raw_strings(raw)


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
        return code.encode("ascii") in raw
    except UnicodeEncodeError:
        return False


def _quoted_raw_strings(raw: bytes) -> tuple[str, ...]:
    strings: list[str] = []
    seen: set[str] = set()
    for match in _QUOTED_BYTES_RE.finditer(raw):
        value = match.group(1).decode("utf-8", errors="replace")
        if value in seen:
            continue
        seen.add(value)
        strings.append(value)
        if len(strings) >= MAX_EVIDENCE_STRINGS:
            break
    return tuple(strings)


def _expected_save_keys(md: MapData) -> tuple[str, ...]:
    report = build_save_report(md)
    return tuple(
        dict.fromkeys(
            (*report.keys, *report.sections, *report.local_files, *report.sync_prefixes)
        )
    )


def _decode_text(payload: bytes) -> str | None:
    if not payload:
        return ""
    controls = sum(byte == 0 or byte < 9 or 13 < byte < 32 for byte in payload)
    if controls > max(2, len(payload) // 50):
        return None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


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
    return payload[:4096].find(b"MPQ\x1a") >= 0


def _read_mpq_text(snapshot: bytes) -> tuple[str | None, str]:
    descriptor, temporary_path = tempfile.mkstemp(prefix="w3xray-save-", suffix=".mpq")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            _ = handle.write(snapshot)
        return _read_mpq_text_path(Path(temporary_path))
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary_path)


def _read_mpq_text_path(path: Path) -> tuple[str | None, str]:
    chunks: list[str] = []
    readable = 0
    remaining = MAX_MPQ_TEXT_TOTAL_SIZE
    try:
        with MPQArchive(str(path)) as archive:
            for name in archive.list_files()[:MAX_MPQ_TEXT_FILES]:
                block_index = archive.block_index_of(name)
                if block_index is None:
                    continue
                declared_size = archive.block_table[block_index].file_size
                if declared_size > min(MAX_SAVE_FILE_SIZE, remaining):
                    continue
                try:
                    payload = archive.read_file(name)
                except KeyError, OSError, ValueError:
                    continue
                if len(payload) > remaining:
                    continue
                remaining -= len(payload)
                text = _decode_text(payload)
                if text is not None:
                    chunks.append(f"\n[{name}]\n{text}")
                    readable += 1
    except (OSError, ValueError) as exc:
        return None, f"MPQ 只读打开失败，未解密：{exc}"
    return "".join(chunks), f"MPQ 可读命名文本 {readable} 个；未执行平台 API 或解密"


def _diagnostic(kind: SaveFileKind) -> str:
    if kind is SaveFileKind.BINARY:
        return "不透明二进制，仅记录哈希和大小；未解密"
    return "只读静态证据；未执行平台 API，未修改原文件"
