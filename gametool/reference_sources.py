"""Fresh, lossless pack snapshots adapted to the shared object schema engine."""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
import hashlib
import io
import os
from pathlib import Path

from .csv_fields import full_csv_fields
from .pack_query_objects import ObjectTable, object_field_table, object_table
from .reference_models import ReferenceSource


def _identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


@dataclass(frozen=True, slots=True)
class _Snapshot:
    path: Path
    identity: tuple[int, int, int, int] | None
    payload: bytes


class PackReferenceSources:
    """One loader call owns its snapshots; no persisted or process-wide cache."""

    def __init__(self) -> None:
        self.snapshots: dict[Path, _Snapshot] = {}
        self.sources: dict[str, ReferenceSource] = {}
        self.diagnostics: list[str] = []
        self.tables: dict[Path, ObjectTable] = {}

    def _clean(self, text: str) -> str:
        # Reference evidence keeps complete cells, including color codes/BOMs.
        return text

    def _named_table(self, pack: Path, relative: str, table: str = "") -> ObjectTable:
        path = pack / relative
        if path in self.tables:
            return self.tables[path]
        payload, error = self._read(path, pack)
        rows: list[tuple[str, ...]] = []
        problems = [error] if error else []
        reader = None
        confirmed_line = 0
        if payload is not None:
            try:
                text = payload.decode("utf-8-sig")
                with full_csv_fields():
                    reader = csv.reader(
                        io.StringIO(text, newline=""), delimiter="\t", strict=True
                    )
                    for row in reader:
                        rows.append(tuple(row))
                        confirmed_line = getattr(reader, "line_num", confirmed_line)
            except UnicodeError as exc:
                problems.append(f"UTF-8 解码失败: {exc}")
            except csv.Error as exc:
                failure_line = getattr(reader, "line_num", None)
                location = (
                    f"，物理行 {confirmed_line + 1}..{failure_line}"
                    if isinstance(failure_line, int)
                    else ""
                )
                problems.append(
                    f"TSV 解析失败，保留此前 {len(rows)} 条逻辑记录；"
                    f"失败逻辑记录序号 {len(rows) + 1}{location}: {exc}"
                )
        parsed = (
            object_table(table, tuple(rows))
            if table
            else object_field_table(tuple(rows))
        )
        result = replace(
            parsed,
            diagnostics=(*parsed.diagnostics, *problems),
            readable=payload is not None and not problems,
        )
        self.tables[path] = result
        self.diagnostics.extend(f"{path}: {note}" for note in result.diagnostics)
        return result

    def _read(self, path: Path, pack: Path) -> tuple[bytes | None, str]:
        try:
            relative = path.relative_to(pack)
            current = pack
            for part in relative.parts:
                current /= part
                if current.is_symlink():
                    return (
                        None,
                        "来源含符号链接，未越过资料包路径边界；请使用实际目录。",
                    )
            with path.open("rb") as handle:
                before = os.fstat(handle.fileno())
                payload = handle.read()
                after = os.fstat(handle.fileno())
            if _identity(before) != _identity(after) or _identity(after) != _identity(
                path.stat()
            ):
                return None, "来源在读取时变化，未将不稳定内容作为完整目录。"
            self.snapshots[path] = _Snapshot(path, _identity(after), payload)
            source_id = str(path)
            self.sources[source_id] = ReferenceSource(
                source_id,
                str(path),
                hashlib.sha256(payload).hexdigest(),
                "调用方提供的 GameXRay 知识包；原始字节 SHA-256，未推断游戏 build。",
                state="map-evidence",
            )
            return payload, ""
        except FileNotFoundError:
            self.snapshots[path] = _Snapshot(path, None, b"")
            return None, "未记录此表；可用已确认字段继续检索，或重新完整导出知识包。"
        except OSError as exc:
            return None, f"读取失败: {exc}；可检查目录或重新导出知识包。"

    def verify(self) -> None:
        """Detect replacement and content edits even when size/mtime are retained."""
        for snapshot in self.snapshots.values():
            try:
                if snapshot.identity is None:
                    unchanged = not snapshot.path.exists()
                else:
                    with snapshot.path.open("rb") as handle:
                        before = os.fstat(handle.fileno())
                        payload = handle.read()
                        after = os.fstat(handle.fileno())
                    unchanged = (
                        snapshot.identity
                        == _identity(before)
                        == _identity(after)
                        == _identity(snapshot.path.stat())
                        and payload == snapshot.payload
                        and not snapshot.path.is_symlink()
                    )
                if unchanged:
                    continue
            except OSError:
                pass
            self.diagnostics.append(
                f"{snapshot.path}: 来源在目录交付前变化；以上保留已读取证据，完整性未确认，请刷新。"
            )


def reference_pack_scopes(pack: Path) -> tuple[tuple[Path, ...], tuple[str, ...]]:
    """Include every immediate campaign child, including diagnostic-only packs."""
    if not pack.is_dir() or pack.is_symlink():
        return (), (f"{pack}: 资料包目录不存在或为符号链接；请选择实际知识包目录。",)
    children = pack / "子地图"
    if not children.exists():
        return (pack,), ()
    if children.is_symlink():
        return (pack,), (f"{children}: 未遍历符号链接；请使用实际子地图目录。",)
    try:
        scopes = [pack]
        diagnostics: list[str] = []
        for child in sorted(children.iterdir()):
            if child.is_symlink():
                diagnostics.append(f"{child}: 未遍历符号链接子包。")
            elif child.is_dir():
                scopes.append(child)
        return tuple(scopes), tuple(diagnostics)
    except OSError as exc:
        return (pack,), (f"{children}: 子包枚举失败: {exc}",)
