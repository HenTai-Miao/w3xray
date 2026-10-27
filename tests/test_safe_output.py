"""Unified output containment and no-follow writer tests."""

from __future__ import annotations

from collections.abc import Iterator
import os
from pathlib import Path, PurePosixPath

import pytest

from tests.symlink_capability import skip_if_symlinks_unsupported
from gametool import safe_output
from gametool.safe_output import (
    SafeWriteStatus,
    safe_destination,
    safe_relative_path,
    write_bytes_safely,
    write_text_safely,
)


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
    assert safe_relative_path(r"scripts\war3map.j") == PurePosixPath(
        "scripts/war3map.j"
    )
    assert safe_destination(str(tmp_path), r"scripts\war3map.j") == str(
        tmp_path / "scripts" / "war3map.j",
    )


@skip_if_symlinks_unsupported
def test_rejects_existing_parent_directory_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "out"
    root.mkdir()
    (root / "assets").symlink_to(outside, target_is_directory=True)

    result = write_bytes_safely(str(root), "assets/x.bin", b"x")

    assert result.status is SafeWriteStatus.UNSAFE
    assert not (outside / "x.bin").exists()


@skip_if_symlinks_unsupported
def test_rejects_output_root_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "out"
    root.symlink_to(outside, target_is_directory=True)

    result = write_bytes_safely(str(root), "x.bin", b"x")

    assert result.status is SafeWriteStatus.UNSAFE
    assert not (outside / "x.bin").exists()


@skip_if_symlinks_unsupported
def test_rejects_existing_destination_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"before")
    root = tmp_path / "out"
    root.mkdir()
    (root / "asset.bin").symlink_to(outside)

    result = write_bytes_safely(str(root), "asset.bin", b"after")

    assert result.status is SafeWriteStatus.UNSAFE
    assert outside.read_bytes() == b"before"


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
    assert not tuple(tmp_path.glob(".gamexray-stage-*.tmp"))


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
        staged = next(tmp_path.glob(".gamexray-stage-*.tmp"))
        staged.unlink()
        _ = staged.write_bytes(b"attacker-data")
        return size

    monkeypatch.setattr(safe_output, "write_chunks_to_descriptor", replacing_writer)

    # When: the completed stage is about to replace an existing target.
    result = safe_output.write_chunks_safely(str(tmp_path), output.name, (b"trusted",))

    # Then: replacement is detected on POSIX or blocked by Windows while open.
    expected = SafeWriteStatus.FAILED if os.name == "nt" else SafeWriteStatus.UNSAFE
    assert result.status is expected
    assert output.read_bytes() == b"before"


def test_staged_path_identity_detects_replacement_after_close(tmp_path: Path) -> None:
    # Given: a closed stage is replaced while retaining the same path.
    staged = tmp_path / ".gamexray-stage-test.tmp"
    staged.write_bytes(b"trusted")
    details = staged.stat()
    identity = details.st_dev, details.st_ino
    staged.unlink()
    staged.write_bytes(b"replacement")

    # When/Then: the platform-neutral identity check rejects the new file.
    assert safe_output._staged_path_error(str(staged), identity) == (
        "staged output changed before publication"
    )


@skip_if_symlinks_unsupported
def test_safe_destination_rejects_in_root_parent_symlink(tmp_path: Path) -> None:
    root = tmp_path / "out"
    actual = root / "actual"
    actual.mkdir(parents=True)
    (root / "assets").symlink_to(actual, target_is_directory=True)

    destination = safe_destination(str(root), "assets/x.bin")

    assert destination is None


@skip_if_symlinks_unsupported
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
