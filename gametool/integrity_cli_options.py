"""Closed typed option parser for the three integrity CLI actions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .integrity_snapshot_models import SnapshotRoot
from .integrity_utf8 import IntegrityUtf8Error, require_utf8_text


class IntegrityCliOptionError(ValueError):
    """The integrity command shape is incomplete or ambiguous."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class SnapshotCliOptions:
    """Explicit labeled roots and safe report destination."""

    roots: tuple[SnapshotRoot, ...]
    output: Path


@dataclass(frozen=True, slots=True)
class VerifyCliOptions:
    """One exact saved snapshot selected for verification."""

    snapshot: Path


@dataclass(frozen=True, slots=True)
class RetainedCacheCliOptions:
    """One explicit active cache and safe report destination."""

    active_root: Path
    output: Path


type IntegrityCliOptions = (
    SnapshotCliOptions | VerifyCliOptions | RetainedCacheCliOptions
)


def parse_integrity_cli_options(argv: Sequence[str]) -> IntegrityCliOptions:
    """Parse only the exact snapshot, verify, and retained-cache grammars."""
    try:
        for value in argv:
            require_utf8_text(value, "integrity argument")
    except IntegrityUtf8Error as exc:
        raise IntegrityCliOptionError(str(exc)) from exc
    if not argv:
        raise IntegrityCliOptionError("缺少完整性操作")
    action = argv[0]
    if action == "snapshot":
        return _parse_snapshot(argv[1:])
    if action == "verify":
        return _parse_verify(argv[1:])
    if action == "retained-cache":
        return _parse_retained_cache(argv[1:])
    raise IntegrityCliOptionError(f"不支持的完整性操作：{action}")


def _parse_snapshot(argv: Sequence[str]) -> SnapshotCliOptions:
    roots: list[SnapshotRoot] = []
    output: Path | None = None
    index = 0
    while index < len(argv):
        option = argv[index]
        if option not in {"--root", "--output"}:
            raise IntegrityCliOptionError(f"不支持的参数：{option}")
        if index + 1 >= len(argv) or not argv[index + 1]:
            raise IntegrityCliOptionError(f"参数缺少值：{option}")
        value = argv[index + 1]
        if option == "--root":
            label, separator, path = value.partition("=")
            if not separator or not label or not path:
                raise IntegrityCliOptionError("--root 必须是 LABEL=PATH")
            roots.append(SnapshotRoot(label, Path(path)))
        elif output is None:
            output = Path(value)
        else:
            raise IntegrityCliOptionError("参数不能重复：--output")
        index += 2
    if not roots or output is None:
        raise IntegrityCliOptionError("snapshot 需要 --root 和 --output")
    return SnapshotCliOptions(tuple(roots), output)


def _parse_verify(argv: Sequence[str]) -> VerifyCliOptions:
    if len(argv) != 2 or argv[0] != "--snapshot" or not argv[1]:
        raise IntegrityCliOptionError("verify 仅接受一个 --snapshot FILE")
    return VerifyCliOptions(Path(argv[1]))


def _parse_retained_cache(argv: Sequence[str]) -> RetainedCacheCliOptions:
    values: dict[str, str] = {}
    index = 0
    while index < len(argv):
        option = argv[index]
        if option not in {"--active-root", "--output"}:
            raise IntegrityCliOptionError(f"不支持的参数：{option}")
        if option in values:
            raise IntegrityCliOptionError(f"参数不能重复：{option}")
        if index + 1 >= len(argv) or not argv[index + 1]:
            raise IntegrityCliOptionError(f"参数缺少值：{option}")
        values[option] = argv[index + 1]
        index += 2
    if set(values) != {"--active-root", "--output"}:
        raise IntegrityCliOptionError("retained-cache 需要 --active-root 和 --output")
    return RetainedCacheCliOptions(
        Path(values["--active-root"]),
        Path(values["--output"]),
    )


__all__ = (
    "IntegrityCliOptionError",
    "RetainedCacheCliOptions",
    "SnapshotCliOptions",
    "VerifyCliOptions",
    "parse_integrity_cli_options",
)
