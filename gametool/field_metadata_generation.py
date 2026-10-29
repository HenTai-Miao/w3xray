"""Validated, versioned inputs for the offline field-metadata generator.

These helpers are build-time only. Runtime field lookups use field_meta.py and
never load the editor reference, its stock-object profiles, or external code.
"""

from __future__ import annotations

import ast
import base64
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import zlib

from .safe_output import SafeWriteStatus, write_text_safely


TABLE_NAMES = (
    "GENERATED_FIELD_LABELS",
    "FIELD_TYPES",
    "GENERATED_FIELD_APPLICABILITY",
    "GENERATED_FIELD_BOUNDS",
    "GENERATED_FIELD_CONSTANTS",
)
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){3}\Z")
_REFERENCE_CATEGORIES = frozenset({"ability", "unit", "item"})


class MetadataInputError(ValueError):
    """An input cannot establish a complete, unambiguous generation."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MetadataInputError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> Any:
    raise MetadataInputError(f"non-finite JSON constant: {value}")


def decode_json(raw: bytes, origin: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
        )
    except (UnicodeError, ValueError) as exc:
        raise MetadataInputError(f"{origin}: {exc}") from exc
    if not isinstance(value, dict):
        raise MetadataInputError(f"{origin}: expected a JSON object")
    return value


def _hashes(value: object, origin: str) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise MetadataInputError(f"{origin}: missing source hashes")
    for key, digest in value.items():
        if not isinstance(key, str) or not key or not isinstance(digest, str):
            raise MetadataInputError(f"{origin}: invalid source hash entry")
        if not _HASH.fullmatch(digest):
            raise MetadataInputError(f"{origin}: invalid SHA-256 for {key!r}")
    return dict(value)


def validate_metadata(
    value: object, origin: str
) -> dict[str, dict[str, dict[str, str]]]:
    if not isinstance(value, dict) or set(value) != _REFERENCE_CATEGORIES:
        raise MetadataInputError(f"{origin}: requires ability, unit and item metadata")
    for category, rows in value.items():
        if not isinstance(rows, dict) or not rows:
            raise MetadataInputError(f"{origin}: empty metadata category {category!r}")
        for code, row in rows.items():
            if not isinstance(code, str) or not code or not isinstance(row, dict):
                raise MetadataInputError(f"{origin}: invalid metadata record {code!r}")
            if any(
                not isinstance(k, str) or not isinstance(v, str) for k, v in row.items()
            ):
                raise MetadataInputError(
                    f"{origin}: non-string metadata {category}/{code}"
                )
            if not row.get("type") or not reference_label(row)[0]:
                raise MetadataInputError(
                    f"{origin}: missing label/type for {category}/{code}"
                )
    return value


def reference_label(row: dict[str, str]) -> tuple[str, str]:
    """Retain a real localized label; an unresolved WESTRING key is not a label."""
    for language in ("zhCN", "enUS"):
        label = row.get(language, "")
        if label and not label.upper().startswith("WESTRING_"):
            return label, language
    return "", ""


def reference_from_source(path: Path) -> dict[str, Any]:
    """Decode the sole literal _DATA assignment without importing its module."""
    raw = path.read_bytes()
    try:
        tree = ast.parse(raw.decode("utf-8-sig"), filename=path.name)
    except (UnicodeError, SyntaxError) as exc:
        raise MetadataInputError(f"{path.name}: invalid source: {exc}") from exc
    assignments = [
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_DATA"
            for target in node.targets
        )
    ]
    if len(assignments) != 1 or not isinstance(assignments[0], ast.Constant):
        raise MetadataInputError(f"{path.name}: requires one literal _DATA assignment")
    encoded = assignments[0].value
    if not isinstance(encoded, str) or not encoded:
        raise MetadataInputError(
            f"{path.name}: _DATA must be a nonempty literal string"
        )
    try:
        compressed = base64.b85decode(encoded)
        decoder = zlib.decompressobj()
        decoded = decoder.decompress(compressed) + decoder.flush()
    except (ValueError, zlib.error) as exc:
        raise MetadataInputError(
            f"{path.name}: invalid compressed literal: {exc}"
        ) from exc
    if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise MetadataInputError(f"{path.name}: incomplete or trailing compressed data")
    payload = decode_json(decoded, path.name)
    if type(payload.get("schema")) is not int or payload["schema"] != 1:
        raise MetadataInputError(f"{path.name}: unsupported reference schema")
    version = payload.get("game_build")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise MetadataInputError(f"{path.name}: missing four-part game_build")
    metadata = validate_metadata(payload.get("metadata"), path.name)
    return {
        "schema": 1,
        "kind": "warcraft-editor-field-metadata",
        "game_build": version,
        "scope": "versioned editor metadata; not current-game object values",
        "origin": {
            "module": path.name,
            "module_sha256": sha256(raw),
            "compressed_literal_sha256": sha256(compressed),
            "decoded_payload_sha256": sha256(decoded),
            "method": "AST literal _DATA; Base85; zlib; JSON; no source execution",
        },
        "source_hashes": _hashes(payload.get("sources"), path.name),
        "record_counts": {category: len(rows) for category, rows in metadata.items()},
        "metadata_sha256": sha256(canonical_json(metadata).encode("utf-8")),
        "metadata": metadata,
    }


def read_reference(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    data = decode_json(raw, path.name)
    if (
        type(data.get("schema")) is not int
        or data["schema"] != 1
        or data.get("kind") != "warcraft-editor-field-metadata"
    ):
        raise MetadataInputError(f"{path.name}: unsupported reference schema/kind")
    version = data.get("game_build")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise MetadataInputError(f"{path.name}: invalid game_build")
    metadata = validate_metadata(data.get("metadata"), path.name)
    counts = {category: len(rows) for category, rows in metadata.items()}
    if data.get("record_counts") != counts or any(
        type(count) is not int for count in data.get("record_counts", {}).values()
    ):
        raise MetadataInputError(f"{path.name}: metadata record counts do not match")
    if data.get("metadata_sha256") != sha256(canonical_json(metadata).encode("utf-8")):
        raise MetadataInputError(f"{path.name}: metadata SHA-256 does not match")
    _hashes(data.get("source_hashes"), path.name)
    origin = data.get("origin")
    if not isinstance(origin, dict) or not origin.get("module"):
        raise MetadataInputError(f"{path.name}: missing module origin")
    _hashes(
        {
            key: origin.get(key)
            for key in (
                "module_sha256",
                "compressed_literal_sha256",
                "decoded_payload_sha256",
            )
        },
        path.name,
    )
    return data, raw


@dataclass
class Generation:
    tables: dict[str, dict[str, Any]]
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    provenance: dict[str, dict[str, str]] = field(default_factory=dict)
    retained_differences: dict[str, dict[str, Any]] = field(default_factory=dict)
    found: int = 0
    unresolved: int = 0

    def legacy_tuple(self):
        return (
            *(self.tables[name] for name in TABLE_NAMES),
            self.found,
            self.unresolved,
        )

    def fill(self, table: str, code: str, value: Any, source: str) -> None:
        target = self.tables[table]
        if code not in target:
            target[code] = value
            self.provenance.setdefault(code, {})[table] = source
        elif target[code] != value:
            # Every version difference stays reviewable, including bounds and
            # applicability. Preserving the seed never erases the new evidence.
            self.retained_differences.setdefault(source, {}).setdefault(table, {})[
                code
            ] = value


def load_seed(path: Path) -> Generation:
    raw = path.read_bytes()
    data = decode_json(raw, path.name)
    if (
        type(data.get("schema")) is not int
        or data["schema"] != 1
        or not isinstance(data.get("tables"), dict)
        or set(data["tables"]) != set(TABLE_NAMES)
    ):
        raise MetadataInputError(f"{path.name}: incomplete seed tables")
    if data.get("tables_sha256") != sha256(
        canonical_json(data["tables"]).encode("utf-8")
    ):
        raise MetadataInputError(f"{path.name}: seed tables SHA-256 does not match")
    tables: dict[str, dict[str, Any]] = {}
    for name in TABLE_NAMES:
        values = data["tables"][name]
        if not isinstance(values, dict) or not values:
            raise MetadataInputError(f"{path.name}: empty seed {name}")
        tables[name] = {}
        for code, value in values.items():
            if not isinstance(code, str) or not code:
                raise MetadataInputError(f"{path.name}: invalid seed field code")
            if name == "GENERATED_FIELD_APPLICABILITY":
                valid = (
                    isinstance(value, list)
                    and len(value) == 2
                    and all(
                        isinstance(part, list)
                        and all(isinstance(k, str) and k for k in part)
                        for part in value
                    )
                )
                if valid:
                    value = tuple(tuple(part) for part in value)
            elif name == "GENERATED_FIELD_BOUNDS":
                valid = (
                    isinstance(value, list)
                    and len(value) == 2
                    and all(part is None or isinstance(part, str) for part in value)
                )
                if valid:
                    value = tuple(value)
            else:
                valid = isinstance(value, str) and bool(value)
            if not valid:
                raise MetadataInputError(f"{path.name}: invalid {name}/{code}")
            tables[name][code] = value
    return Generation(
        tables,
        {
            "seed": {
                "file": path.name,
                "sha256": sha256(raw),
                "origin": data.get("origin", {}),
                "counts": {name: len(values) for name, values in tables.items()},
            }
        },
    )


def merge_reference(result: Generation, path: Path) -> None:
    data, raw = read_reference(path)
    source = f"editor-reference:{data['game_build']}"
    result.sources[source] = {
        "file": path.name,
        "sha256": sha256(raw),
        "game_build": data["game_build"],
        "origin": data["origin"],
        "record_counts": data["record_counts"],
        "source_hashes": data["source_hashes"],
        "policy": "fill missing metadata; preserve existing values; no stock object values",
    }
    candidates: dict[tuple[str, str], tuple[Any, str]] = {}
    for category, rows in sorted(data["metadata"].items()):
        for code, row in sorted(rows.items()):
            result.found += 1
            label, language = reference_label(row)
            values: dict[str, Any] = {
                "GENERATED_FIELD_LABELS": label,
                "FIELD_TYPES": row["type"],
            }
            use = split_codes(row.get("useSpecific", ""))
            avoid = split_codes(row.get("notSpecific", ""))
            if use or avoid:
                values["GENERATED_FIELD_APPLICABILITY"] = (use, avoid)
            lo, hi = row.get("minVal") or None, row.get("maxVal") or None
            if lo is not None or hi is not None:
                values["GENERATED_FIELD_BOUNDS"] = (lo, hi)
            for table, value in values.items():
                identity = (table, code)
                prior = candidates.get(identity)
                if prior is not None and prior[0] != value:
                    raise MetadataInputError(
                        f"{path.name}: ambiguous {table}/{code}: {prior[1]} vs {category}"
                    )
                candidates[identity] = (value, category)
                suffix = f":{language}" if table == "GENERATED_FIELD_LABELS" else ""
                result.fill(table, code, value, f"{source}:{category}{suffix}")


def split_codes(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def publish_text(path: Path, text: str) -> None:
    """Publish complete generated text through the repository's safe writer."""
    target = path.absolute()
    result = write_text_safely(str(target.parent), target.name, text)
    if result.status != SafeWriteStatus.WRITTEN:
        raise OSError(f"{target}: {result.status}: {result.error}")
