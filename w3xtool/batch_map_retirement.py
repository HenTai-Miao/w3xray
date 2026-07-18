"""Safe retirement of superseded, strictly owned map publications."""

from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import assert_never
from unicodedata import normalize

from .batch_global_publication import load_current_generation
from .batch_global_models import GlobalGeneration
from .batch_manifest_validation import verify_map_publication
from .batch_models import BatchState
from .batch_output_lock import (
    BatchOutputLease,
    hold_batch_output_lock,
    lease_is_current,
)
from .batch_status import PublicationResult
from .batch_retirement_quarantine import (
    open_maps_root,
    retire_isolated_candidate,
)
from .safe_output import safe_relative_path


def retire_superseded_map_publications(
    output_root: str,
    expected_state: BatchState,
    lease: BatchOutputLease | None = None,
) -> tuple[str, ...]:
    """Remove only valid same-source directories outside the final authority."""
    if lease is None:
        with hold_batch_output_lock(output_root) as owned:
            return _retire_superseded_map_publications_locked(
                output_root,
                expected_state,
                owned,
            )
    return _retire_superseded_map_publications_locked(
        output_root,
        expected_state,
        lease,
    )


def _retire_superseded_map_publications_locked(
    output_root: str,
    expected_state: BatchState,
    lease: BatchOutputLease,
) -> tuple[str, ...]:
    """Retire candidates while the exact output lease is held."""
    if not lease_is_current(lease, output_root):
        return ()
    generation = load_current_generation(output_root)
    if generation is None or generation.state != expected_state:
        return ()
    output = Path(output_root)
    maps_root = output / "地图"
    if output.is_symlink() or maps_root.is_symlink() or not maps_root.is_dir():
        return ()
    maps_descriptor = open_maps_root(maps_root)
    if maps_descriptor is None:
        return ()
    try:
        return _retire_from_maps_root(
            output,
            maps_root,
            maps_descriptor,
            generation,
            expected_state,
            lease,
        )
    finally:
        os.close(maps_descriptor)


def _retire_from_maps_root(
    output: Path,
    maps_root: Path,
    maps_descriptor: int,
    generation: GlobalGeneration,
    expected_state: BatchState,
    lease: BatchOutputLease,
) -> tuple[str, ...]:
    """Validate, isolate, revalidate, and delete through one directory anchor."""
    authority = _authority(expected_state, maps_root)
    if authority is None:
        return ()
    referenced, source_digests = authority
    retired: list[str] = []
    for candidate in sorted(maps_root.iterdir(), key=lambda path: _key(path.name)):
        if (
            candidate.name.startswith(".")
            or _key(candidate.name) in referenced
            or candidate.is_symlink()
            or not candidate.is_dir()
        ):
            continue
        before = candidate.stat(follow_symlinks=False)
        validation = verify_map_publication(candidate)
        manifest = validation.manifest
        if (
            not validation.valid
            or manifest is None
            or manifest.source.sha256 not in source_digests
        ):
            continue
        after = candidate.stat(follow_symlinks=False)
        if (
            (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
            or not stat.S_ISDIR(after.st_mode)
            or candidate.is_symlink()
        ):
            continue
        if not retire_isolated_candidate(
            output,
            maps_root,
            maps_descriptor,
            candidate,
            after,
            validation.manifest_sha256,
            generation,
            expected_state,
            lease,
        ):
            continue
        retired.append(f"地图/{candidate.name}")
    return tuple(retired)


def _authority(
    state: BatchState,
    maps_root: Path,
) -> tuple[frozenset[str], frozenset[str]] | None:
    referenced: set[str] = set()
    source_digests: set[str] = set()
    for result in state.results:
        match result.publication_result:
            case PublicationResult.PUBLISHED:
                pass
            case PublicationResult.FAILED | PublicationResult.CANCELLED:
                return None
            case unreachable:
                assert_never(unreachable)
        relative = safe_relative_path(result.output_directory)
        if relative is None or len(relative.parts) != 2 or relative.parts[0] != "地图":
            return None
        current = maps_root / relative.name
        if current.is_symlink() or not current.is_dir():
            return None
        if not verify_map_publication(current, result).valid:
            return None
        referenced.add(_key(relative.name))
        source_digests.add(result.source.sha256)
    return frozenset(referenced), frozenset(source_digests)


def _key(name: str) -> str:
    return normalize("NFC", name).casefold()


__all__ = ("retire_superseded_map_publications",)
