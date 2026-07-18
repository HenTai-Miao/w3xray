"""Strict canonical JSON codec for integrity snapshots."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Final

from .integrity_snapshot_models import (
    INTEGRITY_SNAPSHOT_SCHEMA,
    IntegrityEntry,
    IntegrityRoot,
    IntegritySnapshot,
    IntegritySnapshotError,
)
from .safe_output import safe_relative_path


type JsonValue = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)

_DIGEST: Final = re.compile(r"[0-9a-f]{64}")
_TOP_KEYS: Final = frozenset(("schema", "roots"))
_ROOT_KEYS: Final = frozenset(
    ("label", "path", "entries", "file_count", "total_size", "tree_sha256")
)
_ENTRY_KEYS: Final = frozenset(("path", "size", "mtime_ns", "sha256"))


def tree_sha256(entries: tuple[IntegrityEntry, ...]) -> str:
    """Hash canonical path, size, mtime, and file-digest tuples."""
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(
            json.dumps(
                (
                    entry.relative_path,
                    entry.size,
                    entry.mtime_ns,
                    entry.sha256,
                ),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def format_integrity_snapshot(snapshot: IntegritySnapshot) -> str:
    """Serialize one valid snapshot with exact keys and canonical whitespace."""
    _validate_snapshot(snapshot)
    value = {
        "roots": [
            {
                "entries": [
                    {
                        "mtime_ns": entry.mtime_ns,
                        "path": entry.relative_path,
                        "sha256": entry.sha256,
                        "size": entry.size,
                    }
                    for entry in root.entries
                ],
                "file_count": len(root.entries),
                "label": root.label,
                "path": root.path,
                "total_size": root.total_size,
                "tree_sha256": root.tree_sha256,
            }
            for root in snapshot.roots
        ],
        "schema": snapshot.schema,
    }
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def parse_integrity_snapshot(payload: str) -> IntegritySnapshot:
    """Parse exact JSON fields and reprove all canonical snapshot invariants."""
    try:
        value: JsonValue = json.loads(payload, object_pairs_hook=_unique_mapping)
    except json.JSONDecodeError as exc:
        raise IntegritySnapshotError(f"invalid snapshot JSON: {exc.msg}") from exc
    root = _mapping(value, "snapshot")
    _require_keys(root, _TOP_KEYS, "snapshot")
    raw_roots = root["roots"]
    if not isinstance(raw_roots, list):
        raise IntegritySnapshotError("snapshot roots must be a list")
    snapshot = IntegritySnapshot(
        _integer(root["schema"], "snapshot schema"),
        tuple(_parse_root(item) for item in raw_roots),
    )
    _validate_snapshot(snapshot)
    return snapshot


def _unique_mapping(
    pairs: list[tuple[str, JsonValue]],
) -> dict[str, JsonValue]:
    mapping: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in mapping:
            raise IntegritySnapshotError(f"duplicate snapshot JSON key: {key}")
        mapping[key] = value
    return mapping


def _parse_root(value: JsonValue) -> IntegrityRoot:
    root = _mapping(value, "root")
    _require_keys(root, _ROOT_KEYS, "root")
    raw_entries = root["entries"]
    if not isinstance(raw_entries, list):
        raise IntegritySnapshotError("root entries must be a list")
    entries = tuple(_parse_entry(item) for item in raw_entries)
    if _nonnegative(root["file_count"], "file count") != len(entries):
        raise IntegritySnapshotError("file count mismatch")
    return IntegrityRoot(
        _text(root["label"], "root label"),
        _text(root["path"], "root path"),
        entries,
        _nonnegative(root["total_size"], "total size"),
        _digest(root["tree_sha256"], "tree SHA-256"),
    )


def _parse_entry(value: JsonValue) -> IntegrityEntry:
    row = _mapping(value, "entry")
    _require_keys(row, _ENTRY_KEYS, "entry")
    return IntegrityEntry(
        _text(row["path"], "entry path"),
        _nonnegative(row["size"], "entry size"),
        _nonnegative(row["mtime_ns"], "entry mtime"),
        _digest(row["sha256"], "file SHA-256"),
    )


def _validate_snapshot(snapshot: IntegritySnapshot) -> None:
    if snapshot.schema != INTEGRITY_SNAPSHOT_SCHEMA:
        raise IntegritySnapshotError("unsupported integrity snapshot schema")
    labels: set[str] = set()
    paths: list[Path] = []
    for root in snapshot.roots:
        if not root.label or root.label in labels:
            raise IntegritySnapshotError("root labels must be unique and nonempty")
        labels.add(root.label)
        path = Path(root.path)
        if not path.is_absolute():
            raise IntegritySnapshotError("snapshot roots must be absolute")
        if any(
            path == previous
            or path.is_relative_to(previous)
            or previous.is_relative_to(path)
            for previous in paths
        ):
            raise IntegritySnapshotError("snapshot roots overlap")
        paths.append(path)
        _validate_root(root)
    if snapshot.roots != tuple(sorted(snapshot.roots, key=lambda item: item.label)):
        raise IntegritySnapshotError("snapshot roots are not sorted")


def _validate_root(root: IntegrityRoot) -> None:
    keys: set[str] = set()
    for entry in root.entries:
        relative = safe_relative_path(entry.relative_path)
        if relative is None or relative.as_posix() != entry.relative_path:
            raise IntegritySnapshotError("unsafe integrity entry path")
        folded = entry.relative_path.casefold()
        if folded in keys:
            raise IntegritySnapshotError("duplicate case-folded integrity path")
        keys.add(folded)
        if entry.size < 0 or entry.mtime_ns < 0:
            raise IntegritySnapshotError("negative integrity entry metadata")
        _require_digest(entry.sha256, "file SHA-256")
    ordered = tuple(
        sorted(
            root.entries,
            key=lambda item: (item.relative_path.casefold(), item.relative_path),
        )
    )
    if root.entries != ordered:
        raise IntegritySnapshotError("integrity entries are not sorted")
    if root.total_size != sum(entry.size for entry in root.entries):
        raise IntegritySnapshotError("integrity root byte total mismatch")
    _require_digest(root.tree_sha256, "tree SHA-256")
    if root.tree_sha256 != tree_sha256(root.entries):
        raise IntegritySnapshotError("integrity tree SHA-256 mismatch")


def _mapping(value: JsonValue, label: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise IntegritySnapshotError(f"{label} must be an object")
    return value


def _require_keys(
    value: dict[str, JsonValue], expected: frozenset[str], label: str
) -> None:
    if set(value) != expected:
        raise IntegritySnapshotError(f"unexpected {label} keys")


def _text(value: JsonValue, label: str) -> str:
    if not isinstance(value, str):
        raise IntegritySnapshotError(f"{label} must be text")
    return value


def _integer(value: JsonValue, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise IntegritySnapshotError(f"{label} must be an integer")
    return value


def _nonnegative(value: JsonValue, label: str) -> int:
    number = _integer(value, label)
    if number < 0:
        raise IntegritySnapshotError(f"{label} must be nonnegative")
    return number


def _digest(value: JsonValue, label: str) -> str:
    digest = _text(value, label)
    _require_digest(digest, label)
    return digest


def _require_digest(value: str, label: str) -> None:
    if _DIGEST.fullmatch(value) is None:
        raise IntegritySnapshotError(f"invalid {label}")


__all__ = ("format_integrity_snapshot", "parse_integrity_snapshot")
