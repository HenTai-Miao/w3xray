"""Real-MPQ publication acceptance and repeated-run soak coverage."""

from __future__ import annotations

import gc
import multiprocessing
from pathlib import Path
import shutil
import threading
import tracemalloc

from w3xtool.acceptance_batch import check_batch_publication
from w3xtool.batch_configuration import BatchOptions
from w3xtool.batch_global_publication import load_current_generation
from w3xtool.batch_manifest_validation import verify_map_publication
from w3xtool.batch_runner import fingerprint_source, run_batch
from w3xtool.batch_runtime import BatchAction, BatchProgress


_FIXTURE = (
    Path(__file__).parent / "fixtures" / "maps" / "war3net-map-script-builder.w3x"
)
_MEMORY_GROWTH_LIMIT = 16 * 1024 * 1024


def test_batch_publication_acceptance_reuses_manifest_and_preserves_fixture(
    tmp_path: Path,
) -> None:
    # Given
    before = fingerprint_source(str(_FIXTURE))

    # When
    detail = check_batch_publication(_FIXTURE, tmp_path)

    # Then
    after = fingerprint_source(str(_FIXTURE))
    assert after == before
    assert "second=reused" in detail
    assert f"source_sha256={before.sha256}" in detail
    assert "manifest_sha256=" in detail
    assert not _publication_leftovers(tmp_path / "batch-publication" / "output")


def test_five_run_soak_has_bounded_memory_and_no_worker_leaks(tmp_path: Path) -> None:
    # Given
    source_root = tmp_path / "Maps"
    source_root.mkdir()
    source = source_root / "sample.w3x"
    shutil.copyfile(_FIXTURE, source)
    output = tmp_path / "output"
    before = fingerprint_source(str(source))
    child_pids = _active_child_pids()
    worker_names = _worker_thread_names()
    actions: list[BatchAction] = []
    current_bytes: list[int] = []
    tracemalloc.start()

    # When
    try:
        for _run_number in range(5):
            progress: list[BatchProgress] = []
            state = run_batch(
                BatchOptions(
                    str(source_root),
                    str(output),
                    map_timeout_seconds=60,
                    minimum_free_bytes=0,
                ),
                on_progress=progress.append,
            )
            actions.append(progress[-1].action)
            assert len(state.results) == 1
            assert _active_child_pids() == child_pids
            assert _worker_thread_names() == worker_names
            gc.collect()
            current_bytes.append(tracemalloc.get_traced_memory()[0])
    finally:
        tracemalloc.stop()

    # Then
    assert actions == [BatchAction.PROCESSED, *([BatchAction.REUSED] * 4)]
    assert (
        max(current_bytes[1:], default=current_bytes[0]) - current_bytes[0]
        < _MEMORY_GROWTH_LIMIT
    )
    assert fingerprint_source(str(source)) == before
    generation = load_current_generation(output)
    assert generation is not None
    result = generation.state.results[0]
    assert verify_map_publication(output / result.output_directory, result).valid
    assert not _publication_leftovers(output)


def _active_child_pids() -> frozenset[int]:
    return frozenset(
        process.pid
        for process in multiprocessing.active_children()
        if process.pid is not None
    )


def _worker_thread_names() -> frozenset[str]:
    return frozenset(
        thread.name
        for thread in threading.enumerate()
        if thread.name.startswith("w3xray-")
    )


def _publication_leftovers(output: Path) -> tuple[Path, ...]:
    prefixes = (
        ".w3xray-backup-",
        ".w3xray-global-stage-",
        ".w3xray-map-backup-",
        ".w3xray-map-stage-",
        ".w3xray-map-transaction-",
        ".w3xray-stage-",
    )
    return tuple(
        path
        for path in output.rglob("*")
        if any(path.name.startswith(prefix) for prefix in prefixes)
    )
