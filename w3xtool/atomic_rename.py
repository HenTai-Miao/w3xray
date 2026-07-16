"""Fail-closed descriptor-anchored atomic rename primitives."""

from __future__ import annotations

import ctypes
import errno
import os
import sys
from typing import ClassVar, Final, Protocol, override


_DARWIN_RENAME_EXCL: Final = 0x00000004
_DARWIN_RENAME_SWAP: Final = 0x00000002
_LINUX_RENAME_EXCHANGE: Final = 2
_LINUX_RENAME_NOREPLACE: Final = 1
_UNAVAILABLE_ERRNOS: Final = frozenset(
    (errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP)
)


class _RenameAt(Protocol):
    argtypes: tuple[
        type[ctypes.c_int],
        type[ctypes.c_char_p],
        type[ctypes.c_int],
        type[ctypes.c_char_p],
        type[ctypes.c_uint],
    ]
    restype: type[ctypes.c_int]

    def __call__(
        self,
        source_descriptor: int,
        source_name: bytes,
        destination_descriptor: int,
        destination_name: bytes,
        flags: int,
    ) -> int: ...


class _LibC(ctypes.CDLL):
    renameatx_np: ClassVar[_RenameAt]
    renameat2: ClassVar[_RenameAt]


class AtomicRenameUnavailableError(OSError):
    """The host cannot guarantee the requested atomic directory rename."""

    __slots__: tuple[str, ...] = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    @override
    def __str__(self) -> str:
        return self.detail


class AtomicRenamePathError(ValueError):
    """An anchored rename name was not one safe leaf."""

    __slots__: tuple[str, ...] = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    @override
    def __str__(self) -> str:
        return self.detail


def rename_noreplace(
    source_descriptor: int,
    source_name: str,
    destination_descriptor: int,
    destination_name: str,
) -> None:
    """Rename one anchored leaf only when the destination is absent."""
    _require_leaf(source_name)
    _require_leaf(destination_name)
    if sys.platform == "darwin":
        _call(
            "renameatx_np",
            source_descriptor,
            source_name,
            destination_descriptor,
            destination_name,
            _DARWIN_RENAME_EXCL,
        )
        return
    if sys.platform.startswith("linux"):
        _call(
            "renameat2",
            source_descriptor,
            source_name,
            destination_descriptor,
            destination_name,
            _LINUX_RENAME_NOREPLACE,
        )
        return
    raise AtomicRenameUnavailableError(
        f"atomic no-replace rename is unavailable on {sys.platform}"
    )


def rename_exchange(
    source_descriptor: int,
    source_name: str,
    destination_descriptor: int,
    destination_name: str,
) -> None:
    """Atomically exchange two existing anchored leaves."""
    _require_leaf(source_name)
    _require_leaf(destination_name)
    if sys.platform == "darwin":
        _call(
            "renameatx_np",
            source_descriptor,
            source_name,
            destination_descriptor,
            destination_name,
            _DARWIN_RENAME_SWAP,
        )
        return
    if sys.platform.startswith("linux"):
        _call(
            "renameat2",
            source_descriptor,
            source_name,
            destination_descriptor,
            destination_name,
            _LINUX_RENAME_EXCHANGE,
        )
        return
    raise AtomicRenameUnavailableError(
        f"atomic exchange rename is unavailable on {sys.platform}"
    )


def _call(
    symbol: str,
    source_descriptor: int,
    source_name: str,
    destination_descriptor: int,
    destination_name: str,
    flags: int,
) -> None:
    library = _LibC(None, use_errno=True)
    try:
        function = (
            library.renameatx_np if symbol == "renameatx_np" else library.renameat2
        )
    except (AttributeError, OSError) as exc:
        raise AtomicRenameUnavailableError(
            f"atomic no-replace rename symbol is unavailable: {symbol}"
        ) from exc
    function.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    function.restype = ctypes.c_int
    _ = ctypes.set_errno(0)
    result = function(
        source_descriptor,
        os.fsencode(source_name),
        destination_descriptor,
        os.fsencode(destination_name),
        flags,
    )
    if result == 0:
        return
    error = ctypes.get_errno()
    if error in _UNAVAILABLE_ERRNOS:
        raise AtomicRenameUnavailableError(
            f"atomic no-replace rename is unsupported: {os.strerror(error)}"
        )
    raise OSError(error, os.strerror(error), destination_name)


def _require_leaf(name: str) -> None:
    if not name or name in {".", ".."} or os.sep in name:
        raise AtomicRenamePathError("anchored rename requires one leaf name")
    if os.altsep is not None and os.altsep in name:
        raise AtomicRenamePathError("anchored rename requires one leaf name")


__all__ = (
    "AtomicRenamePathError",
    "AtomicRenameUnavailableError",
    "rename_exchange",
    "rename_noreplace",
)
