from __future__ import annotations

import mmap
import os
from pathlib import Path
import subprocess
import sys

import pytest

from w3xtool import mpq_storage
from w3xtool.mpq import MPQArchive
from w3xtool.mpq_layout import MPQLayoutError
from w3xtool.mpq_storage import MPQBackingStore, open_mpq_backing


class _UnexpectedMmapError(RuntimeError):
    pass


class _MmapRejectedError(ValueError):
    pass


def test_backing_store_close_releases_real_mmap_and_handle(tmp_path: Path) -> None:
    path = tmp_path / "large-invalid.w3x"
    with path.open("wb") as handle:
        handle.truncate(41 * 1024 * 1024)
    store = open_mpq_backing(str(path))
    mapped = store.data
    source_handle = store.handle
    assert isinstance(mapped, mmap.mmap)
    assert source_handle is not None
    store.close()
    store.close()
    assert mapped.closed
    assert source_handle.closed


def test_backing_store_retains_mmap_when_exported_buffer_blocks_close(
    tmp_path: Path,
) -> None:
    path = tmp_path / "large.w3x"
    with path.open("wb") as handle:
        handle.truncate(41 * 1024 * 1024)
    store = open_mpq_backing(str(path))
    mapped = store.data
    assert isinstance(mapped, mmap.mmap)
    exported = memoryview(mapped)
    store.close()
    assert store.data is mapped
    assert not mapped.closed
    exported.release()
    store.close()
    assert mapped.closed


def test_archive_constructor_closes_backing_when_layout_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "large-invalid.w3x"
    with path.open("wb") as handle:
        handle.truncate(41 * 1024 * 1024)
    store = open_mpq_backing(str(path))
    mapped = store.data
    source_handle = store.handle
    monkeypatch.setattr("w3xtool.mpq.open_mpq_backing", lambda _path: store)
    with pytest.raises(MPQLayoutError):
        MPQArchive(str(path))
    assert isinstance(mapped, mmap.mmap) and mapped.closed
    assert source_handle is not None and source_handle.closed


def test_archive_constructor_removes_fallback_copy_when_layout_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary = tmp_path / "fallback.w3x"
    temporary.write_bytes(b"not an mpq")
    store = MPQBackingStore(
        data=temporary.read_bytes(),
        handle=None,
        temporary_path=str(temporary),
    )
    monkeypatch.setattr("w3xtool.mpq.open_mpq_backing", lambda _path: store)
    with pytest.raises(MPQLayoutError):
        MPQArchive("source.w3x")
    assert not temporary.exists()


def test_fallback_copy_is_removed_when_second_open_raises_value_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.w3x"
    source.write_bytes(b"source")
    temporary = tmp_path / "owned-copy.w3x"
    calls = 0

    def failing_open(_path: str, *, temporary_path: str | None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PermissionError("direct open denied")
        raise ValueError

    def owned_mkstemp(*, suffix: str):
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        return descriptor, str(temporary)

    monkeypatch.setattr(mpq_storage, "_open_path", failing_open)
    monkeypatch.setattr(mpq_storage.tempfile, "mkstemp", owned_mkstemp)
    with pytest.raises(ValueError):
        open_mpq_backing(str(source))
    assert calls == 2
    assert not temporary.exists()


def test_fifo_source_is_rejected_without_waiting_for_writer(tmp_path: Path) -> None:
    # Given: a FIFO path with no writer process connected.
    if not hasattr(os, "mkfifo"):
        pytest.skip("mkfifo is unavailable")
    fifo = tmp_path / "stream.w3x"
    os.mkfifo(fifo)
    script = "\n".join(
        (
            "import sys",
            "from w3xtool.mpq_storage import open_mpq_backing",
            "try:",
            "    open_mpq_backing(sys.argv[1])",
            "except OSError as error:",
            "    raise SystemExit(0 if 'regular' in str(error) else 2)",
            "raise SystemExit(3)",
        )
    )

    # When: a fresh process attempts to open the FIFO as an archive.
    completed = subprocess.run(
        (sys.executable, "-c", script, str(fifo)),
        check=False,
        capture_output=True,
        timeout=2,
    )

    # Then: it rejects the non-regular descriptor without needing a peer.
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")


def test_open_uses_descriptor_size_instead_of_preopen_path_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "small.w3x"
    path.write_bytes(b"archive")

    def reject_preopen_stat(_path: str) -> int:
        raise AssertionError("pre-open path size is racy")

    monkeypatch.setattr(mpq_storage.os.path, "getsize", reject_preopen_stat)
    store = open_mpq_backing(str(path))
    try:
        assert store.data == b"archive"
    finally:
        store.close()


def test_unexpected_mmap_failure_still_closes_source_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "large.w3x"
    with path.open("wb") as handle:
        handle.truncate(41 * 1024 * 1024)
    real_open = mpq_storage.open_regular_binary
    source_handles = []

    def tracking_open(file: str):
        handle, size = real_open(file)
        if Path(file) == path:
            source_handles.append(handle)
        return handle, size

    def unexpected_mmap_failure(*_args, **_kwargs):
        raise _UnexpectedMmapError("unexpected mmap failure")

    monkeypatch.setattr(mpq_storage, "open_regular_binary", tracking_open)
    monkeypatch.setattr(mpq_storage.mmap, "mmap", unexpected_mmap_failure)

    with pytest.raises(_UnexpectedMmapError, match="unexpected mmap failure"):
        mpq_storage._open_path(str(path), temporary_path=None)

    assert len(source_handles) == 1 and source_handles[0].closed


def test_fallback_cleanup_failure_preserves_primary_open_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.w3x"
    source.write_bytes(b"source")
    temporary = tmp_path / "owned-copy.w3x"
    calls = 0

    def failing_open(_path: str, *, temporary_path: str | None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PermissionError("direct open denied")
        raise _MmapRejectedError("mmap rejected")

    def owned_mkstemp(*, suffix: str):
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        return descriptor, str(temporary)

    def failing_remove(_path: str) -> None:
        raise PermissionError("cleanup denied")

    monkeypatch.setattr(mpq_storage, "_open_path", failing_open)
    monkeypatch.setattr(mpq_storage.tempfile, "mkstemp", owned_mkstemp)
    monkeypatch.setattr(mpq_storage.os, "remove", failing_remove)

    try:
        with pytest.raises(ValueError, match="mmap rejected") as caught:
            open_mpq_backing(str(source))
        assert any("cleanup denied" in note for note in caught.value.__notes__)
    finally:
        temporary.unlink(missing_ok=True)
