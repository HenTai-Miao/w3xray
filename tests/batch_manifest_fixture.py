"""Minimal stage and publication fixtures shared by manifest contract tests."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from tests.batch_publication_fixture import empty_result, write_empty_publication
from w3xtool.batch_manifest_models import CONTENT_MANIFEST_NAME, OWNERSHIP_MARKER_NAME
from w3xtool.batch_map_manifest import finalize_map_manifest
from w3xtool.batch_models import MapBatchResult, SourceFingerprint


MANIFEST_TRANSACTION_ID: Final = "1" * 32
_FINGERPRINT: Final = SourceFingerprint("/maps/sample.w3x", 3, 4, "a" * 64)
_OUTPUT_DIRECTORY: Final = "地图/001_sample_aaaaaaaa"


def write_empty_manifest_stage(root: Path) -> MapBatchResult:
    """Write required empty reports without retaining their temporary metadata."""
    result = empty_result(_FINGERPRINT, _OUTPUT_DIRECTORY)
    _ = write_empty_publication(root, result, MANIFEST_TRANSACTION_ID)
    (root / CONTENT_MANIFEST_NAME).unlink()
    (root / OWNERSHIP_MARKER_NAME).unlink()
    return result


def publish_manifest_fixture(
    root: Path,
    result: MapBatchResult | None = None,
) -> MapBatchResult:
    """Finalize one existing stage with the supplied or canonical summary."""
    staged = write_empty_manifest_stage(root) if result is None else result
    return finalize_map_manifest(root, staged, MANIFEST_TRANSACTION_ID)
