"""Warcraft III game-data source backed by CascLib."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from types import TracebackType
from typing import override

from .casclib_api import (
    CascFileNotFoundError,
    CascLibApi,
    CascLibLoadError,
    CascNativeError,
    CtypesCascLibApi,
)
from .casclib_enumeration import CascEntry, CascLibEnumerationApi
from .game_data_inventory import GameDataInventoryView


@dataclass(frozen=True, slots=True)
class CascLibProbe:
    is_available: bool
    reason: str


@dataclass(frozen=True, slots=True)
class CascSourceClosedError(OSError):
    root: str

    @override
    def __str__(self) -> str:
        return f"CascLib data source is closed: {self.root}"


@dataclass(frozen=True, slots=True)
class CascEnumerationUnavailableError(OSError):
    root: str

    @override
    def __str__(self) -> str:
        return f"CascLib build cannot enumerate storage entries: {self.root}"


class CascLibDataSource:
    """Read internal Warcraft III paths from one open CascLib storage."""

    inventory_view = GameDataInventoryView.FULL_ROOT

    root: str
    _api: CascLibApi

    def __init__(self, root: str, api: CascLibApi | None = None) -> None:
        self.root = root
        self._api = api if api is not None else CtypesCascLibApi()
        self._storage: int | None = self._api.open_storage(root)

    def has_file(self, name: str) -> bool:
        storage = self._open_storage_handle()
        file_handle: int | None = None
        try:
            file_handle = self._api.open_file(storage, _internal_name(name))
            return True
        except CascFileNotFoundError:
            return False
        finally:
            if file_handle is not None:
                self._api.close_file(file_handle)

    def read_file(self, name: str) -> bytes:
        storage = self._open_storage_handle()
        file_handle: int | None = None
        try:
            file_handle = self._api.open_file(storage, _internal_name(name))
            size = self._api.file_size(file_handle)
            return self._api.read_file(file_handle, size)
        finally:
            if file_handle is not None:
                self._api.close_file(file_handle)

    def has_exact_file(self, name: str) -> bool:
        return self.has_file(name)

    def read_exact_file(self, name: str) -> bytes:
        return self.read_file(name)

    def iter_entries(
        self,
        mask: str = "*",
        listfile: str | None = None,
    ) -> Generator[CascEntry, None, None]:
        """Yield all root and nameless encoding entries, closing search on exit."""
        api = self._enumeration_api()
        first = api.find_first(self._open_storage_handle(), mask, listfile)
        if first is None:
            return
        search, entry = first
        try:
            yield entry
            while (entry := api.find_next(search)) is not None:
                yield entry
        finally:
            api.close_find(search)

    def close(self) -> None:
        storage = self._storage
        if storage is None:
            return
        self._storage = None
        self._api.close_storage(storage)

    def __enter__(self) -> CascLibDataSource:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _open_storage_handle(self) -> int:
        if self._storage is None:
            raise CascSourceClosedError(root=self.root)
        return self._storage

    def _enumeration_api(self) -> CascLibEnumerationApi:
        if not isinstance(self._api, CascLibEnumerationApi):
            raise CascEnumerationUnavailableError(root=self.root)
        return self._api


def casclib_available() -> bool:
    """Return whether the packaged CascLib DLL can be loaded on this platform."""
    try:
        _ = CtypesCascLibApi()
    except CascLibLoadError:
        return False
    return True


def probe_casclib(root: str) -> CascLibProbe:
    """Load CascLib and verify that it can open this native installation."""
    try:
        with CascLibDataSource(root):
            return CascLibProbe(is_available=True, reason="CascLib storage readable")
    except (CascLibLoadError, CascNativeError) as exc:
        return CascLibProbe(is_available=False, reason=str(exc))


def _internal_name(name: str) -> str:
    return name.replace("/", "\\").lstrip("\\")
