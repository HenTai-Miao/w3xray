"""Deterministic strict JSON I/O for global manifests and pointers."""

from __future__ import annotations

import json
import re
from typing import Final

from .batch_global_models import (
    GLOBAL_PAYLOAD_NAMES,
    GLOBAL_SCHEMA_VERSION,
    GlobalArtifact,
    GlobalFormatError,
    GlobalManifest,
    GlobalPointer,
)
from .batch_models import BATCH_SCHEMA_VERSION


_SHA256: Final = re.compile(r"[0-9a-f]{64}")
_GENERATION_ID: Final = re.compile(r"[0-9a-f]{32}")

type JsonValue = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)


def format_global_manifest(manifest: GlobalManifest) -> str:
    """Serialize a validated manifest with stable keys and ordering."""
    _validate_manifest(manifest)
    payload = {
        "artifact_count": len(manifest.artifacts),
        "artifacts": [
            {"name": item.name, "sha256": item.sha256, "size": item.size}
            for item in manifest.artifacts
        ],
        "generation_id": manifest.generation_id,
        "schema_version": manifest.schema_version,
        "state_schema_version": manifest.state_schema_version,
        "total_size": manifest.total_size,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def parse_global_manifest(text: str) -> GlobalManifest:
    """Parse a manifest and reject unknown keys or ambiguous file inventories."""
    raw = _json_mapping(text, "global manifest")
    _require_keys(
        raw,
        {
            "artifact_count",
            "artifacts",
            "generation_id",
            "schema_version",
            "state_schema_version",
            "total_size",
        },
    )
    artifacts = _artifacts(raw["artifacts"])
    manifest = GlobalManifest(
        _integer(raw["schema_version"], "schema version"),
        _generation_id(raw["generation_id"]),
        _integer(raw["state_schema_version"], "state schema version"),
        artifacts,
        _nonnegative(raw["total_size"], "total size"),
    )
    if _nonnegative(raw["artifact_count"], "artifact count") != len(artifacts):
        raise GlobalFormatError("global artifact count mismatch")
    _validate_manifest(manifest)
    return manifest


def format_global_pointer(pointer: GlobalPointer) -> str:
    """Serialize the authoritative generation selector deterministically."""
    _validate_pointer(pointer)
    payload = {
        "generation_id": pointer.generation_id,
        "manifest_sha256": pointer.manifest_sha256,
        "schema_version": pointer.schema_version,
    }
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def parse_global_pointer(text: str) -> GlobalPointer:
    """Parse a pointer without accepting traversal or noncanonical hashes."""
    raw = _json_mapping(text, "global pointer")
    _require_keys(raw, {"generation_id", "manifest_sha256", "schema_version"})
    pointer = GlobalPointer(
        _integer(raw["schema_version"], "schema version"),
        _generation_id(raw["generation_id"]),
        _digest(raw["manifest_sha256"], "manifest SHA-256"),
    )
    _validate_pointer(pointer)
    return pointer


def _artifacts(value: JsonValue) -> tuple[GlobalArtifact, ...]:
    if not isinstance(value, list):
        raise GlobalFormatError("global artifacts must be a list")
    result: list[GlobalArtifact] = []
    names: set[str] = set()
    for item in value:
        raw = _mapping(item, "global artifact")
        _require_keys(raw, {"name", "sha256", "size"})
        name = _text(raw["name"], "artifact name")
        if name in names:
            raise GlobalFormatError("duplicate global artifact")
        names.add(name)
        result.append(
            GlobalArtifact(
                name,
                _nonnegative(raw["size"], "artifact size"),
                _digest(raw["sha256"], "artifact SHA-256"),
            )
        )
    ordered = tuple(sorted(result, key=lambda artifact: artifact.name.casefold()))
    if tuple(result) != ordered:
        raise GlobalFormatError("global artifacts are not sorted")
    return ordered


def _validate_manifest(manifest: GlobalManifest) -> None:
    if manifest.schema_version != GLOBAL_SCHEMA_VERSION:
        raise GlobalFormatError("unsupported global manifest schema")
    _require_generation_id(manifest.generation_id)
    if manifest.state_schema_version != BATCH_SCHEMA_VERSION:
        raise GlobalFormatError("global state schema mismatch")
    expected_names = set(GLOBAL_PAYLOAD_NAMES)
    if {item.name for item in manifest.artifacts} != expected_names:
        raise GlobalFormatError("global payload set mismatch")
    if manifest.total_size != sum(item.size for item in manifest.artifacts):
        raise GlobalFormatError("global byte count mismatch")
    for artifact in manifest.artifacts:
        if _SHA256.fullmatch(artifact.sha256) is None:
            raise GlobalFormatError("invalid global artifact SHA-256")


def _validate_pointer(pointer: GlobalPointer) -> None:
    if pointer.schema_version != GLOBAL_SCHEMA_VERSION:
        raise GlobalFormatError("unsupported global pointer schema")
    _require_generation_id(pointer.generation_id)
    if _SHA256.fullmatch(pointer.manifest_sha256) is None:
        raise GlobalFormatError("invalid global manifest SHA-256")


def _json_mapping(text: str, label: str) -> dict[str, JsonValue]:
    try:
        value: JsonValue = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GlobalFormatError(f"invalid {label} JSON: {exc.msg}") from exc
    return _mapping(value, label)


def _mapping(value: JsonValue, label: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise GlobalFormatError(f"{label} must be an object")
    return value


def _require_keys(value: dict[str, JsonValue], expected: set[str]) -> None:
    if set(value) != expected:
        raise GlobalFormatError("unexpected global JSON keys")


def _text(value: JsonValue, label: str) -> str:
    if not isinstance(value, str):
        raise GlobalFormatError(f"{label} must be text")
    return value


def _integer(value: JsonValue, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GlobalFormatError(f"{label} must be an integer")
    return value


def _nonnegative(value: JsonValue, label: str) -> int:
    number = _integer(value, label)
    if number < 0:
        raise GlobalFormatError(f"{label} must be nonnegative")
    return number


def _digest(value: JsonValue, label: str) -> str:
    digest = _text(value, label)
    if _SHA256.fullmatch(digest) is None:
        raise GlobalFormatError(f"invalid {label}")
    return digest


def _generation_id(value: JsonValue) -> str:
    generation_id = _text(value, "generation ID")
    _require_generation_id(generation_id)
    return generation_id


def _require_generation_id(generation_id: str) -> None:
    if _GENERATION_ID.fullmatch(generation_id) is None:
        raise GlobalFormatError("invalid generation ID")
