"""Ownership and cleanup safety for current-map snapshots."""

from __future__ import annotations

from collections.abc import Iterator
import os
from pathlib import Path
import time
from types import TracebackType
from typing import Final, Self

import pytest

from w3xtool import current_map_snapshot as snapshot_module
from w3xtool.current_map_snapshot import (
    CurrentMapSnapshotError,
    cleanup_current_map_snapshot,
    create_current_map_snapshot,
)


_SNAPSHOT_DIR_PREFIX: Final = "w3xray-current-map-"
_OWNER_MARKER_NAME: Final = ".w3xray-current-map-owner"
_OWNER_MARKER_CONTENT: Final = b"W3XRAY_CURRENT_MAP_SNAPSHOT_V1\n"
_STALE_AFTER_NS: Final = 24 * 60 * 60 * 1_000_000_000
_MAX_STALE_REMOVALS: Final = 8


class _CountingScandir:
    def __init__(
        self,
        entries: Iterator[os.DirEntry[str]],
        fetched: list[str],
    ) -> None:
        self._entries: Iterator[os.DirEntry[str]] = entries
        self._fetched: list[str] = fetched

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        return None

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> os.DirEntry[str]:
        entry = next(self._entries)
        self._fetched.append(entry.name)
        return entry


def _isolated_snapshot_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    root = tmp_path / "snapshots"
    root.mkdir()
    monkeypatch.setattr(
        "w3xtool.current_map_snapshot.tempfile.gettempdir",
        lambda: str(root),
    )
    return root


def _source(tmp_path: Path, name: str = "source.w3x") -> Path:
    source = tmp_path / name
    _ = source.write_bytes(b"map")
    return source


def _write_owner_marker(directory: Path, content: bytes = _OWNER_MARKER_CONTENT) -> Path:
    marker = directory / _OWNER_MARKER_NAME
    _ = marker.write_bytes(content)
    if os.name == "posix":
        marker.chmod(0o600)
    return marker


def _stale_candidate(
    root: Path,
    name: str,
    marker_content: bytes | None,
) -> tuple[Path, Path]:
    directory = root / f"{_SNAPSHOT_DIR_PREFIX}{name}"
    directory.mkdir(mode=0o700)
    current = directory / "current.w3x"
    _ = current.write_bytes(b"stale")
    if marker_content is not None:
        _ = _write_owner_marker(directory, marker_content)
    stale_ns = time.time_ns() - _STALE_AFTER_NS - 1_000_000_000
    os.utime(directory, ns=(stale_ns, stale_ns))
    return directory, current


def test_snapshot_creates_versioned_regular_owner_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an isolated temp root and a valid map.
    _ = _isolated_snapshot_root(tmp_path, monkeypatch)

    # When: a snapshot is created.
    snapshot = create_current_map_snapshot(_source(tmp_path))

    # Then: its fixed ownership marker is regular and versioned exactly.
    try:
        marker = snapshot.path.parent / _OWNER_MARKER_NAME
        assert marker.is_file() and not marker.is_symlink()
        assert marker.read_bytes() == _OWNER_MARKER_CONTENT
    finally:
        cleanup_current_map_snapshot(snapshot)


def test_snapshot_cleanup_is_idempotent(tmp_path: Path) -> None:
    # Given: an owned current-map snapshot.
    snapshot = create_current_map_snapshot(_source(tmp_path))
    directory = snapshot.path.parent

    # When: cleanup is requested twice.
    cleanup_current_map_snapshot(snapshot)
    cleanup_current_map_snapshot(snapshot)

    # Then: the complete private directory remains absent.
    assert not directory.exists()


def test_later_snapshot_never_cleans_older_active_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: snapshot A remains active when the wall clock advances beyond stale age.
    _ = _isolated_snapshot_root(tmp_path, monkeypatch)
    first = create_current_map_snapshot(_source(tmp_path, "first.w3x"))
    future_ns = time.time_ns() + _STALE_AFTER_NS + 1_000_000_000
    monkeypatch.setattr(
        "w3xtool.current_map_snapshot.time.time_ns",
        lambda: future_ns,
    )

    # When: the same session creates snapshot B.
    second = create_current_map_snapshot(_source(tmp_path, "second.w3x"))

    # Then: creation does not perform lifecycle cleanup of snapshot A.
    try:
        assert first.path.read_bytes() == b"map"
    finally:
        cleanup_current_map_snapshot(first)
        cleanup_current_map_snapshot(second)


@pytest.mark.parametrize("marker_content", [None, b"not-owned\n"])
def test_stale_cleanup_leaves_unowned_prefixed_directory_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    marker_content: bytes | None,
) -> None:
    # Given: an old prefixed directory without a valid ownership marker.
    root = _isolated_snapshot_root(tmp_path, monkeypatch)
    _directory, current = _stale_candidate(root, "unowned", marker_content)

    # When: session-start stale cleanup runs explicitly.
    snapshot_module.cleanup_stale_current_map_snapshots()

    # Then: the unowned prefixed directory is not modified.
    assert current.read_bytes() == b"stale"


def test_session_start_cleanup_removes_bounded_abandoned_snapshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: more stale owned directories than one cleanup pass may remove.
    root = _isolated_snapshot_root(tmp_path, monkeypatch)
    stale = [
        _stale_candidate(root, f"{index:04d}", _OWNER_MARKER_CONTENT)[0]
        for index in range(_MAX_STALE_REMOVALS + 3)
    ]
    fresh, _current = _stale_candidate(root, "fresh", _OWNER_MARKER_CONTENT)
    os.utime(fresh, None)
    unrelated = root / "unrelated"
    unrelated.mkdir()

    # When: session-start cleanup runs before any session snapshots are created.
    snapshot_module.cleanup_stale_current_map_snapshots()

    # Then: only the removal budget is reclaimed and live/unrelated data survives.
    assert sum(directory.exists() for directory in stale) == 3
    assert (fresh / "current.w3x").read_bytes() == b"stale"
    assert unrelated.is_dir()


def test_stale_cleanup_does_not_follow_prefixed_directory_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a prefixed stale-looking symlink to data outside the temp root.
    root = _isolated_snapshot_root(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "current.w3x"
    _ = sentinel.write_bytes(b"do not delete")
    try:
        (root / f"{_SNAPSHOT_DIR_PREFIX}linked").symlink_to(
            outside,
            target_is_directory=True,
        )
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    # When: session-start stale cleanup runs.
    snapshot_module.cleanup_stale_current_map_snapshots()

    # Then: cleanup leaves the symlink target untouched.
    assert sentinel.read_bytes() == b"do not delete"


def test_stale_cleanup_does_not_follow_owner_marker_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a stale candidate whose marker symlinks to valid-looking outside data.
    root = _isolated_snapshot_root(tmp_path, monkeypatch)
    directory, current = _stale_candidate(root, "marker-link", None)
    outside_marker = tmp_path / "outside-owner"
    _ = outside_marker.write_bytes(_OWNER_MARKER_CONTENT)
    try:
        (directory / _OWNER_MARKER_NAME).symlink_to(outside_marker)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    stale_ns = time.time_ns() - _STALE_AFTER_NS - 1_000_000_000
    os.utime(directory, ns=(stale_ns, stale_ns))

    # When: session-start stale cleanup runs.
    snapshot_module.cleanup_stale_current_map_snapshots()

    # Then: a followed marker cannot authorize deletion.
    assert current.read_bytes() == b"stale"


def test_stale_scan_does_not_fetch_entry_beyond_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 65 unrelated temp entries and an iterator that records each fetch.
    root = _isolated_snapshot_root(tmp_path, monkeypatch)
    for index in range(65):
        (root / f"unrelated-{index:02d}").mkdir()
    real_scandir = os.scandir
    fetched: list[str] = []

    def counting_scandir(path: Path) -> _CountingScandir:
        with real_scandir(path) as entries:
            captured = iter(tuple(entries))
        return _CountingScandir(captured, fetched)

    monkeypatch.setattr("w3xtool.current_map_snapshot_cleanup.os.scandir", counting_scandir)

    # When: session-start cleanup performs its bounded stale scan.
    snapshot_module.cleanup_stale_current_map_snapshots()

    # Then: the 65th entry was never pulled from the iterator.
    assert len(fetched) == 64


def test_chmod_failure_removes_just_created_empty_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: chmod fails immediately after mkdtemp creates a directory.
    root = _isolated_snapshot_root(tmp_path, monkeypatch)

    def failing_chmod(_path: Path, _mode: int) -> None:
        raise PermissionError("injected chmod failure")

    monkeypatch.setattr("w3xtool.current_map_snapshot_cleanup.os.chmod", failing_chmod)

    # When/Then: creation fails without leaving the empty directory behind.
    with pytest.raises(CurrentMapSnapshotError, match="create snapshot"):
        _ = create_current_map_snapshot(_source(tmp_path))
    assert list(root.iterdir()) == []


def test_initial_temp_lstat_failure_removes_just_created_empty_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the first lstat of the newly created temp directory fails.
    root = _isolated_snapshot_root(tmp_path, monkeypatch)
    real_lstat = os.lstat

    def failing_temp_lstat(path: str | os.PathLike[str]) -> os.stat_result:
        candidate = Path(path)
        if candidate.parent == root and candidate.name.startswith(_SNAPSHOT_DIR_PREFIX):
            raise PermissionError("injected temp lstat failure")
        return real_lstat(path)

    monkeypatch.setattr("w3xtool.current_map_snapshot_cleanup.os.lstat", failing_temp_lstat)

    # When/Then: creation fails without relying on a captured directory identity.
    with pytest.raises(CurrentMapSnapshotError, match="create snapshot"):
        _ = create_current_map_snapshot(_source(tmp_path))
    assert list(root.iterdir()) == []
