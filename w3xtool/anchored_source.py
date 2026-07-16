"""Stable regular-file reads through a held no-follow source-root chain."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import errno
import os
from pathlib import Path, PurePosixPath
import stat
from types import TracebackType
from typing import Final, final, override

from .bounded_file import FileIdentity


_READ_CHUNK_BYTES: Final = 1024 * 1024
_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_FILE_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_BINARY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_ANCHORED_OPEN_AVAILABLE: Final = bool(
    os.open in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks
    and hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
)
type _FileState = tuple[int, int, int, int, int, int]


class AnchoredSourceError(OSError):
    """A source could not be read through its held root directory."""

    __slots__: tuple[str, ...] = ("path", "reason")

    path: Path
    reason: str

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(reason)
        self.path = path
        self.reason = reason

    @override
    def __str__(self) -> str:
        return f"cannot read anchored source {self.path}: {self.reason}"


class AnchoredSourceNotFoundError(AnchoredSourceError):
    """An anchored source component does not exist."""


class AnchoredSourceUnavailableError(AnchoredSourceError):
    """The host cannot provide component-by-component anchored opens."""


@dataclass(frozen=True, slots=True)
class AnchoredRead:
    payload: bytes
    identity: FileIdentity


@final
class AnchoredSourceRoot:
    """One canonical source directory held open across all relative reads."""

    __slots__: tuple[str, ...] = ("path", "descriptor")

    path: Path
    descriptor: int

    def __init__(self, path: Path, descriptor: int) -> None:
        self.path = path
        self.descriptor = descriptor

    @classmethod
    def open(cls, path: Path) -> AnchoredSourceRoot:
        if not _ANCHORED_OPEN_AVAILABLE:
            raise AnchoredSourceUnavailableError(
                path,
                "component no-follow open is unavailable on this platform",
            )
        descriptor = -1
        try:
            before = os.lstat(path)
            descriptor = os.open(path, _DIRECTORY_FLAGS)
            opened = os.fstat(descriptor)
            if not _same_directory(before, opened):
                raise AnchoredSourceError(path, "source-root identity changed")
            return cls(path, descriptor)
        except AnchoredSourceError:
            if descriptor >= 0:
                os.close(descriptor)
            raise
        except OSError as exc:
            if descriptor >= 0:
                os.close(descriptor)
            raise AnchoredSourceError(path, str(exc)) from exc

    def close(self) -> None:
        os.close(self.descriptor)

    def __enter__(self) -> AnchoredSourceRoot:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def read(self, relative: PurePosixPath, maximum: int) -> AnchoredRead:
        display_path = self.path.joinpath(*relative.parts)
        _require_relative(relative, display_path)
        try:
            return self._read(relative, display_path, maximum)
        except AnchoredSourceError:
            raise
        except FileNotFoundError as exc:
            raise AnchoredSourceNotFoundError(display_path, str(exc)) from exc
        except OSError as exc:
            reason = (
                "source component is a symlink"
                if exc.errno == errno.ELOOP
                else str(exc)
            )
            raise AnchoredSourceError(display_path, reason) from exc

    def _read(
        self,
        relative: PurePosixPath,
        display_path: Path,
        maximum: int,
    ) -> AnchoredRead:
        with ExitStack() as opened_descriptors:
            parent_descriptor = self.descriptor
            for component in relative.parts[:-1]:
                parent_descriptor = os.open(
                    component,
                    _DIRECTORY_FLAGS,
                    dir_fd=parent_descriptor,
                )
                _ = opened_descriptors.callback(os.close, parent_descriptor)
            descriptor = os.open(
                relative.name,
                _FILE_FLAGS,
                dir_fd=parent_descriptor,
            )
            _ = opened_descriptors.callback(os.close, descriptor)
            before = os.fstat(descriptor)
            _require_regular(before, display_path, maximum)
            state = _file_state(before)
            first = _read_once(descriptor, display_path, maximum)
            _require_state(os.fstat(descriptor), state, display_path)
            second = _read_once(descriptor, display_path, maximum)
            _require_state(os.fstat(descriptor), state, display_path)
            anchored = os.stat(
                relative.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            _require_state(anchored, state, display_path)
            if first != second:
                raise AnchoredSourceError(
                    display_path,
                    "source changed between stable reads",
                )
            return AnchoredRead(
                first,
                FileIdentity(before.st_dev, before.st_ino, before.st_size),
            )


def _read_once(descriptor: int, path: Path, maximum: int) -> bytes:
    _ = os.lseek(descriptor, 0, os.SEEK_SET)
    payload = bytearray()
    while True:
        chunk = os.read(
            descriptor,
            min(_READ_CHUNK_BYTES, maximum + 1 - len(payload)),
        )
        if not chunk:
            return bytes(payload)
        payload.extend(chunk)
        if len(payload) > maximum:
            raise AnchoredSourceError(path, f"size exceeds limit {maximum}")


def _require_relative(relative: PurePosixPath, path: Path) -> None:
    if (
        relative.is_absolute()
        or not relative.parts
        or any(component in {"", ".", ".."} for component in relative.parts)
    ):
        raise AnchoredSourceError(path, "source path is not canonical relative text")


def _require_regular(details: os.stat_result, path: Path, maximum: int) -> None:
    if not stat.S_ISREG(details.st_mode):
        raise AnchoredSourceError(path, "source is not a regular file")
    if details.st_size > maximum:
        raise AnchoredSourceError(path, f"size exceeds limit {maximum}")


def _require_state(
    details: os.stat_result,
    expected: _FileState,
    path: Path,
) -> None:
    if not stat.S_ISREG(details.st_mode) or _file_state(details) != expected:
        raise AnchoredSourceError(path, "source identity or metadata changed")


def _file_state(details: os.stat_result) -> _FileState:
    return (
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
        details.st_mode,
    )


def _same_directory(first: os.stat_result, second: os.stat_result) -> bool:
    return bool(
        stat.S_ISDIR(first.st_mode)
        and stat.S_ISDIR(second.st_mode)
        and (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)
    )


__all__ = (
    "AnchoredRead",
    "AnchoredSourceError",
    "AnchoredSourceNotFoundError",
    "AnchoredSourceRoot",
    "AnchoredSourceUnavailableError",
)
