"""CascLib-backed game-data source contract tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Never

import pytest

import w3xtool.casclib_api as casclib_api
import w3xtool.casclib_source as casclib_source
from w3xtool.casclib_api import (
    CascFileNotFoundError,
    CascLibLoadError,
    CascNativeError,
    CtypesCascLibApi,
)
from w3xtool.casclib_source import CascLibDataSource, probe_casclib


@dataclass(slots=True)  # noqa: MUTABLE_OK - fake tracks native handle lifecycle.
class FakeCascLibApi:
    """In-memory CascLib API whose handles expose lifecycle mistakes."""

    files: dict[str, bytes]
    storage_error: int | None = None
    read_error: int | None = None
    size_error: int | None = None
    open_handles: set[int] = field(default_factory=set)
    events: list[str] = field(default_factory=list)
    _next_handle: int = 100
    _file_by_handle: dict[int, str] = field(default_factory=dict)

    def open_storage(self, path: str) -> int:
        self.events.append(f"open_storage:{path}")
        if self.storage_error is not None:
            raise CascNativeError(
                operation="CascOpenStorage", native_error_code=self.storage_error
            )
        return self._open_handle()

    def close_storage(self, handle: int) -> None:
        self.events.append(f"close_storage:{handle}")
        self.open_handles.remove(handle)

    def open_file(self, storage: int, name: str) -> int:
        self.events.append(f"open_file:{name}")
        if name not in self.files:
            raise CascFileNotFoundError(name=name, native_error_code=2)
        handle = self._open_handle()
        self._file_by_handle[handle] = name
        return handle

    def file_size(self, handle: int) -> int:
        if self.size_error is not None:
            raise CascNativeError(
                operation="CascGetFileSize64", native_error_code=self.size_error
            )
        return len(self.files[self._file_by_handle[handle]])

    def read_file(self, handle: int, size: int) -> bytes:
        if self.read_error is not None:
            raise CascNativeError(
                operation="CascReadFile", native_error_code=self.read_error
            )
        return self.files[self._file_by_handle[handle]][:size]

    def close_file(self, handle: int) -> None:
        self.events.append(f"close_file:{handle}")
        self._file_by_handle.pop(handle)
        self.open_handles.remove(handle)

    def _open_handle(self) -> int:
        handle = self._next_handle
        self._next_handle += 1
        self.open_handles.add(handle)
        return handle


def test_source_reads_internal_file_and_closes_handles() -> None:
    # Given: three game resources exposed by a fake native API.
    api = FakeCascLibApi(
        {
            "UI\\TriggerData.txt": b"[TriggerActions]\n",
            "UI\\TriggerStrings.txt": b"WESTRING_TEST=Test\n",
            "ReplaceableTextures\\CommandButtons\\BTNHero.blp": b"BLP1hero",
        }
    )

    # When: callers use both slash styles and close the source context.
    with CascLibDataSource("C:/Warcraft III", api=api) as source:
        assert source.has_file("UI/TriggerData.txt")
        assert source.read_file("UI\\TriggerStrings.txt").startswith(b"WESTRING")
        assert (
            source.read_file("ReplaceableTextures/CommandButtons/BTNHero.blp")
            == b"BLP1hero"
        )

    # Then: all native file and storage handles are closed.
    assert api.open_handles == set()
    assert api.events[-1].startswith("close_storage:")


def test_missing_file_is_false_for_has_and_raises_for_read() -> None:
    # Given: an open native storage without the requested path.
    api = FakeCascLibApi({})
    with CascLibDataSource("C:/Warcraft III", api=api) as source:
        # When/Then: probing is false while reading keeps missing distinct.
        assert not source.has_file("UI/Missing.txt")
        with pytest.raises(CascFileNotFoundError) as caught:
            source.read_file("UI/Missing.txt")
        assert caught.value.native_error_code == 2

    assert api.open_handles == set()


def test_exact_lookup_uses_the_full_internal_casclib_path() -> None:
    # Given
    api = FakeCascLibApi({"Icons\\BTNHero.blp": b"BLP1hero"})

    # When / Then
    with CascLibDataSource("C:/Warcraft III", api=api) as source:
        assert source.has_exact_file("Icons/BTNHero.blp")
        assert not source.has_exact_file("BTNHero.blp")
        assert source.read_exact_file("Icons/BTNHero.blp") == b"BLP1hero"


@pytest.mark.parametrize("failure", ["size", "read"])
def test_file_handle_closes_when_native_file_operation_fails(failure: str) -> None:
    # Given: a native file whose size lookup or body read fails.
    api = FakeCascLibApi(
        {"UI\\TriggerData.txt": b"data"},
        size_error=1006 if failure == "size" else None,
        read_error=1005 if failure == "read" else None,
    )

    # When: the native error escapes from read_file.
    with CascLibDataSource("C:/Warcraft III", api=api) as source:
        with pytest.raises(CascNativeError) as caught:
            source.read_file("UI/TriggerData.txt")
        assert caught.value.native_error_code in {1005, 1006}
        assert len(api.open_handles) == 1

    # Then: file finally and storage close leave no handles behind.
    assert api.open_handles == set()


def test_close_is_idempotent() -> None:
    # Given: an open native storage.
    api = FakeCascLibApi({})
    source = CascLibDataSource("C:/Warcraft III", api=api)

    # When: close is called repeatedly.
    source.close()
    source.close()

    # Then: the storage is closed exactly once.
    assert api.open_handles == set()
    assert sum(event.startswith("close_storage:") for event in api.events) == 1


def test_missing_dll_load_error_has_specific_probe_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: Windows is selected but the configured DLL is absent.
    missing = tmp_path / "CascLib.dll"
    monkeypatch.setattr(casclib_api.sys, "platform", "win32")

    # When/Then: loading fails before ctypes with a concrete path and native code.
    with pytest.raises(CascLibLoadError) as caught:
        CtypesCascLibApi(dll_path=missing)
    assert "CascLib.dll 不存在" in str(caught.value)
    assert caught.value.native_error_code == 2


def test_wrong_architecture_load_error_preserves_win32_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a present DLL that Windows rejects as ERROR_BAD_EXE_FORMAT.
    dll = tmp_path / "CascLib.dll"
    dll.write_bytes(b"not-an-x64-pe")
    monkeypatch.setattr(casclib_api.sys, "platform", "win32")

    def reject_bad_image(_path: str) -> casclib_api.ctypes.CDLL:
        error = OSError("bad image")
        error.winerror = 193
        raise error

    monkeypatch.setattr(casclib_api.ctypes, "WinDLL", reject_bad_image, raising=False)

    # When/Then: the adapter classifies architecture and keeps error 193.
    with pytest.raises(CascLibLoadError) as caught:
        CtypesCascLibApi(dll_path=dll)
    assert "架构错误" in str(caught.value)
    assert caught.value.native_error_code == 193


def test_probe_reports_missing_required_dll_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a loadable DLL facade that is missing one required CascLib export.
    class MissingExportLibrary(casclib_api.ctypes.CDLL):
        def __getattr__(self, name: str) -> Never:
            raise AttributeError(name)

    missing_library = object.__new__(MissingExportLibrary)

    monkeypatch.setattr(
        casclib_source,
        "CtypesCascLibApi",
        lambda: CtypesCascLibApi(library=missing_library),
    )

    # When: the concrete probe tries to bind the incompatible DLL.
    result = probe_casclib("C:/Warcraft III")

    # Then: probing reports a load compatibility error instead of leaking AttributeError.
    assert not result.is_available
    assert "缺少必需导出符号" in result.reason
    assert "CascOpenStorage" in result.reason


def test_probe_reports_open_storage_native_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the DLL loads but its storage open fails.
    api = FakeCascLibApi({}, storage_error=1006)
    monkeypatch.setattr(casclib_source, "CtypesCascLibApi", lambda: api)

    # When: the concrete CascLib probe opens the install.
    result = probe_casclib("C:/Warcraft III")

    # Then: the operation and native code survive into the probe reason.
    assert not result.is_available
    assert "CascOpenStorage" in result.reason
    assert "1006" in result.reason
