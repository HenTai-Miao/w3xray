"""Fail-closed construction of security-sensitive descriptor open flags."""

from __future__ import annotations

import os
from typing import override


class DescriptorFlagUnavailableError(OSError):
    """A required no-follow descriptor flag is unavailable."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    @override
    def __str__(self) -> str:
        return self.detail


def directory_read_flags() -> int:
    """Return the complete no-follow directory-read flag set."""
    return _required_flags(os.O_RDONLY, "O_DIRECTORY", "O_CLOEXEC", "O_NOFOLLOW")


def file_read_flags() -> int:
    """Return the complete no-follow regular-file read flag set."""
    return _required_flags(os.O_RDONLY | _optional_binary(), "O_CLOEXEC", "O_NOFOLLOW")


def staged_create_flags() -> int:
    """Return the complete exclusive no-follow staged-file flag set."""
    return _required_flags(
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        "O_CLOEXEC",
        "O_NOFOLLOW",
    )


def _required_flags(base: int, *names: str) -> int:
    flags = base
    for name in names:
        value = getattr(os, name, None)
        if not isinstance(value, int):
            raise DescriptorFlagUnavailableError(
                f"required descriptor flag is unavailable: {name}"
            )
        flags |= value
    return flags


def _optional_binary() -> int:
    value = getattr(os, "O_BINARY", None)
    return value if isinstance(value, int) else 0


__all__ = (
    "DescriptorFlagUnavailableError",
    "directory_read_flags",
    "file_read_flags",
    "staged_create_flags",
)
