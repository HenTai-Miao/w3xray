"""No-follow descriptor bindings for absolute integrity paths."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
from types import TracebackType
from typing import Final, Literal, Self, override


_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


class IntegrityPathBindingError(OSError):
    """A requested path could not retain its no-follow directory binding."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    @override
    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class BoundDirectoryPath:
    """Held root-to-leaf directory descriptors and exact name identities."""

    path: Path
    descriptors: tuple[int, ...]
    names: tuple[str, ...]
    identities: tuple[tuple[int, int, int], ...]

    @property
    def descriptor(self) -> int:
        """Return the held descriptor for the requested directory."""
        return self.descriptors[-1]

    def __enter__(self) -> Self:
        """Verify and return the live binding."""
        try:
            self.require_current()
        except IntegrityPathBindingError:
            self.close()
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        """Re-prove successful use and close every held descriptor."""
        del exc_value, traceback
        try:
            if exc_type is None:
                self.require_current()
        finally:
            self.close()
        return False

    def close(self) -> None:
        """Close every held descriptor exactly once per binding owner."""
        for descriptor in reversed(self.descriptors):
            os.close(descriptor)

    def require_current(self) -> None:
        """Re-prove every held descriptor and its anchored public name."""
        try:
            root = os.fstat(self.descriptors[0])
            if not stat.S_ISDIR(root.st_mode):
                raise IntegrityPathBindingError("filesystem root is not a directory")
            for index, expected in enumerate(self.identities):
                held = os.fstat(self.descriptors[index + 1])
                named = os.stat(
                    self.names[index],
                    dir_fd=self.descriptors[index],
                    follow_symlinks=False,
                )
                if (
                    not stat.S_ISDIR(held.st_mode)
                    or not stat.S_ISDIR(named.st_mode)
                    or _binding_identity(held) != expected
                    or _binding_identity(named) != expected
                ):
                    raise IntegrityPathBindingError("directory path binding changed")
        except IntegrityPathBindingError:
            raise
        except OSError as exc:
            raise IntegrityPathBindingError(
                "directory path binding became unavailable"
            ) from exc


def bind_directory_path(
    requested: Path,
    *,
    create: bool = False,
) -> BoundDirectoryPath:
    """Open every absolute path component without following symlinks."""
    path = Path(os.path.abspath(requested.expanduser()))
    descriptors: list[int] = []
    names: list[str] = []
    identities: list[tuple[int, int, int]] = []
    try:
        descriptors.append(os.open(os.sep, _DIRECTORY_FLAGS))
        for name in path.parts[1:]:
            parent = descriptors[-1]
            try:
                descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(name, 0o700, dir_fd=parent)
                descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent)
            details = os.fstat(descriptor)
            if not stat.S_ISDIR(details.st_mode):
                os.close(descriptor)
                raise IntegrityPathBindingError("path component is not a directory")
            descriptors.append(descriptor)
            names.append(name)
            identities.append(_binding_identity(details))
        return BoundDirectoryPath(
            path,
            tuple(descriptors),
            tuple(names),
            tuple(identities),
        )
    except IntegrityPathBindingError:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        raise
    except OSError as exc:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        raise IntegrityPathBindingError(f"cannot bind directory path: {path}") from exc


def stable_stat(details: os.stat_result) -> tuple[int, int, int, int, int, int]:
    """Return the exact integrity proof tuple for files and directories."""
    return (
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
        details.st_mode,
    )


def _binding_identity(details: os.stat_result) -> tuple[int, int, int]:
    return details.st_dev, details.st_ino, details.st_mode


__all__ = (
    "BoundDirectoryPath",
    "IntegrityPathBindingError",
    "bind_directory_path",
    "stable_stat",
)
