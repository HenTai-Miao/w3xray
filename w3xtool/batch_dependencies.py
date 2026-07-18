"""Deterministic dependency evidence for resumable batch results."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Final, Protocol

from . import __version__
from .batch_models import BATCH_SCHEMA_VERSION, SourceFingerprint
from .bounded_file import sha256_regular_file
from .classic_mpq_source import classic_mpq_paths, is_classic_mpq_install
from .trusted_icon_cache import TRUSTED_ICON_CACHE_MARKER, is_trusted_icon_cache


_SHA256: Final = re.compile(r"[0-9a-f]{64}")
_MAX_IDENTITY_FILE_BYTES: Final = 256 * 1024 * 1024
_TRUSTED_MANIFEST: Final = "可信图标缓存.tsv"
_TRUSTED_EVIDENCE_DIRECTORY: Final = "地图图标证据"
BATCH_EXTRACTION_REVISION: Final = 5

type EvidenceField = str | int
type EvidenceRecord = tuple[EvidenceField, ...]


class BatchOptionsView(Protocol):
    """Extraction options whose values may affect map output bytes."""

    @property
    def game_data_path(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class DependencyEvidence:
    """Bounded summary of one selected Warcraft client-data source."""

    kind: str
    file_count: int
    total_size: int
    identity_sha256: str


class DependencyFingerprintError(ValueError):
    """Dependency evidence is unsafe, unstable, or semantically invalid."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    def __str__(self) -> str:
        return self.detail


def fingerprint_dependencies(
    source: SourceFingerprint,
    options: BatchOptionsView,
    description_cache_manifest_sha256: str,
) -> str:
    """Hash schema, tool, source, options, client evidence, and trusted cache."""
    _require_digest(source.sha256, "source SHA-256")
    _require_digest(
        description_cache_manifest_sha256,
        "description cache manifest SHA-256",
    )
    evidence = _game_data_evidence(options.game_data_path)
    normalized_path = (
        ""
        if options.game_data_path is None
        else os.path.normcase(
            os.path.abspath(os.path.expanduser(options.game_data_path))
        )
    )
    payload = {
        "batch_extraction_revision": BATCH_EXTRACTION_REVISION,
        "batch_schema_version": BATCH_SCHEMA_VERSION,
        "description_cache_manifest_sha256": description_cache_manifest_sha256,
        "client": {
            "file_count": evidence.file_count,
            "identity_sha256": evidence.identity_sha256,
            "kind": evidence.kind,
            "total_size": evidence.total_size,
        },
        "game_data_path": normalized_path,
        "source_sha256": source.sha256,
        "tool_version": __version__,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _game_data_evidence(path: str | None) -> DependencyEvidence:
    if path is None:
        return _empty_evidence("missing")
    root = Path(path).expanduser()
    if root.is_symlink():
        raise DependencyFingerprintError("game-data root is a symlink")
    if not root.exists():
        return _empty_evidence("missing")
    if not root.is_dir():
        raise DependencyFingerprintError("game-data root is not a directory")
    if is_trusted_icon_cache(str(root)):
        return _trusted_cache_evidence(root)
    if is_classic_mpq_install(str(root)):
        records = (
            _stat_record(root, Path(archive), include_hash=False)
            for archive in classic_mpq_paths(str(root))
        )
        return _summarize("classic_mpq", records)
    build_info = root / ".build.info"
    data_root = root / "Data" / "data"
    if build_info.is_file() and data_root.is_dir():
        return _casc_evidence(root, build_info, data_root)
    return _summarize("extracted_dir", _walk_records(root, include_hash=False))


def _trusted_cache_evidence(root: Path) -> DependencyEvidence:
    def records() -> Iterator[EvidenceRecord]:
        yield _stat_record(
            root,
            root / TRUSTED_ICON_CACHE_MARKER,
            include_hash=True,
        )
        yield _stat_record(root, root / _TRUSTED_MANIFEST, include_hash=True)
        evidence_root = root / _TRUSTED_EVIDENCE_DIRECTORY
        if evidence_root.exists():
            yield from _walk_records(evidence_root, include_hash=True, base=root)

    return _summarize("trusted_icon_cache", records())


def _casc_evidence(
    root: Path,
    build_info: Path,
    data_root: Path,
) -> DependencyEvidence:
    records: list[EvidenceRecord] = [_stat_record(root, build_info, include_hash=True)]
    for path in sorted(data_root.iterdir(), key=lambda item: item.name.casefold()):
        name = path.name.casefold()
        if name.endswith(".idx") or name.startswith("data."):
            records.append(_stat_record(root, path, include_hash=False))
    return _summarize("native_casc", tuple(records))


def _walk_records(
    root: Path,
    *,
    include_hash: bool,
    base: Path | None = None,
) -> Iterator[EvidenceRecord]:
    relative_root = root if base is None else base
    for directory, names, files in os.walk(root, followlinks=False):
        names.sort(key=str.casefold)
        files.sort(key=str.casefold)
        directory_path = Path(directory)
        retained: list[str] = []
        for name in names:
            child = directory_path / name
            if child.is_symlink():
                raise DependencyFingerprintError(f"symlink in game-data tree: {child}")
            retained.append(name)
        names[:] = retained
        for name in files:
            path = directory_path / name
            yield _stat_record(relative_root, path, include_hash=include_hash)


def _stat_record(
    root: Path,
    path: Path,
    *,
    include_hash: bool,
) -> EvidenceRecord:
    details = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(details.st_mode):
        raise DependencyFingerprintError(f"unsafe dependency file: {path}")
    relative = path.relative_to(root).as_posix()
    if include_hash:
        digest, identity = sha256_regular_file(path, _MAX_IDENTITY_FILE_BYTES)
        if identity.size != details.st_size:
            raise DependencyFingerprintError(f"dependency file changed: {path}")
        return relative, details.st_size, details.st_mtime_ns, digest
    return relative, details.st_size, details.st_mtime_ns


def _summarize(
    kind: str,
    records: Iterable[EvidenceRecord],
) -> DependencyEvidence:
    digest = hashlib.sha256()
    total_size = 0
    file_count = 0
    for record in records:
        digest.update(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode()
        )
        digest.update(b"\n")
        total_size += int(record[1])
        file_count += 1
    return DependencyEvidence(kind, file_count, total_size, digest.hexdigest())


def _empty_evidence(kind: str) -> DependencyEvidence:
    return DependencyEvidence(kind, 0, 0, hashlib.sha256(b"").hexdigest())


def _require_digest(value: str, label: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise DependencyFingerprintError(f"invalid {label}")


__all__ = (
    "BATCH_EXTRACTION_REVISION",
    "BatchOptionsView",
    "DependencyEvidence",
    "DependencyFingerprintError",
    "fingerprint_dependencies",
)
