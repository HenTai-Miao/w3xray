"""Deterministic formatting and strict parsing for map publication metadata."""

from __future__ import annotations

import json
import re
from typing import Final

from .batch_manifest_models import (
    MANIFEST_SCHEMA_VERSION,
    OWNERSHIP_SCHEMA_VERSION,
    ArtifactKind,
    BatchManifestFormatError,
    ManifestArtifact,
    MapContentManifest,
    OwnershipRecord,
)
from .batch_manifest_summary import (
    JsonValue,
    manifest_summary_payload,
    parse_manifest_summary,
)
from .batch_models import SourceFingerprint
from .safe_output import safe_relative_path


_SHA256: Final = re.compile(r"[0-9a-f]{64}")
_TRANSACTION_ID: Final = re.compile(r"[0-9a-f]{32}")


def format_map_manifest(manifest: MapContentManifest) -> str:
    """Serialize one manifest with stable keys and artifact ordering."""
    payload = {
        "artifact_count": len(manifest.artifacts),
        "artifacts": [
            {
                "kind": item.kind.value,
                "relative_path": item.relative_path,
                "sha256": item.sha256,
                "size": item.size,
            }
            for item in manifest.artifacts
        ],
        "dependency_fingerprint": manifest.dependency_fingerprint,
        "result": manifest_summary_payload(manifest.result),
        "schema_version": manifest.schema_version,
        "source": {
            "mtime_ns": manifest.source.mtime_ns,
            "path": manifest.source.path,
            "sha256": manifest.source.sha256,
            "size": manifest.source.size,
        },
        "total_size": manifest.total_size,
        "transaction_id": manifest.transaction_id,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def parse_map_manifest(text: str) -> MapContentManifest:
    """Parse a manifest and reject malformed or ambiguous identities."""
    raw = _json_mapping(text, "manifest")
    _require_keys(
        raw,
        {
            "artifact_count",
            "artifacts",
            "dependency_fingerprint",
            "result",
            "schema_version",
            "source",
            "total_size",
            "transaction_id",
        },
    )
    if _integer(raw["schema_version"], "schema_version") != MANIFEST_SCHEMA_VERSION:
        raise BatchManifestFormatError("unsupported manifest schema")
    transaction_id = _transaction_id(raw["transaction_id"])
    dependency = _digest(raw["dependency_fingerprint"], "dependency fingerprint")
    source = _parse_source(raw["source"])
    summary = parse_manifest_summary(raw["result"])
    artifacts = _parse_artifacts(raw["artifacts"])
    artifact_count = _nonnegative(raw["artifact_count"], "artifact_count")
    total_size = _nonnegative(raw["total_size"], "total_size")
    if artifact_count != len(artifacts):
        raise BatchManifestFormatError("manifest artifact count mismatch")
    if total_size != sum(item.size for item in artifacts):
        raise BatchManifestFormatError("manifest byte count mismatch")
    return MapContentManifest(
        MANIFEST_SCHEMA_VERSION,
        transaction_id,
        source,
        dependency,
        summary,
        artifacts,
        total_size,
    )


def format_ownership_record(record: OwnershipRecord) -> str:
    """Serialize the source/manifest ownership binding."""
    payload = {
        "manifest_sha256": record.manifest_sha256,
        "schema_version": record.schema_version,
        "source_sha256": record.source_sha256,
        "transaction_id": record.transaction_id,
    }
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def parse_ownership_record(text: str) -> OwnershipRecord:
    """Parse only the current JSON ownership schema."""
    raw = _json_mapping(text, "ownership marker")
    _require_keys(
        raw,
        {"manifest_sha256", "schema_version", "source_sha256", "transaction_id"},
    )
    if _integer(raw["schema_version"], "schema_version") != OWNERSHIP_SCHEMA_VERSION:
        raise BatchManifestFormatError("unsupported ownership schema")
    return OwnershipRecord(
        OWNERSHIP_SCHEMA_VERSION,
        _digest(raw["source_sha256"], "source SHA-256"),
        _digest(raw["manifest_sha256"], "manifest SHA-256"),
        _transaction_id(raw["transaction_id"]),
    )


def _parse_source(value: JsonValue) -> SourceFingerprint:
    raw = _mapping(value, "source")
    _require_keys(raw, {"mtime_ns", "path", "sha256", "size"})
    return SourceFingerprint(
        _string(raw["path"], "source path"),
        _nonnegative(raw["size"], "source size"),
        _nonnegative(raw["mtime_ns"], "source mtime"),
        _digest(raw["sha256"], "source SHA-256"),
    )


def _parse_artifacts(value: JsonValue) -> tuple[ManifestArtifact, ...]:
    if not isinstance(value, list):
        raise BatchManifestFormatError("manifest artifacts must be a list")
    artifacts: list[ManifestArtifact] = []
    identities: set[str] = set()
    for value_item in value:
        raw = _mapping(value_item, "artifact")
        _require_keys(raw, {"kind", "relative_path", "sha256", "size"})
        relative = _string(raw["relative_path"], "artifact path")
        parsed = safe_relative_path(relative)
        if parsed is None or parsed.as_posix() != relative:
            raise BatchManifestFormatError("unsafe artifact path")
        identity = relative.casefold()
        if identity in identities:
            raise BatchManifestFormatError("duplicate artifact path")
        identities.add(identity)
        artifacts.append(
            ManifestArtifact(
                relative,
                ArtifactKind(_string(raw["kind"], "artifact kind")),
                _nonnegative(raw["size"], "artifact size"),
                _digest(raw["sha256"], "artifact SHA-256"),
            )
        )
    if artifacts != sorted(artifacts, key=lambda item: item.relative_path.casefold()):
        raise BatchManifestFormatError("manifest artifacts are not sorted")
    return tuple(artifacts)


def _json_mapping(text: str, label: str) -> dict[str, JsonValue]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BatchManifestFormatError(f"invalid {label} JSON: {exc.msg}") from exc
    return _mapping(value, label)


def _mapping(value: JsonValue, label: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise BatchManifestFormatError(f"{label} must be an object")
    return value


def _require_keys(value: dict[str, JsonValue], expected: set[str]) -> None:
    if set(value) != expected:
        raise BatchManifestFormatError("unexpected JSON keys")


def _string(value: JsonValue, label: str) -> str:
    if not isinstance(value, str):
        raise BatchManifestFormatError(f"{label} must be text")
    return value


def _integer(value: JsonValue, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BatchManifestFormatError(f"{label} must be an integer")
    return value


def _nonnegative(value: JsonValue, label: str) -> int:
    number = _integer(value, label)
    if number < 0:
        raise BatchManifestFormatError(f"{label} must be nonnegative")
    return number


def _digest(value: JsonValue, label: str) -> str:
    digest = _string(value, label)
    if _SHA256.fullmatch(digest) is None:
        raise BatchManifestFormatError(f"invalid {label}")
    return digest


def _transaction_id(value: JsonValue) -> str:
    transaction_id = _string(value, "transaction ID")
    if _TRANSACTION_ID.fullmatch(transaction_id) is None:
        raise BatchManifestFormatError("invalid transaction ID")
    return transaction_id
