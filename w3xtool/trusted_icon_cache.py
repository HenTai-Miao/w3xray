"""Read hash-bound icon payloads and evidence from an owned historical cache."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import Final, Mapping, final, override

from .icon_resources import (
    HistoricalIconEvidenceSet,
    IconObjectReference,
    NamedIconResource,
)
from .safe_output import safe_destination, safe_relative_path

TRUSTED_ICON_CACHE_MARKER: Final = ".w3xray-trusted-icon-cache"
_PAYLOAD_MANIFEST: Final = "可信图标缓存.tsv"
_EVIDENCE_DIRECTORY: Final = "地图图标证据"
_PAYLOAD_HEADER: Final = (
    "虚拟路径",
    "SHA256",
    "原客户端档案",
    "验证来源目录",
)
_EVIDENCE_HEADER: Final = (
    "原始路径",
    "解析路径",
    "SHA256",
    "原客户端档案",
    "引用对象",
)
_CLIENT_ARCHIVES: Final = frozenset(
    ("war3patch.mpq", "war3xlocal.mpq", "war3x.mpq", "war3.mpq")
)
_SHA256: Final = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class TrustedIconCacheError(OSError):
    path: str
    detail: str

    @override
    def __str__(self) -> str:
        return f"invalid trusted icon cache {self.path}: {self.detail}"


@dataclass(frozen=True, slots=True)
class _CachedPayload:
    virtual_path: str
    digest: str
    source_archive: str
    payload_path: str


@final
class TrustedIconCacheDataSource:
    """Expose only verified client paths and same-map historical evidence."""

    __slots__ = ("_payloads", "root")

    root: str
    _payloads: Mapping[str, _CachedPayload]

    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(root)
        self._validate_root()
        payloads: dict[str, _CachedPayload] = {}
        for row in _read_tsv(Path(self.root, _PAYLOAD_MANIFEST), _PAYLOAD_HEADER):
            virtual_path, digest, source_archive, _verified_from = row
            normalized = _parse_icon_path(virtual_path, self.root)
            _parse_digest(digest, self.root)
            archive = _parse_archive(source_archive, self.root)
            key = _path_key(normalized)
            previous = payloads.get(key)
            if previous is not None and previous.digest != digest:
                raise TrustedIconCacheError(
                    self.root,
                    f"conflicting virtual path: {normalized}",
                )
            payload_path = safe_destination(self.root, normalized)
            if (
                payload_path is None
                or os.path.islink(payload_path)
                or not os.path.isfile(payload_path)
            ):
                raise TrustedIconCacheError(self.root, f"missing payload: {normalized}")
            entry = _CachedPayload(normalized, digest, archive, payload_path)
            if previous is None:
                payloads[key] = entry
        self._payloads = MappingProxyType(payloads)

    def has_file(self, name: str) -> bool:
        return _path_key(name) in self._payloads

    def read_file(self, name: str) -> bytes:
        entry = self._payloads.get(_path_key(name))
        if entry is None:
            raise FileNotFoundError(name)
        try:
            with open(entry.payload_path, "rb") as handle:
                payload = handle.read()
        except OSError as exc:
            raise TrustedIconCacheError(entry.payload_path, str(exc)) from exc
        if hashlib.sha256(payload).hexdigest() != entry.digest:
            raise TrustedIconCacheError(entry.payload_path, "payload hash mismatch")
        return payload

    def has_exact_file(self, name: str) -> bool:
        return self.has_file(name)

    def read_exact_file(self, name: str) -> bytes:
        return self.read_file(name)

    def read_file_with_source(self, name: str) -> tuple[bytes, str]:
        entry = self._payloads.get(_path_key(name))
        if entry is None:
            raise FileNotFoundError(name)
        return self.read_file(name), f"可信图标缓存:{entry.source_archive}"

    def historical_icons_for(self, source_digest: str) -> HistoricalIconEvidenceSet:
        _parse_digest(source_digest, self.root)
        evidence_path = safe_destination(
            self.root,
            f"{_EVIDENCE_DIRECTORY}/{source_digest}.tsv",
        )
        if evidence_path is None:
            raise TrustedIconCacheError(self.root, "unsafe evidence path")
        evidence = Path(evidence_path)
        if not evidence.exists():
            return HistoricalIconEvidenceSet(available=False, resources=())
        records: list[NamedIconResource] = []
        for row in _read_tsv(evidence, _EVIDENCE_HEADER):
            requested, resolved, digest, source_archive, encoded_objects = row
            requested = _parse_icon_path(requested, str(evidence))
            resolved = _parse_icon_path(resolved, str(evidence))
            _parse_digest(digest, str(evidence))
            archive = _parse_archive(source_archive, str(evidence))
            payload_entry = self._payloads.get(_path_key(resolved))
            if payload_entry is None or payload_entry.digest != digest:
                raise TrustedIconCacheError(
                    str(evidence),
                    f"unbound payload: {resolved}",
                )
            if payload_entry.source_archive != archive:
                raise TrustedIconCacheError(
                    str(evidence),
                    f"archive mismatch: {resolved}",
                )
            payload = self.read_file(resolved)
            records.append(
                NamedIconResource(
                    requested_path=requested,
                    normalized_path=requested,
                    resolved_path=resolved,
                    source_path=f"可信图标缓存:{archive}",
                    payload=payload,
                    sha256=digest,
                    objects=_parse_objects(encoded_objects, str(evidence)),
                )
            )
        return HistoricalIconEvidenceSet(available=True, resources=tuple(records))

    def close(self) -> None:
        """Release no resources because every payload read owns its handle."""

    def _validate_root(self) -> None:
        marker = Path(self.root, TRUSTED_ICON_CACHE_MARKER)
        manifest = Path(self.root, _PAYLOAD_MANIFEST)
        if os.path.islink(self.root) or not os.path.isdir(self.root):
            raise TrustedIconCacheError(self.root, "root is not a regular directory")
        if marker.is_symlink() or not marker.is_file():
            raise TrustedIconCacheError(self.root, "ownership marker missing")
        try:
            schema = marker.read_text(encoding="ascii").splitlines()
        except (OSError, UnicodeError) as exc:
            raise TrustedIconCacheError(str(marker), str(exc)) from exc
        if not schema or schema[0] != "schema=2":
            raise TrustedIconCacheError(str(marker), "unsupported schema")
        if manifest.is_symlink() or not manifest.is_file():
            raise TrustedIconCacheError(self.root, "payload manifest missing")


def is_trusted_icon_cache(path: str) -> bool:
    """Recognize the explicit owned-cache marker before generic directories."""
    root = Path(path)
    marker = root / TRUSTED_ICON_CACHE_MARKER
    manifest = root / _PAYLOAD_MANIFEST
    return (
        root.is_dir()
        and not root.is_symlink()
        and marker.is_file()
        and not marker.is_symlink()
        and manifest.is_file()
        and not manifest.is_symlink()
    )


def _read_tsv(path: Path, header: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    if path.is_symlink() or not path.is_file():
        raise TrustedIconCacheError(str(path), "table missing")
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = tuple(tuple(row) for row in csv.reader(handle, delimiter="\t"))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise TrustedIconCacheError(str(path), str(exc)) from exc
    if not rows or rows[0] != header:
        raise TrustedIconCacheError(str(path), "unexpected table header")
    if any(len(row) != len(header) for row in rows[1:]):
        raise TrustedIconCacheError(str(path), "malformed table row")
    return rows[1:]


def _parse_icon_path(value: str, source: str) -> str:
    parsed = safe_relative_path(value.strip().strip('"'))
    if parsed is None:
        raise TrustedIconCacheError(source, f"unsafe icon path: {value}")
    return str(parsed).replace("/", "\\")


def _parse_digest(value: str, source: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise TrustedIconCacheError(source, f"invalid SHA-256: {value}")


def _parse_archive(value: str, source: str) -> str:
    archive = Path(value).name.casefold()
    if archive not in _CLIENT_ARCHIVES:
        raise TrustedIconCacheError(source, f"untrusted client archive: {value}")
    return archive


def _parse_objects(value: str, source: str) -> tuple[IconObjectReference, ...]:
    if not value:
        return ()
    references: list[IconObjectReference] = []
    for encoded in value.split(";"):
        parts = encoded.split(":", 2)
        if len(parts) != 3 or not parts[0] or not parts[1]:
            raise TrustedIconCacheError(
                source, f"malformed object reference: {encoded}"
            )
        references.append(IconObjectReference(parts[0], parts[1], parts[2]))
    if (
        ";".join(
            f"{item.category}:{item.object_id}:{item.object_name}"
            for item in references
        )
        != value
    ):
        raise TrustedIconCacheError(source, "object reference round-trip mismatch")
    return tuple(references)


def _path_key(name: str) -> str:
    return name.replace("\\", "/").lstrip("/").casefold()
