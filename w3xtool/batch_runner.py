"""Sequential, resumable orchestration for map extraction batches."""

from __future__ import annotations

import struct
from dataclasses import replace
import hashlib
from pathlib import Path

from .batch_checkpoint_publication import publish_batch_checkpoint
from .batch_configuration import (
    DEFAULT_BATCH_OUTPUT as DEFAULT_BATCH_OUTPUT,
    BatchConfigurationError,
    BatchOptions,
    BatchOutputError,
    normalize_batch_options,
    validate_batch_roots,
)
from .batch_dependencies import fingerprint_dependencies
from .batch_description_cache import build_and_publish_description_cache
from .batch_manifest_models import (
    OWNERSHIP_MARKER_NAME as OWNERSHIP_MARKER,
    REQUIRED_MAP_REPORTS,
)
from .batch_map_publication import recover_map_publications
from .batch_models import BatchState, MapBatchResult, MapBatchState, SourceFingerprint
from .batch_resume import (
    ResumeDiagnostic,
    checkpoint_state,
    find_reusable_result,
    format_resume_diagnostics_jsonl,
    load_previous_state,
)
from .bounded_file import BoundedFileError, sha256_regular_file
from .description_cache import format_description_cache_tsv
from .load_context import MapLoadContext, build_map_load_context
from .map_directory import scan_map_sources

__all__ = (
    "DEFAULT_BATCH_OUTPUT",
    "OWNERSHIP_MARKER",
    "REQUIRED_MAP_REPORTS",
    "BatchConfigurationError",
    "BatchOptions",
    "BatchOutputError",
    "fingerprint_source",
    "process_one_map",
    "run_batch",
)


def run_batch(options: BatchOptions) -> BatchState:
    """Process sources sequentially and persist progress after every map."""
    normalized = normalize_batch_options(options)
    validate_batch_roots(normalized)
    recovery = recover_map_publications(normalized.output_root)
    previous = load_previous_state(normalized.output_root)
    cache = build_and_publish_description_cache(normalized.output_root)
    cache_text = format_description_cache_tsv(cache)
    cache_sha256 = hashlib.sha256(cache_text.encode("utf-8")).hexdigest()
    context = replace(
        build_map_load_context(game_data_path=normalized.game_data_path),
        description_cache=cache,
    )
    paths = tuple(scan_map_sources(normalized.source_directory))
    results: list[MapBatchResult] = []
    diagnostics = list(previous.diagnostics)
    diagnostics.extend(
        ResumeDiagnostic(
            f"recovery_{item.code}",
            item.detail,
            item.transaction_id,
        )
        for item in recovery
    )
    for offset, path in enumerate(paths):
        index = offset + 1
        try:
            fingerprint = fingerprint_source(path)
        except (OSError, ValueError) as exc:
            result = _failed_without_fingerprint(path, exc)
            diagnostics.append(
                ResumeDiagnostic("source_fingerprint_failed", str(exc), path)
            )
        else:
            decision = find_reusable_result(
                previous,
                fingerprint,
                "",
                normalized.output_root,
                retry_failed=normalized.retry_failed,
            )
            if decision.result is not None:
                result = decision.result
            else:
                try:
                    dependency = fingerprint_dependencies(
                        fingerprint,
                        normalized,
                        cache_sha256,
                    )
                except (OSError, ValueError, KeyError, IndexError, struct.error) as exc:
                    result = _failed_result(fingerprint, exc)
                else:
                    decision = find_reusable_result(
                        previous,
                        fingerprint,
                        dependency,
                        normalized.output_root,
                        retry_failed=normalized.retry_failed,
                    )
                    if decision.result is not None:
                        result = decision.result
                    else:
                        try:
                            result = process_one_map(
                                index,
                                fingerprint,
                                normalized,
                                context,
                            )
                        except (
                            OSError,
                            ValueError,
                            KeyError,
                            IndexError,
                            struct.error,
                        ) as exc:
                            result = _failed_result(fingerprint, exc)
            diagnostics.append(
                ResumeDiagnostic(
                    decision.code,
                    decision.detail,
                    fingerprint.path,
                )
            )
        results.append(result)
        state = checkpoint_state(
            tuple(results),
            previous,
            paths[offset + 1 :],
        )
        publish_batch_checkpoint(
            normalized.output_root,
            state,
            cache_text,
            format_resume_diagnostics_jsonl(tuple(diagnostics)),
        )
    state = checkpoint_state(tuple(results), previous, ())
    if not results:
        publish_batch_checkpoint(
            normalized.output_root,
            state,
            cache_text,
            format_resume_diagnostics_jsonl(tuple(diagnostics)),
        )
    return state


def process_one_map(
    index: int,
    fingerprint: SourceFingerprint,
    options: BatchOptions,
    context: MapLoadContext,
) -> MapBatchResult:
    """Load the focused single-map processor without coupling scan tests to it."""
    from .batch_map_processing import process_one_map as process

    return process(index, fingerprint, options, context)


def fingerprint_source(path: str) -> SourceFingerprint:
    """Hash one stable regular source and capture its resume identity."""
    source = Path(path)
    before = source.stat(follow_symlinks=False)
    digest, identity = sha256_regular_file(source)
    after = source.stat(follow_symlinks=False)
    if (after.st_dev, after.st_ino, after.st_size) != (
        identity.device,
        identity.inode,
        identity.size,
    ) or before.st_mtime_ns != after.st_mtime_ns:
        raise BoundedFileError(source, "file identity changed while hashing")
    return SourceFingerprint(str(source), identity.size, after.st_mtime_ns, digest)


def _failed_result(
    fingerprint: SourceFingerprint, exc: BaseException
) -> MapBatchResult:
    return MapBatchResult(
        source=fingerprint,
        display_name=Path(fingerprint.path).stem,
        output_directory="",
        stage="load/process",
        state=MapBatchState.FAILED,
        first_error=f"{type(exc).__name__}: {exc}".replace("\n", " "),
        object_count=0,
        description_counts=(),
        named_icon_count=0,
        anonymous_icon_count=0,
        original_written_count=0,
        png_written_count=0,
        icon_failure_count=0,
        restricted_block_count=0,
        elapsed_ms=0,
    )


def _failed_without_fingerprint(path: str, exc: BaseException) -> MapBatchResult:
    fingerprint = SourceFingerprint(path, 0, 0, "0" * 64)
    return _failed_result(fingerprint, exc)
