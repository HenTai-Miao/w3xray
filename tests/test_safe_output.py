"""Unified output containment and no-follow writer tests."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from w3xtool.safe_output import (
    SafeWriteStatus,
    safe_destination,
    safe_relative_path,
    write_bytes_safely,
    write_text_safely,
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
