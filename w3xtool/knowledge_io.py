"""Shared filesystem helpers for knowledge-pack writers."""

from __future__ import annotations

import os
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from contextvars import ContextVar
from typing import final

from .knowledge_results import KnowledgeWriteItem, KnowledgeWriteReport
from .presentation_safety import redact_user_text, single_line_text, tsv_cell
from .safe_output import write_bytes_safely, write_text_safely
from .safe_output_models import SafeWriteResult, SafeWriteStatus


@final
class KnowledgeWriteRecorder:
    """Mutable session accumulator whose report exposes final path state."""

    def __init__(self, publication_root: str, report_root: str) -> None:
        self._publication_root = os.path.abspath(publication_root)
        self._report_root = os.path.abspath(report_root)
        self._items: dict[str, KnowledgeWriteItem] = {}

    def record(self, out_dir: str, name: str, result: SafeWriteResult) -> None:
        """Record the final result for the requested pack-relative path."""
        path = self._relative_path(self._report_root, out_dir, name)
        self.record_relative(path, result)

    def record_relative(self, path: str, result: SafeWriteResult) -> None:
        """Record a result already anchored to this session's relative path."""
        written = result.status is SafeWriteStatus.WRITTEN
        error = None if written else _clean_write_error(
            result.error or result.status.value,
            self._publication_root,
        )
        self._items[path] = KnowledgeWriteItem(path, written, result.size, error)

    def target(self, out_dir: str, name: str) -> tuple[str, str]:
        """Return the held publication root and one pack-relative destination."""
        return (
            self._publication_root,
            self._relative_path(self._publication_root, out_dir, name),
        )

    def report(self) -> KnowledgeWriteReport:
        """Return an immutable, deterministic snapshot of this session."""
        items = tuple(self._items[path] for path in sorted(self._items, key=str.casefold))
        return KnowledgeWriteReport(items)

    @staticmethod
    def _relative_path(root: str, out_dir: str, name: str) -> str:
        try:
            parent = os.path.relpath(os.path.abspath(out_dir), root)
        except ValueError:
            parent = os.path.basename(os.path.abspath(out_dir))
        parts = [] if parent == "." else [parent.replace("\\", "/")]
        parts.append(name.replace("\\", "/").lstrip("/"))
        return "/".join(part.strip("/") for part in parts if part.strip("/"))


_ACTIVE_RECORDER: ContextVar[KnowledgeWriteRecorder | None] = ContextVar(
    "knowledge_write_recorder",
    default=None,
)


@contextmanager
def knowledge_write_session(
    out_dir: str,
    *,
    publication_root: str | None = None,
) -> Generator[KnowledgeWriteRecorder]:
    """Capture writes below ``out_dir`` and restore any outer session."""
    recorder = KnowledgeWriteRecorder(publication_root or out_dir, out_dir)
    token = _ACTIVE_RECORDER.set(recorder)
    try:
        yield recorder
    finally:
        _ACTIVE_RECORDER.reset(token)


def record_safe_write(out_dir: str, name: str, result: SafeWriteResult) -> None:
    """Record a safe-output result when a publication session is active."""
    recorder = _ACTIVE_RECORDER.get()
    if recorder is not None:
        recorder.record(out_dir, name, result)


def write_text(out_dir: str, name: str, text: str) -> int:
    """Write UTF-8 text under the pack directory and return one file count."""
    recorder = _ACTIVE_RECORDER.get()
    if recorder is None:
        result = write_text_safely(out_dir, name, text)
    else:
        root, relative = recorder.target(out_dir, name)
        result = write_text_safely(root, relative, text)
        recorder.record(out_dir, name, result)
    return int(result.status is SafeWriteStatus.WRITTEN)


def write_bytes(out_dir: str, name: str, data: bytes) -> SafeWriteResult:
    """Write binary pack content through the active publication root."""
    recorder = _ACTIVE_RECORDER.get()
    if recorder is None:
        return write_bytes_safely(out_dir, name, data)
    root, relative = recorder.target(out_dir, name)
    result = write_bytes_safely(root, relative, data)
    recorder.record(out_dir, name, result)
    return result


def safe_filename(name: str) -> str:
    """Return a filename safe on Windows and Unix-like filesystems."""
    display_name = single_line_text(name, max_chars=240)
    cleaned = "".join(
        "_" if char in '<>:"/\\|?*' else char
        for char in display_name
    ).strip(" .")
    return cleaned or "未命名"


def tsv(value: str) -> str:
    """Escape tabs and newlines for single-line TSV cells."""
    return tsv_cell(value)


def format_lines(lines: Iterable[str]) -> str:
    """Return one item per line with a trailing newline."""
    return "\n".join(lines) + "\n"


def _clean_write_error(error: str, root: str) -> str:
    cleaned = error.replace(os.path.realpath(root), "<output>").replace(root, "<output>")
    return redact_user_text(cleaned)[:512]
