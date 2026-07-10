"""Unified output containment and no-follow writer tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import errno
import os
import stat
from pathlib import Path, PurePosixPath
from typing import BinaryIO

import pytest

from w3xtool import safe_output
from w3xtool.safe_output import (
    SafeWriteStatus,
    safe_destination,
    safe_relative_path,
    write_bytes_safely,
    write_text_safely,
)
from w3xtool.safe_output_anchored import ANCHORED_WRITES_AVAILABLE


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


@pytest.mark.parametrize(
    "name",
    ("../x", "/tmp/x", "//server/share/x", r"C:\x", "C:/x", "a\0b"),
)
def test_rejects_non_relative_output_names(name: str) -> None:
    assert safe_relative_path(name) is None


def test_normalizes_safe_archive_separators(tmp_path: Path) -> None:
    assert safe_relative_path(r"scripts\war3map.j") == PurePosixPath("scripts/war3map.j")
    assert safe_destination(str(tmp_path), r"scripts\war3map.j") == str(
        tmp_path / "scripts" / "war3map.j",
    )


def test_rejects_existing_parent_directory_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "out"
    root.mkdir()
    (root / "assets").symlink_to(outside, target_is_directory=True)

    result = write_bytes_safely(str(root), "assets/x.bin", b"x")

    assert result.status is SafeWriteStatus.UNSAFE
    assert not (outside / "x.bin").exists()


def test_rejects_output_root_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "out"
    root.symlink_to(outside, target_is_directory=True)

    result = write_bytes_safely(str(root), "x.bin", b"x")

    assert result.status is SafeWriteStatus.UNSAFE
    assert not (outside / "x.bin").exists()


def test_rejects_existing_destination_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"before")
    root = tmp_path / "out"
    root.mkdir()
    (root / "asset.bin").symlink_to(outside)

    result = write_bytes_safely(str(root), "asset.bin", b"after")

    assert result.status is SafeWriteStatus.UNSAFE
    assert outside.read_bytes() == b"before"


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
            yield handle
        parent.rename(moved_parent)
        parent.symlink_to(redirected_parent, target_is_directory=True)

    monkeypatch.setattr(safe_output.os, "fdopen", moving_fdopen)

    result = write_bytes_safely(str(root), "assets/x.bin", b"anchored")

    assert result.path == str(parent / "x.bin")
    assert not (moved_parent / "x.bin").exists()
    assert not (redirected_parent / "x.bin").exists()
    assert result.status is SafeWriteStatus.UNSAFE


def test_path_checked_fallback_writes_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(safe_output, "_ANCHORED_WRITES_AVAILABLE", False)

    result = write_bytes_safely(str(tmp_path), "assets/x.bin", b"fallback")

    assert result.status is SafeWriteStatus.WRITTEN
    assert (tmp_path / "assets" / "x.bin").read_bytes() == b"fallback"


def test_chunk_writer_fallback_publishes_only_after_all_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an existing target and the Windows-style path-checked fallback.
    monkeypatch.setattr(safe_output, "_ANCHORED_WRITES_AVAILABLE", False)
    output = tmp_path / "inventory.tsv"
    _ = output.write_bytes(b"before")

    def chunks() -> Iterator[bytes]:
        yield b"new-"
        assert output.read_bytes() == b"before"
        yield b"data"

    # When: staged chunks are written and published.
    result = safe_output.write_chunks_safely(str(tmp_path), output.name, chunks())

    # Then: the complete payload atomically replaces the old target.
    assert result.status is SafeWriteStatus.WRITTEN
    assert result.size == len(b"new-data")
    assert output.read_bytes() == b"new-data"
    assert not tuple(tmp_path.glob(".w3xray-stage-*.tmp"))


def test_chunk_writer_fallback_preserves_target_when_source_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a chunk source that fails after producing partial staged data.
    monkeypatch.setattr(safe_output, "_ANCHORED_WRITES_AVAILABLE", False)
    output = tmp_path / "inventory.tsv"
    _ = output.write_bytes(b"before")

    def chunks() -> Iterator[bytes]:
        yield b"partial"
        raise RuntimeError("enumeration failed")

    # When: the source raises before publication.
    with pytest.raises(RuntimeError, match="enumeration failed"):
        _ = safe_output.write_chunks_safely(str(tmp_path), output.name, chunks())

    # Then: the prior target and directory are unchanged.
    assert output.read_bytes() == b"before"
    assert tuple(tmp_path.iterdir()) == (output,)


def test_chunk_writer_fallback_rejects_replaced_staged_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: another process replaces the private stage before publication.
    monkeypatch.setattr(safe_output, "_ANCHORED_WRITES_AVAILABLE", False)
    output = tmp_path / "inventory.tsv"
    _ = output.write_bytes(b"before")
    original_writer = safe_output.write_chunks_to_descriptor

    def replacing_writer(descriptor: int, chunks: Iterator[bytes]) -> int:
        size = original_writer(descriptor, chunks)
        staged = next(tmp_path.glob(".w3xray-stage-*.tmp"))
        staged.unlink()
        _ = staged.write_bytes(b"attacker-data")
        return size

    monkeypatch.setattr(safe_output, "write_chunks_to_descriptor", replacing_writer)

    # When: the completed stage is about to replace an existing target.
    result = safe_output.write_chunks_safely(str(tmp_path), output.name, (b"trusted",))

    # Then: inode ownership fails closed and the existing target survives.
    assert result.status is SafeWriteStatus.UNSAFE
    assert output.read_bytes() == b"before"


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX mode bits")
def test_new_output_file_mode_is_0600(tmp_path: Path) -> None:
    result = write_bytes_safely(str(tmp_path), "x.bin", b"x")

    assert result.status is SafeWriteStatus.WRITTEN
    assert stat.S_IMODE((tmp_path / "x.bin").stat().st_mode) == 0o600


def test_safe_destination_rejects_in_root_parent_symlink(tmp_path: Path) -> None:
    root = tmp_path / "out"
    actual = root / "actual"
    actual.mkdir(parents=True)
    (root / "assets").symlink_to(actual, target_is_directory=True)

    destination = safe_destination(str(root), "assets/x.bin")

    assert destination is None


def test_safe_destination_rejects_in_root_destination_symlink(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    target = root / "target.bin"
    target.write_bytes(b"before")
    (root / "asset.bin").symlink_to(target)

    destination = safe_destination(str(root), "asset.bin")

    assert destination is None


def test_text_writer_reports_utf8_byte_size(tmp_path: Path) -> None:
    result = write_text_safely(str(tmp_path), "报告.txt", "测试\n")

    assert result.status is SafeWriteStatus.WRITTEN
    assert result.size == len("测试\n".encode())
    assert (tmp_path / "报告.txt").read_text(encoding="utf-8") == "测试\n"
