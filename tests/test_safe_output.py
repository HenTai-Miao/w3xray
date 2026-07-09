"""Unified output containment and no-follow writer tests."""

from __future__ import annotations

import errno
import os
from pathlib import Path, PurePosixPath

import pytest

from w3xtool import safe_output
from w3xtool.safe_output import (
    SafeWriteStatus,
    safe_destination,
    safe_relative_path,
    write_bytes_safely,
    write_text_safely,
)


_HAS_ANCHORED_DIRECTORY_OPEN = (
    os.open in os.supports_dir_fd
    and os.mkdir in os.supports_dir_fd
    and hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
)


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
    not _HAS_ANCHORED_DIRECTORY_OPEN,
    reason="requires dir_fd open/mkdir with O_DIRECTORY and O_NOFOLLOW",
)
def test_parent_swap_before_file_open_stays_in_anchored_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "out"
    parent = root / "assets"
    parent.mkdir(parents=True)
    anchored_parent = root / "assets-anchored"
    outside = tmp_path / "outside"
    outside.mkdir()
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
            parent.rename(anchored_parent)
            parent.symlink_to(outside, target_is_directory=True)
            swapped = True
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(safe_output.os, "open", racing_open)

    result = write_bytes_safely(str(root), "assets/x.bin", b"anchored")

    assert swapped
    assert result.status is SafeWriteStatus.WRITTEN
    assert result.path == str(parent / "x.bin")
    assert not (outside / "x.bin").exists()
    assert (anchored_parent / "x.bin").read_bytes() == b"anchored"


@pytest.mark.skipif(
    not _HAS_ANCHORED_DIRECTORY_OPEN,
    reason="requires dir_fd open/mkdir with O_DIRECTORY and O_NOFOLLOW",
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
