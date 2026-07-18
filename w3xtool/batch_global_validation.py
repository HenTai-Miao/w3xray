"""Content and schema validation for immutable global generations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Final

from .batch_global_evidence import collect_global_evidence
from .batch_global_evidence_models import GlobalEvidenceIndex
from .batch_global_evidence_reports import (
    format_axis_status_tsv,
    format_global_icon_gaps_tsv,
    format_icon_candidates_tsv,
    format_icon_gap_statistics,
    parse_global_icon_gaps_tsv,
    parse_icon_candidates_tsv,
)
from .batch_global_io import parse_global_manifest
from .batch_global_models import (
    GLOBAL_MANIFEST_NAME,
    GLOBAL_PAYLOAD_NAMES,
    GlobalFormatError,
    GlobalGeneration,
)
from .batch_reports import (
    format_batch_state_json,
    format_batch_summary_tsv,
    format_retry_tsv,
    parse_batch_state_json,
)
from .bounded_file import read_bounded_regular_file, sha256_regular_file
from .description_cache import (
    format_description_cache_tsv,
    load_description_cache_text,
)


_MAX_MANIFEST_BYTES: Final = 4 * 1024 * 1024
_MAX_PAYLOAD_BYTES: Final = 512 * 1024 * 1024
_SUMMARY_NAME: Final = "批量提取汇总.tsv"
_STATE_NAME: Final = "批量提取状态.json"
_RETRY_NAME: Final = "失败与重试.tsv"
_CACHE_NAME: Final = "可信描述缓存.tsv"
_DIAGNOSTICS_NAME: Final = "批量诊断.jsonl"
_GAPS_NAME: Final = "图标缺口汇总.tsv"
_CANDIDATES_NAME: Final = "图标候选绑定.tsv"
_STATISTICS_NAME: Final = "图标缺口统计.txt"
_AXES_NAME: Final = "三轴状态汇总.tsv"


def validate_global_generation(
    directory: Path,
    expected_manifest_sha256: str | None = None,
) -> GlobalGeneration | None:
    """Validate the exact file set, hashes, schemas, and report reconciliation."""
    if directory.is_symlink() or not directory.is_dir():
        return None
    try:
        manifest_bytes, _identity = read_bounded_regular_file(
            directory / GLOBAL_MANIFEST_NAME,
            _MAX_MANIFEST_BYTES,
        )
        manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
        if (
            expected_manifest_sha256 is not None
            and manifest_digest != expected_manifest_sha256
        ):
            return None
        manifest = parse_global_manifest(manifest_bytes.decode("utf-8"))
        if manifest.generation_id != directory.name:
            return None
        if not _has_exact_files(directory):
            return None
        artifact_by_name = {item.name: item for item in manifest.artifacts}
        payloads: dict[str, str] = {}
        for name in GLOBAL_PAYLOAD_NAMES:
            artifact = artifact_by_name[name]
            if artifact.size > _MAX_PAYLOAD_BYTES:
                return None
            digest, identity = sha256_regular_file(
                directory / name,
                _MAX_PAYLOAD_BYTES,
            )
            if identity.size != artifact.size or digest != artifact.sha256:
                return None
            payload, _read_identity = read_bounded_regular_file(
                directory / name,
                _MAX_PAYLOAD_BYTES,
                expected=identity,
            )
            payloads[name] = payload.decode("utf-8")
        state = parse_batch_state_json(payloads[_STATE_NAME])
        if format_batch_state_json(state) != payloads[_STATE_NAME]:
            return None
        if format_batch_summary_tsv(state) != payloads[_SUMMARY_NAME]:
            return None
        if format_retry_tsv(state) != payloads[_RETRY_NAME]:
            return None
        cache = load_description_cache_text(
            payloads[_CACHE_NAME],
            str(directory / _CACHE_NAME),
        )
        if (
            cache.diagnostics
            or format_description_cache_tsv(cache) != payloads[_CACHE_NAME]
        ):
            return None
        _validate_json_lines(payloads[_DIAGNOSTICS_NAME])
        parsed_gaps = parse_global_icon_gaps_tsv(payloads[_GAPS_NAME])
        parsed_candidates = parse_icon_candidates_tsv(payloads[_CANDIDATES_NAME])
        fresh = collect_global_evidence(directory.parents[2], state)
        evidence = GlobalEvidenceIndex.build(
            parsed_gaps,
            fresh.resolved,
            fresh.anonymous,
            parsed_candidates,
        )
        if evidence != fresh:
            return None
        if (
            len(evidence.gaps)
            != sum(result.unresolved_icon_count for result in state.results)
            or sum(row.reference_count for row in evidence.gaps)
            != sum(result.unresolved_icon_reference_count for result in state.results)
            or format_global_icon_gaps_tsv(evidence) != payloads[_GAPS_NAME]
            or format_icon_candidates_tsv(evidence) != payloads[_CANDIDATES_NAME]
            or format_icon_gap_statistics(evidence, state) != payloads[_STATISTICS_NAME]
            or format_axis_status_tsv(state) != payloads[_AXES_NAME]
        ):
            return None
        return GlobalGeneration(
            manifest.generation_id,
            directory,
            manifest_digest,
            state,
            payloads[_CACHE_NAME],
            payloads[_DIAGNOSTICS_NAME],
            evidence,
        )
    except OSError, UnicodeError, ValueError, GlobalFormatError:
        return None


def _has_exact_files(directory: Path) -> bool:
    expected = {*GLOBAL_PAYLOAD_NAMES, GLOBAL_MANIFEST_NAME}
    actual: set[str] = set()
    for path in directory.iterdir():
        if path.is_symlink() or not path.is_file() or path.name in actual:
            return False
        actual.add(path.name)
    return actual == expected


def _validate_json_lines(text: str) -> None:
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GlobalFormatError(
                f"invalid diagnostics JSON at line {line_number}: {exc.msg}"
            ) from exc
        if not isinstance(value, dict):
            raise GlobalFormatError(f"diagnostics line {line_number} must be an object")
