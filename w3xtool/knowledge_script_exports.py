"""Script index and readable script exports for knowledge packs."""

from __future__ import annotations

from collections.abc import Iterable

from .api import MapData
from .knowledge_io import safe_filename, write_text
from .safe_output import safe_relative_path
from .script_text_export import ReadableScriptExport, build_readable_script_exports


def write_readable_scripts(md: MapData, out_dir: str) -> int:
    """Write scripts with TRIGSTR references restored where possible."""
    return write_script_exports(build_readable_script_exports(md), out_dir)


def write_script_exports(
    scripts: Iterable[ReadableScriptExport],
    out_dir: str,
) -> int:
    """Write prebuilt script exports after validating their original names."""
    count = 0
    for item in scripts:
        relative = safe_relative_path(item.name)
        if relative is None:
            continue
        count += write_text(out_dir, safe_filename(relative.name), item.text)
    return count


def format_script_index(md: MapData) -> str:
    """Return script filenames, line counts and character counts."""
    lines = [f"脚本文件：{len(md.scripts)}"]
    for name, text in sorted(md.scripts.items()):
        line_count = len(text.splitlines())
        lines.append(f"{name}\t{line_count} 行\t{len(text)} 字符")
    return "\n".join(lines) + "\n"


def all_script_text(md: MapData) -> str:
    """Return all script text joined for static clue scanners."""
    return "\n".join(md.scripts.values())
