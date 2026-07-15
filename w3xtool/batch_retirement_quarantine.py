"""Descriptor-anchored quarantine and deletion for one retired publication."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
from typing import Final
from uuid import uuid4

from .batch_global_models import GlobalGeneration
from .batch_global_publication import load_current_generation
from .batch_manifest_validation import verify_map_publication
from .batch_models import BatchState
from .batch_output_lock import BatchOutputLease, lease_is_current
from .durable_io import sync_directory_descriptor


_RMTREE_IS_ANCHORED: Final = shutil.rmtree.avoids_symlink_attacks


def open_maps_root(maps_root: Path) -> int | None:
    """Open one no-follow directory anchor and verify its pathname identity."""
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(maps_root, flags)
    except OSError:
        return None
    if _maps_root_is_current(maps_root, descriptor):
        return descriptor
    os.close(descriptor)
    return None


def retire_isolated_candidate(
    output: Path,
    maps_root: Path,
    maps_descriptor: int,
    candidate: Path,
    expected: os.stat_result,
    manifest_sha256: str,
    generation: GlobalGeneration,
    expected_state: BatchState,
    lease: BatchOutputLease,
) -> bool:
    """Delete only the exact candidate after private isolation and revalidation."""
    if not _supports_anchored_retirement() or not _maps_root_is_current(
        maps_root,
        maps_descriptor,
    ):
        return False
    quarantine = maps_root / f".w3xray-map-retirement-{uuid4().hex}"
    try:
        isolated = _isolate_candidate(
            maps_root,
            maps_descriptor,
            candidate,
            quarantine,
            expected,
        )
    except OSError:
        return False
    if not isolated:
        _restore_candidate(maps_descriptor, candidate, quarantine, expected)
        return False
    if not _isolated_candidate_is_safe(
        output,
        maps_root,
        maps_descriptor,
        quarantine,
        expected,
        manifest_sha256,
        generation,
        expected_state,
        lease,
    ):
        _restore_candidate(maps_descriptor, candidate, quarantine, expected)
        return False
    try:
        shutil.rmtree(quarantine.name, dir_fd=maps_descriptor)
        sync_directory_descriptor(maps_descriptor)
    except OSError:
        _restore_candidate(maps_descriptor, candidate, quarantine, expected)
        return False
    return True


def _isolate_candidate(
    maps_root: Path,
    maps_descriptor: int,
    candidate: Path,
    quarantine: Path,
    expected: os.stat_result,
) -> bool:
    if not _maps_root_is_current(maps_root, maps_descriptor):
        return False
    try:
        anchored = os.stat(
            candidate.name,
            dir_fd=maps_descriptor,
            follow_symlinks=False,
        )
    except OSError:
        return False
    if not _anchored_name_is_available(maps_descriptor, quarantine.name):
        return False
    if not _same_directory(anchored, expected):
        return False
    os.rename(
        candidate.name,
        quarantine.name,
        src_dir_fd=maps_descriptor,
        dst_dir_fd=maps_descriptor,
    )
    sync_directory_descriptor(maps_descriptor)
    try:
        isolated = os.stat(
            quarantine.name,
            dir_fd=maps_descriptor,
            follow_symlinks=False,
        )
    except OSError:
        return False
    return _same_directory(isolated, expected)


def _isolated_candidate_is_safe(
    output: Path,
    maps_root: Path,
    maps_descriptor: int,
    quarantine: Path,
    expected: os.stat_result,
    manifest_sha256: str,
    generation: GlobalGeneration,
    expected_state: BatchState,
    lease: BatchOutputLease,
) -> bool:
    if (
        not lease_is_current(lease, output)
        or not _maps_root_is_current(maps_root, maps_descriptor)
        or not _same_generation(output, generation, expected_state)
    ):
        return False
    validation = verify_map_publication(quarantine)
    if not validation.valid or validation.manifest_sha256 != manifest_sha256:
        return False
    try:
        after = os.stat(
            quarantine.name,
            dir_fd=maps_descriptor,
            follow_symlinks=False,
        )
    except OSError:
        return False
    return bool(
        _same_directory(after, expected)
        and lease_is_current(lease, output)
        and _maps_root_is_current(maps_root, maps_descriptor)
        and _same_generation(output, generation, expected_state)
    )


def _restore_candidate(
    maps_descriptor: int,
    candidate: Path,
    quarantine: Path,
    expected: os.stat_result,
) -> None:
    try:
        isolated = os.stat(
            quarantine.name,
            dir_fd=maps_descriptor,
            follow_symlinks=False,
        )
    except OSError:
        return
    if not _same_directory(isolated, expected):
        return
    if not _anchored_name_is_available(maps_descriptor, candidate.name):
        return
    try:
        os.rename(
            quarantine.name,
            candidate.name,
            src_dir_fd=maps_descriptor,
            dst_dir_fd=maps_descriptor,
        )
        sync_directory_descriptor(maps_descriptor)
    except OSError:
        return


def _maps_root_is_current(maps_root: Path, descriptor: int) -> bool:
    try:
        path_status = os.lstat(maps_root)
        open_status = os.fstat(descriptor)
    except OSError:
        return False
    return _same_directory(path_status, open_status)


def _anchored_name_is_available(descriptor: int, name: str) -> bool:
    try:
        _ = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


def _same_directory(first: os.stat_result, second: os.stat_result) -> bool:
    return bool(
        stat.S_ISDIR(first.st_mode)
        and stat.S_ISDIR(second.st_mode)
        and (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)
    )


def _same_generation(
    output: Path,
    expected: GlobalGeneration,
    expected_state: BatchState,
) -> bool:
    current = load_current_generation(output)
    return bool(
        current is not None
        and current.generation_id == expected.generation_id
        and current.manifest_sha256 == expected.manifest_sha256
        and current.state == expected_state
    )


def _supports_anchored_retirement() -> bool:
    return bool(
        _RMTREE_IS_ANCHORED
        and os.rename in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
    )


__all__ = ("open_maps_root", "retire_isolated_candidate")
