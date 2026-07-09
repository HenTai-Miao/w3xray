"""Shared filesystem helpers for knowledge-pack writers."""

from __future__ import annotations

from collections.abc import Iterable
import os


def write_text(out_dir: str, name: str, text: str) -> int:
    """Write UTF-8 text under the pack directory and return one file count."""
    path = os.path.join(out_dir, name)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return 1


def safe_filename(name: str) -> str:
    """Return a filename safe on Windows and Unix-like filesystems."""
    cleaned = "".join("_" if char in '<>:"/\\|?*' else char for char in name).strip()
    return cleaned or "未命名"


def tsv(value: str) -> str:
    """Escape tabs and newlines for single-line TSV cells."""
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def format_lines(lines: Iterable[str]) -> str:
    """Return one item per line with a trailing newline."""
    return "\n".join(lines) + "\n"
