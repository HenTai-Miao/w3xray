"""Strict manifest and marker schema for owned description caches."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from typing import Final

from .description_cache_schema import is_digest


TRUSTED_DESCRIPTION_CACHE_MARKER: Final = ".w3xray-trusted-description-cache"
TRUSTED_DESCRIPTION_CACHE_SCHEMA: Final = 1
TRUSTED_DESCRIPTION_CACHE_FILES: Final = (
    "可信描述缓存.tsv",
    "来源清单.tsv",
    "可信缓存迁移拒绝.tsv",
)
TRUSTED_DESCRIPTION_CACHE_MANIFEST: Final = "内容清单.json"
TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY: Final = tuple(
    sorted(
        (
            *TRUSTED_DESCRIPTION_CACHE_FILES,
            TRUSTED_DESCRIPTION_CACHE_MANIFEST,
            TRUSTED_DESCRIPTION_CACHE_MARKER,
        ),
        key=lambda name: name.encode("utf-8"),
    )
)

type JsonValue = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)


@dataclass(frozen=True, slots=True)
class TrustedCacheArtifact:
    """One exact owned payload bound by size and SHA-256."""

    name: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class TrustedCacheManifest:
    """Exact payload inventory plus the only permitted source root."""

    schema_version: int
    source_root: str
    artifacts: tuple[TrustedCacheArtifact, ...]
    content_sha256: str


class TrustedCacheSchemaError(ValueError):
    """Owned cache metadata does not match its closed schema."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    def __str__(self) -> str:
        return self.detail


def format_trusted_cache_manifest(manifest: TrustedCacheManifest) -> str:
    """Serialize a validated manifest deterministically."""
    _validate_manifest(manifest)
    value = {
        "artifact_count": len(manifest.artifacts),
        "artifacts": [
            {"name": item.name, "sha256": item.sha256, "size": item.size}
            for item in manifest.artifacts
        ],
        "content_sha256": manifest.content_sha256,
        "schema_version": manifest.schema_version,
        "source_root": manifest.source_root,
    }
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def parse_trusted_cache_manifest(text: str) -> TrustedCacheManifest:
    """Parse exact manifest keys, types, inventory, ordering, and digests."""
    try:
        value: JsonValue = json.loads(text, object_pairs_hook=_unique_mapping)
    except json.JSONDecodeError as exc:
        raise TrustedCacheSchemaError(f"invalid manifest JSON: {exc.msg}") from exc
    root = _mapping(value, "manifest")
    _require_keys(
        root,
        {
            "artifact_count",
            "artifacts",
            "content_sha256",
            "schema_version",
            "source_root",
        },
    )
    artifacts = _parse_artifacts(root["artifacts"])
    if _nonnegative(root["artifact_count"], "artifact count") != len(artifacts):
        raise TrustedCacheSchemaError("artifact count mismatch")
    manifest = TrustedCacheManifest(
        _integer(root["schema_version"], "schema version"),
        _text(root["source_root"], "source root"),
        artifacts,
        _digest(root["content_sha256"], "content SHA-256"),
    )
    _validate_manifest(manifest)
    return manifest


def format_trusted_cache_marker(manifest_sha256: str) -> str:
    """Bind the owned marker to exactly one manifest digest."""
    if not is_digest(manifest_sha256):
        raise TrustedCacheSchemaError("invalid manifest SHA-256")
    return f"schema={TRUSTED_DESCRIPTION_CACHE_SCHEMA}\nmanifest_sha256={manifest_sha256}\n"


def parse_trusted_cache_marker(text: str) -> str:
    """Parse the exact two-line owned marker."""
    lines = text.splitlines()
    if len(lines) != 2 or lines[0] != f"schema={TRUSTED_DESCRIPTION_CACHE_SCHEMA}":
        raise TrustedCacheSchemaError("unsupported marker schema")
    if not lines[1].startswith("manifest_sha256="):
        raise TrustedCacheSchemaError("invalid ownership marker")
    digest = lines[1].removeprefix("manifest_sha256=")
    if not is_digest(digest) or text != format_trusted_cache_marker(digest):
        raise TrustedCacheSchemaError("invalid marker manifest SHA-256")
    return digest


def trusted_content_sha256(artifacts: Sequence[TrustedCacheArtifact]) -> str:
    """Hash sorted payload identity tuples without depending on JSON layout."""
    ordered = tuple(sorted(artifacts, key=lambda item: item.name.casefold()))
    text = "".join(f"{item.name}\t{item.size}\t{item.sha256}\n" for item in ordered)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_artifacts(value: JsonValue) -> tuple[TrustedCacheArtifact, ...]:
    if not isinstance(value, list):
        raise TrustedCacheSchemaError("artifacts must be a list")
    artifacts: list[TrustedCacheArtifact] = []
    names: set[str] = set()
    for item in value:
        row = _mapping(item, "artifact")
        _require_keys(row, {"name", "sha256", "size"})
        name = _text(row["name"], "artifact name")
        if name in names:
            raise TrustedCacheSchemaError("duplicate artifact name")
        names.add(name)
        artifacts.append(
            TrustedCacheArtifact(
                name,
                _nonnegative(row["size"], "artifact size"),
                _digest(row["sha256"], "artifact SHA-256"),
            )
        )
    ordered = tuple(sorted(artifacts, key=lambda item: item.name.casefold()))
    if tuple(artifacts) != ordered:
        raise TrustedCacheSchemaError("artifacts are not sorted")
    return ordered


def _validate_manifest(manifest: TrustedCacheManifest) -> None:
    if manifest.schema_version != TRUSTED_DESCRIPTION_CACHE_SCHEMA:
        raise TrustedCacheSchemaError("unsupported manifest schema")
    if not manifest.source_root:
        raise TrustedCacheSchemaError("source root is empty")
    if {item.name for item in manifest.artifacts} != set(
        TRUSTED_DESCRIPTION_CACHE_FILES
    ):
        raise TrustedCacheSchemaError("owned payload set mismatch")
    if any(item.size < 0 or not is_digest(item.sha256) for item in manifest.artifacts):
        raise TrustedCacheSchemaError("invalid artifact identity")
    if trusted_content_sha256(manifest.artifacts) != manifest.content_sha256:
        raise TrustedCacheSchemaError("content SHA-256 mismatch")


def _unique_mapping(pairs: list[tuple[str, JsonValue]]) -> Mapping[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise TrustedCacheSchemaError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _mapping(value: JsonValue, label: str) -> Mapping[str, JsonValue]:
    if not isinstance(value, dict):
        raise TrustedCacheSchemaError(f"{label} must be an object")
    return value


def _require_keys(value: Mapping[str, JsonValue], expected: set[str]) -> None:
    if set(value) != expected:
        raise TrustedCacheSchemaError("unexpected manifest keys")


def _text(value: JsonValue, label: str) -> str:
    if not isinstance(value, str):
        raise TrustedCacheSchemaError(f"{label} must be text")
    return value


def _integer(value: JsonValue, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TrustedCacheSchemaError(f"{label} must be an integer")
    return value


def _nonnegative(value: JsonValue, label: str) -> int:
    number = _integer(value, label)
    if number < 0:
        raise TrustedCacheSchemaError(f"{label} must be nonnegative")
    return number


def _digest(value: JsonValue, label: str) -> str:
    digest = _text(value, label)
    if not is_digest(digest):
        raise TrustedCacheSchemaError(f"invalid {label}")
    return digest
