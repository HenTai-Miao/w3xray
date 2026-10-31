"""Physical, non-reparse source inventory shared by offline save entry points."""

from __future__ import annotations

import os
from pathlib import Path
import stat

from .windows_output_paths import native_output_path, validate_output_root


def _reparse(metadata: os.stat_result) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def save_source_path_error(path: str | Path) -> str:
    """Inspect each lexical component without following a reparse point."""
    try:
        validate_output_root(os.fspath(path))
    except (TypeError, ValueError) as exc:
        return f"拒绝不明确的来源路径：{path} ({exc})"
    path = Path(path)
    absolute = path.absolute()
    components = list(reversed((absolute, *absolute.parents)))
    for component in components:
        try:
            metadata = os.lstat(native_output_path(os.path.abspath(component)))
        except OSError as exc:
            return f"不可读取来源路径：{component} ({exc})"
        if _reparse(metadata):
            return f"拒绝来源重解析点/符号链接 (reparse point)：{component}"
    return ""


def iter_save_source_files(
    source: Path,
    *,
    suffixes: frozenset[str] | None = None,
) -> tuple[tuple[Path, ...], list[str]]:
    """Traverse only physical regular files; reject junctions before scandir.

    Windows directory junctions are reparse points but not symbolic links.
    The explicit stack avoids os.walk's platform-specific link-following
    behavior. Every popped directory is checked again before enumeration.
    """
    diagnostics: list[str] = []
    problem = save_source_path_error(source)
    if problem:
        return (), [problem]
    try:
        metadata = os.lstat(native_output_path(os.path.abspath(source)))
    except OSError as exc:
        return (), [f"不可读取来源：{source} ({exc})"]
    if stat.S_ISREG(metadata.st_mode):
        return (
            (source,) if suffixes is None or source.suffix.lower() in suffixes else ()
        ), []
    if not stat.S_ISDIR(metadata.st_mode):
        return (), [f"来源不是普通文件或目录：{source}"]
    pending = [source]
    files: list[Path] = []
    while pending:
        directory = pending.pop()
        problem = save_source_path_error(directory)
        if problem:
            diagnostics.append(problem)
            continue
        try:
            with os.scandir(native_output_path(os.path.abspath(directory))) as entries:
                ordered = sorted(entries, key=lambda entry: entry.name)
        except OSError as exc:
            diagnostics.append(f"目录不可完整读取：{directory} ({exc})")
            continue
        directories: list[Path] = []
        for entry in ordered:
            # Preserve the caller's logical spelling, not the native I/O prefix.
            path = directory / entry.name
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                diagnostics.append(f"不可读取来源记录：{path} ({exc})")
                continue
            if _reparse(metadata):
                diagnostics.append(f"拒绝来源重解析点/符号链接 (reparse point)：{path}")
                continue
            if stat.S_ISDIR(metadata.st_mode):
                directories.append(path)
            elif stat.S_ISREG(metadata.st_mode):
                if suffixes is None or path.suffix.lower() in suffixes:
                    files.append(path)
            else:
                diagnostics.append(f"跳过非普通来源文件：{path}")
        pending.extend(reversed(directories))
    return tuple(files), diagnostics
