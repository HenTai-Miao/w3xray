"""Sequential, resumable orchestration for map extraction batches."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import hashlib
from pathlib import Path
from time import monotonic_ns

from .batch_checkpoint_publication import publish_batch_checkpoint
from .batch_configuration import (
    DEFAULT_BATCH_OUTPUT as DEFAULT_BATCH_OUTPUT,
    BatchConfigurationError,
    BatchOptions,
    BatchOutputError,
    normalize_batch_options,
    validate_batch_roots,
)
from .batch_description_cache import build_and_publish_description_cache
from .batch_execution import CancellationSignal
from .batch_manifest_models import (
    OWNERSHIP_MARKER_NAME as OWNERSHIP_MARKER,
    REQUIRED_MAP_REPORTS,
)
from .batch_map_publication import recover_map_publications
from .batch_map_attempt import attempt_map, failed_unfingerprinted
from .batch_models import BatchState, MapBatchResult, SourceFingerprint
from .batch_observability import observe_attempt, startup_diagnostics
from .batch_resume import (
    checkpoint_state,
    load_previous_state,
)
from .batch_runtime import (
    BatchAction,
    BatchProgress,
    build_batch_progress,
    format_batch_diagnostics_jsonl,
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


def run_batch(
    options: BatchOptions,
    *,
    cancellation: CancellationSignal | None = None,
    on_progress: Callable[[BatchProgress], None] | None = None,
) -> BatchState:
    """Process sources sequentially and persist progress after every map."""
    started_ns = monotonic_ns()
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
    diagnostics = list(startup_diagnostics(previous.diagnostics, recovery, len(paths)))
    if on_progress is not None:
        on_progress(
            build_batch_progress(
                completed=0,
                total=len(paths),
                source_path="",
                action=BatchAction.STARTING,
                started_ns=started_ns,
                now_ns=monotonic_ns(),
                peak_rss_bytes=0,
                published_bytes=0,
                diagnostic_code="started",
            )
        )
    for offset, path in enumerate(paths):
        index = offset + 1
        try:
            fingerprint = fingerprint_source(path)
        except (OSError, ValueError) as exc:
            attempt = failed_unfingerprinted(
                path,
                f"{type(exc).__name__}: {exc}",
            )
        else:
            attempt = attempt_map(
                index,
                fingerprint,
                normalized,
                context,
                previous,
                cache_sha256,
                cancellation,
                process_one_map,
            )
        result = attempt.result
        results.append(attempt.result)
        progress, diagnostic = observe_attempt(
            attempt,
            result,
            sequence=len(diagnostics) + 1,
            completed=index,
            total=len(paths),
            source_path=path,
            started_ns=started_ns,
            now_ns=monotonic_ns(),
        )
        diagnostics.append(diagnostic)
        state = checkpoint_state(
            tuple(results),
            previous,
            paths[offset + 1 :],
        )
        publish_batch_checkpoint(
            normalized.output_root,
            state,
            cache_text,
            format_batch_diagnostics_jsonl(tuple(diagnostics)),
        )
        if on_progress is not None:
            on_progress(progress)
        if attempt.stop_batch:
            return state
    state = checkpoint_state(tuple(results), previous, ())
    if not results:
        publish_batch_checkpoint(
            normalized.output_root,
            state,
            cache_text,
            format_batch_diagnostics_jsonl(tuple(diagnostics)),
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
