"""Read-only archive scopes, complete member proofs and map-table snapshots."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import os
from pathlib import Path
import struct

from .bounded_file import sha256_regular_file
from .archive_source import PathArchiveSource
from .extraction_ledger import BlockSource, BlockState
from .map_data import MapData
from .map_loader import load_map
from .map_reference_identity import MapObjectIdentity, map_object_identities
from .map_reference_tables import map_object_tables, virtual_table_key
from .mpq_storage import open_regular_binary
from .pack_query_objects import OBJECT_TABLES, ObjectTable
from .reference_models import ReferenceMapScope, ReferenceSource

type CancelCheck = Callable[[], bool]
type ProgressCallback = Callable[[str], None]


class MapReferenceCancelled(ValueError):
    """The caller withdrew this scan; no partially scanned catalog is delivered."""


def check_cancelled(cancelled: CancelCheck | None) -> None:
    if cancelled is not None and cancelled():
        raise MapReferenceCancelled("地图目录加载已取消；未交付部分结果。")


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_mode,
    )


@dataclass(frozen=True, slots=True)
class _MapProof:
    digest: str
    identity: tuple[int, int, int, int, int, int]
    named_identity: tuple[int, int, int, int, int, int]


def _prove(path: Path) -> _MapProof:
    before = _identity(path.lstat())
    handle, _size = open_regular_binary(str(path))
    with handle:
        opened = _identity(os.fstat(handle.fileno()))
        digest, observed = sha256_regular_file(path)
        closed = _identity(os.fstat(handle.fileno()))
        after = _identity(path.lstat())
    # Windows stat/fstat can expose distinct ctime values. Compare each API's
    # complete metadata within its own interval; bind the common file identity,
    # size, mtime and mode across the pathname and held descriptor boundaries.
    if (
        before != after
        or opened != closed
        or (observed.device, observed.inode, observed.size) != opened[:3]
        or (*after[:4], after[5]) != (*opened[:4], opened[5])
    ):
        raise OSError(f"{path}: 来源在完整 SHA-256 读取期间变化。")
    return _MapProof(digest, opened, after)


def _notes(md: MapData, scope: str) -> tuple[str, ...]:
    return tuple(
        f"{scope}!{note.source}: [{note.component}/{note.stage}/{note.severity.value}] "
        f"{note.message} (recoverable={note.recoverable}, exception={note.exception_type or 'none'})"
        for note in md.diagnostics
    )


class MapReferenceSources:
    """Each instance owns fresh immutable tables; MapData resources close on return."""

    def __init__(
        self,
        path: str | Path,
        *,
        cancelled: CancelCheck | None = None,
        progress: ProgressCallback | None = None,
    ) -> None:
        self.path = Path(path).absolute()
        if self.path.suffix.casefold() not in {".w3x", ".w3m", ".w3n"}:
            raise ValueError("--map 需要 .w3x/.w3m/.w3n 地图或战役文件。")
        self.cancelled = cancelled
        self.progress = progress
        self.sources: dict[str, ReferenceSource] = {}
        self.diagnostics: list[str] = []
        self.tables: dict[tuple[Path, str], ObjectTable] = {}
        self.members: dict[str, dict[str, str]] = {}
        self.identities: dict[str, dict[tuple[str, str], MapObjectIdentity]] = {}
        self.scopes: list[ReferenceMapScope] = []
        self.proof: _MapProof | None = None
        self.binding_diagnostics: tuple[str, ...] = ()
        self._load()

    def _announce(self, message: str) -> None:
        check_cancelled(self.cancelled)
        if self.progress is not None:
            self.progress(message)
        check_cancelled(self.cancelled)

    def _load(self) -> None:
        scope = str(self.path)
        self._announce(f"读取地图来源指纹: {scope}")
        md: MapData | None = None
        try:
            self.proof = _prove(self.path)
            self.sources[scope] = ReferenceSource(
                scope,
                scope,
                self.proof.digest,
                "只读地图归档；完整原始文件 SHA-256，加载前后验证文件身份与内容。游戏 build 未记录。",
                state="map-archive",
                source_file_sha256=self.proof.digest,
                source_file_state="verified-before-load",
                source_file_identity=self.proof.identity[:2],
                source_descriptor_stamp=self.proof.identity,
                source_path_stamp=self.proof.named_identity,
            )
            self._announce(f"解析地图及全部已声明/可枚举章节: {scope}")
            md = load_map(scope, known_sha256=self.proof.digest)
            expected = (
                md.archive_source.expected_identity
                if isinstance(md.archive_source, PathArchiveSource)
                else None
            )
            actual = (
                (
                    expected.device,
                    expected.inode,
                    expected.size,
                    expected.mtime_ns,
                    expected.ctime_ns,
                    expected.mode,
                )
                if expected is not None
                else None
            )
            if actual != self.proof.identity:
                self.binding_diagnostics = (
                    f"{scope}: 加载器的归档快照身份未与扫描前完整 SHA-256 绑定；完整性未确认。"
                    f" scan={self.proof.identity!r}; loaded={actual!r}",
                )
                self.diagnostics.extend(self.binding_diagnostics)
            self._announce(f"整理地图对象与完整字段: {scope}")
            pending = [(md, "", "")]
            while pending:
                current, member, parent = pending.pop()
                current_scope = scope if not member else f"{scope}!{member}"
                self._announce(f"整理对象范围: {current_scope}")
                self._capture(current, current_scope, member, parent)
                pending.extend(
                    (
                        child,
                        f"{member}!{child.path}" if member else child.path,
                        current_scope,
                    )
                    for child in reversed(current.sub_maps)
                )
            self._missing_children(md, scope)
        except MapReferenceCancelled:
            raise
        except (OSError, ValueError, KeyError, IndexError, struct.error) as exc:
            message = f"{scope}: 地图目录读取失败: {type(exc).__name__}: {exc}"
            self.diagnostics.append(message)
            if not self.scopes:
                self.scopes.append(
                    ReferenceMapScope(
                        scope,
                        scope,
                        "",
                        self.path.name,
                        self.proof.digest if self.proof else "",
                        diagnostics=(message,),
                        complete=False,
                    )
                )
        finally:
            if md is not None:
                md.close()
        self.verify()

    def _capture(self, md: MapData, scope: str, member: str, parent: str) -> None:
        notes = list(_notes(md, scope))
        ledger = md.extraction_ledger
        digest = ledger.source_sha256 if ledger is not None else ""
        if not member and self.proof is not None:
            digest = self.proof.digest
        elif member:
            parent_member = self.sources.get(scope)
            if parent_member is not None and parent_member.sha256 != digest:
                notes.append(
                    f"{scope}: 子地图加载摘要与父归档成员摘要不一致；完整性未确认。"
                )
            self.sources[scope] = ReferenceSource(
                scope,
                str(self.path),
                digest,
                "战役章节的完整成员字节；原始归档路径与章节身份独立保留。",
                state="map-chapter",
                fingerprint_basis="archive-member-decoded-bytes",
                source_file_sha256=self.proof.digest if self.proof else "",
                source_file_state="verified-before-load",
                member_path=member,
                container_sha256=self.proof.digest if self.proof else "",
                source_file_identity=self.proof.identity[:2] if self.proof else None,
            )
        self.members[scope] = {}
        if ledger is None:
            notes.append(f"{scope}: 没有归档成员台账，成员来源完整性未确认。")
        else:
            notes.extend(f"{scope}: {warning}" for warning in ledger.warnings)
            for entry in ledger.entries:
                check_cancelled(self.cancelled)
                member_id = f"{scope}!{entry.internal_path}"
                self.members[scope][
                    entry.internal_path.replace("/", "\\").casefold()
                ] = member_id
                self.sources[member_id] = ReferenceSource(
                    member_id,
                    str(self.path),
                    entry.sha256,
                    f"归档成员 {entry.internal_path}; block={entry.block_index}; "
                    f"state={entry.state.value}; source={entry.source.value}; "
                    f"declared_bytes={entry.declared_size}; decoded_bytes={entry.written_size}; "
                    f"error={entry.error_code}; {entry.detail}",
                    state=f"map-member-{entry.state.value}",
                    fingerprint_basis="archive-member-decoded-bytes"
                    if entry.state in {BlockState.DECODED, BlockState.SUPPLEMENTED}
                    else "archive-member-raw-evidence",
                    source_file_sha256=self.proof.digest if self.proof else "",
                    source_file_state="verified-before-load",
                    member_path=f"{member}!{entry.internal_path}"
                    if member
                    else entry.internal_path,
                    container_sha256=digest,
                    source_file_identity=self.proof.identity[:2]
                    if self.proof
                    else None,
                )
                if entry.state not in {BlockState.DECODED, BlockState.SUPPLEMENTED}:
                    notes.append(
                        f"{member_id}: 成员未完整解码: {entry.state.value}; {entry.error_code}; {entry.detail}"
                    )
                elif entry.source is BlockSource.ARCHIVE_RECOVERED:
                    notes.append(
                        f"{member_id}: 成员原始名称未确认；保留摘要，不能证明对象表及战役章节均已定位。"
                    )
        identities, identity_notes = map_object_identities(
            md,
            scope,
            self.members[scope],
            self.sources,
            lambda: check_cancelled(self.cancelled),
        )
        notes.extend(identity_notes)
        self.identities[scope] = identities
        tables = map_object_tables(md, identities)
        for relative, table in tables.items():
            self.tables[virtual_table_key(scope, relative)] = table
            notes.extend(f"{scope} [{relative}]: {note}" for note in table.diagnostics)
        for bucket in md.objects.values():
            for obj in bucket:
                for evidence in obj.field_blockers:
                    notes.append(
                        f"{scope} {obj.category}:{obj.obj_id} {evidence.key}: "
                        f"{evidence.state.value}; {evidence.source}; {evidence.diagnostic}"
                    )
        self.diagnostics.extend(notes)
        self.scopes.append(
            ReferenceMapScope(
                scope,
                str(self.path),
                member,
                md.name,
                digest,
                tuple(
                    (category, len(tables[f"对象ID/{category}.tsv"].rows) - 1)
                    for category in OBJECT_TABLES
                ),
                parent,
                tuple(
                    (obj.category, obj.obj_id)
                    for bucket in md.objects.values()
                    for obj in bucket
                    if obj.ext == "campaign"
                ),
                tuple(notes),
                not notes,
            )
        )

    def _missing_children(self, md: MapData, root: str) -> None:
        if self.path.suffix.casefold() != ".w3n":
            return
        known = {
            scope.member_path.replace("/", "\\").casefold() for scope in self.scopes
        }
        declared = (
            tuple(entry.path for entry in md.w3f.maps) if md.w3f is not None else ()
        )
        failed = tuple(
            note.source for note in md.diagnostics if note.component == "campaign-child"
        )
        for member in (*declared, *md.all_files, *failed):
            key = member.replace("/", "\\").casefold()
            if not key.endswith((".w3x", ".w3m")) or key in known:
                continue
            known.add(key)
            scope = f"{root}!{member}"
            message = f"{scope}: 已声明/枚举的战役章节未成功加载；保留独立不完整范围。"
            self.diagnostics.append(message)
            source = self.sources.get(scope)
            self.scopes.append(
                ReferenceMapScope(
                    scope,
                    root,
                    member,
                    member,
                    source.sha256 if source else "",
                    shared_scope=root,
                    diagnostics=(message,),
                    complete=False,
                )
            )

    def _clean(self, text: str) -> str:
        return text

    def _named_table(self, pack: Path, relative: str, table: str = "") -> ObjectTable:
        return self.tables[virtual_table_key(str(pack), relative)]

    def verify(self) -> None:
        """Rehash all root bytes; child and member hashes bind to that exact root."""
        check_cancelled(self.cancelled)
        if self.proof is None:
            return
        try:
            unchanged = _prove(self.path) == self.proof
        except OSError:
            unchanged = False
        state = (
            "unbound-loader-snapshot"
            if unchanged and self.binding_diagnostics
            else "verified-after-load"
            if unchanged
            else "changed-before-delivery"
        )
        self.sources = {
            key: replace(value, source_file_state=state)
            for key, value in self.sources.items()
        }
        if not unchanged:
            message = f"{self.path}: 来源在目录交付前变化或不可读取；保留已读取证据，完整性未确认，请刷新。"
            if message not in self.diagnostics:
                self.diagnostics.append(message)
            self.scopes = [
                replace(
                    scope,
                    complete=False,
                    diagnostics=tuple(dict.fromkeys((*scope.diagnostics, message))),
                )
                for scope in self.scopes
            ]
        if self.binding_diagnostics:
            self.scopes = [
                replace(
                    scope,
                    complete=False,
                    diagnostics=tuple(
                        dict.fromkeys((*scope.diagnostics, *self.binding_diagnostics))
                    ),
                )
                for scope in self.scopes
            ]
        check_cancelled(self.cancelled)
