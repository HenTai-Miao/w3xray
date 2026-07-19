"""Immutable manifest schema for archived integrity reports."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
from typing import Final, override

from .integrity_utf8 import IntegrityUtf8Error, require_utf8_text


INTEGRITY_HISTORY_ROOT_NAME: Final = ".w3xray-integrity-history"
INTEGRITY_HISTORY_SCHEMA: Final = 1
INTEGRITY_HISTORY_MANIFEST_NAME: Final = "历史清单.json"
INTEGRITY_HISTORY_REPORT_NAME: Final = "report.json"

_DIGEST: Final = re.compile(r"[0-9a-f]{64}")
_GENERATION_ID: Final = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True, slots=True)
class IntegrityHistoryArtifact:
    """One immutable report payload bound by size and SHA-256."""

    name: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class IntegrityHistoryManifest:
    """Closed inventory for one archived public integrity report."""

    schema: int
    generation_id: str
    destination_name: str
    artifacts: tuple[IntegrityHistoryArtifact, ...]


class IntegrityHistoryError(OSError):
    """An integrity-report history object violated its closed contract."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    @override
    def __str__(self) -> str:
        return self.detail


def format_integrity_history_manifest(manifest: IntegrityHistoryManifest) -> str:
    """Serialize one exact, validated history inventory."""
    _require_manifest(manifest)
    value = {
        "artifact_count": len(manifest.artifacts),
        "artifacts": [
            {"name": item.name, "sha256": item.sha256, "size": item.size}
            for item in manifest.artifacts
        ],
        "destination_name": manifest.destination_name,
        "generation_id": manifest.generation_id,
        "schema": manifest.schema,
    }
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _require_manifest(manifest: IntegrityHistoryManifest) -> None:
    if manifest.schema != INTEGRITY_HISTORY_SCHEMA:
        raise IntegrityHistoryError("unsupported integrity history schema")
    if _GENERATION_ID.fullmatch(manifest.generation_id) is None:
        raise IntegrityHistoryError("invalid integrity history generation ID")
    try:
        require_utf8_text(manifest.destination_name, "history destination name")
    except IntegrityUtf8Error as exc:
        raise IntegrityHistoryError(str(exc)) from exc
    if (
        not manifest.destination_name
        or manifest.destination_name in {".", ".."}
        or os.sep in manifest.destination_name
        or (os.altsep is not None and os.altsep in manifest.destination_name)
    ):
        raise IntegrityHistoryError("history destination must be one safe leaf")
    if len(manifest.artifacts) != 1:
        raise IntegrityHistoryError(
            "integrity history inventory must contain one report"
        )
    artifact = manifest.artifacts[0]
    if (
        artifact.name != INTEGRITY_HISTORY_REPORT_NAME
        or artifact.size < 0
        or _DIGEST.fullmatch(artifact.sha256) is None
    ):
        raise IntegrityHistoryError("invalid integrity history artifact")


__all__ = (
    "INTEGRITY_HISTORY_MANIFEST_NAME",
    "INTEGRITY_HISTORY_REPORT_NAME",
    "INTEGRITY_HISTORY_ROOT_NAME",
    "INTEGRITY_HISTORY_SCHEMA",
    "IntegrityHistoryArtifact",
    "IntegrityHistoryError",
    "IntegrityHistoryManifest",
    "format_integrity_history_manifest",
)
