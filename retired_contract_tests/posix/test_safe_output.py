"""Unified output containment and no-follow writer tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import errno
import os
import stat
from pathlib import Path
from typing import BinaryIO

import pytest

from gametool import safe_output
from gametool.safe_output import (
    SafeWriteStatus,
    write_bytes_safely,
)
from gametool.safe_output_anchored import ANCHORED_WRITES_AVAILABLE


def _track_opened_descriptors(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    original_open = safe_output.os.open
    opened_descriptors: list[int] = []

    def tracking_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        opened_descriptors.append(descriptor)
        return descriptor

    monkeypatch.setattr(safe_output.os, "open", tracking_open)
    return opened_descriptors


@pytest.mark.skipif(
    not ANCHORED_WRITES_AVAILABLE,
    reason="requires dir_fd open/mkdir/unlink with O_DIRECTORY and O_NOFOLLOW",
)
def test_parent_move_outside_before_file_open_removes_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "out"
    parent = root / "assets"
    parent.mkdir(parents=True)
    moved_parent = tmp_path / "assets-moved"
    redirected_parent = tmp_path / "assets-redirected"
    redirected_parent.mkdir()
    original_open = safe_output.os.open
    swapped = False

    def racing_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if not swapped and flags & os.O_WRONLY:
            parent.rename(moved_parent)
            parent.symlink_to(redirected_parent, target_is_directory=True)
            swapped = True
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(safe_output.os, "open", racing_open)

    result = write_bytes_safely(str(root), "assets/x.bin", b"anchored")

    assert swapped
    assert result.path == str(parent / "x.bin")
    assert not (moved_parent / "x.bin").exists()
    assert not (redirected_parent / "x.bin").exists()
    assert result.status is not SafeWriteStatus.WRITTEN


@pytest.mark.skipif(
    not ANCHORED_WRITES_AVAILABLE,
    reason="requires dir_fd open/mkdir/unlink with O_DIRECTORY and O_NOFOLLOW",
)
def test_closes_directory_descriptors_when_file_open_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "out"
    (root / "assets").mkdir(parents=True)
    original_open = safe_output.os.open
    opened_directories: list[int] = []

    def failing_file_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if flags & os.O_WRONLY:
            raise OSError(errno.ENOSPC, "simulated full disk")
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if flags & os.O_DIRECTORY:
            opened_directories.append(descriptor)
        return descriptor

    monkeypatch.setattr(safe_output.os, "open", failing_file_open)

    result = write_bytes_safely(str(root), "assets/x.bin", b"x")

    assert result.status is SafeWriteStatus.FAILED
    assert opened_directories
    for descriptor in opened_directories:
        with pytest.raises(OSError) as error:
            os.fstat(descriptor)
        assert error.value.errno == errno.EBADF


@pytest.mark.skipif(
    not ANCHORED_WRITES_AVAILABLE,
    reason="requires dir_fd open/mkdir/unlink with O_DIRECTORY and O_NOFOLLOW",
)
def test_closes_all_descriptors_after_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "out"
    (root / "assets").mkdir(parents=True)
    opened_descriptors = _track_opened_descriptors(monkeypatch)

    result = write_bytes_safely(str(root), "assets/x.bin", b"x")

    assert result.status is SafeWriteStatus.WRITTEN
    assert opened_descriptors
    for descriptor in set(opened_descriptors):
        with pytest.raises(OSError) as error:
            os.fstat(descriptor)
        assert error.value.errno == errno.EBADF


@pytest.mark.skipif(
    not ANCHORED_WRITES_AVAILABLE,
    reason="requires dir_fd open/mkdir/unlink with O_DIRECTORY and O_NOFOLLOW",
)
def test_closes_all_descriptors_when_file_wrapper_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "out"
    (root / "assets").mkdir(parents=True)
    opened_descriptors = _track_opened_descriptors(monkeypatch)

    def failing_fdopen(
        descriptor: int,
        mode: str,
        *,
        closefd: bool = True,
    ) -> None:
        raise OSError(errno.ENOSPC, "simulated full disk")

    monkeypatch.setattr(safe_output.os, "fdopen", failing_fdopen)

    result = write_bytes_safely(str(root), "assets/x.bin", b"x")

    assert result.status is SafeWriteStatus.FAILED
    assert opened_descriptors
    for descriptor in set(opened_descriptors):
        with pytest.raises(OSError) as error:
            os.fstat(descriptor)
        assert error.value.errno == errno.EBADF


@pytest.mark.skipif(
    not ANCHORED_WRITES_AVAILABLE,
    reason="requires dir_fd open/mkdir/unlink with O_DIRECTORY and O_NOFOLLOW",
)
def test_parent_move_outside_after_write_removes_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "out"
    parent = root / "assets"
    parent.mkdir(parents=True)
    moved_parent = tmp_path / "assets-moved-after-write"
    redirected_parent = tmp_path / "assets-redirected-after-write"
    redirected_parent.mkdir()
    original_fdopen = safe_output.os.fdopen

    @contextmanager
    def moving_fdopen(
        descriptor: int,
        mode: str,
        *,
        closefd: bool = True,
    ) -> Iterator[BinaryIO]:
        with original_fdopen(descriptor, mode, closefd=closefd) as handle:
            yield handle  # pyright: ignore[reportReturnType]
        parent.rename(moved_parent)
        parent.symlink_to(redirected_parent, target_is_directory=True)

    monkeypatch.setattr(safe_output.os, "fdopen", moving_fdopen)

    result = write_bytes_safely(str(root), "assets/x.bin", b"anchored")

    assert result.path == str(parent / "x.bin")
    assert not (moved_parent / "x.bin").exists()
    assert not (redirected_parent / "x.bin").exists()
    assert result.status is SafeWriteStatus.UNSAFE


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX mode bits")
def test_new_output_file_mode_is_0600(tmp_path: Path) -> None:
    result = write_bytes_safely(str(tmp_path), "x.bin", b"x")

    assert result.status is SafeWriteStatus.WRITTEN
    assert stat.S_IMODE((tmp_path / "x.bin").stat().st_mode) == 0o600
