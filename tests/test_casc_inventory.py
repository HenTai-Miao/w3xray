"""CASC full-root inventory export contracts."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
import importlib
import os
from pathlib import Path
import subprocess
import sys

from w3xtool.casclib_enumeration import CascEntry, CascNameType


def _entry(name: str, name_type: CascNameType) -> CascEntry:
    return CascEntry(
        name=name,
        name_type=name_type,
        file_data_id=77 if name_type is CascNameType.FILE_DATA_ID else None,
        ckey="ab" * 16,
        ekey="cd" * 16,
        size=123,
        is_local=True,
        locale_flags=None,
        content_flags=4,
    )


@dataclass(frozen=True, slots=True)
class FakeInventorySource:
    entries: tuple[CascEntry, ...]

    def iter_entries(
        self,
        mask: str = "*",
        listfile: str | None = None,
    ) -> Generator[CascEntry, None, None]:
        del mask, listfile
        yield from self.entries


@dataclass(frozen=True, slots=True)
class StreamingProbeSource:
    output_dir: Path

    def iter_entries(
        self,
        mask: str = "*",
        listfile: str | None = None,
    ) -> Generator[CascEntry, None, None]:
        del mask, listfile
        yield _entry("A" * 100_000, CascNameType.FULL)
        staged = tuple(self.output_dir.glob(".w3xray-stage-*.tmp"))
        assert staged
        assert max(path.stat().st_size for path in staged) > 100_000
        yield _entry("UI\\TriggerData.txt", CascNameType.FULL)


def test_inventory_writes_bounded_chunks_while_root_is_still_enumerating(
    tmp_path: Path,
) -> None:
    # Given: a source that checks the staged output before yielding its last row.
    module = importlib.import_module("w3xtool.casc_inventory")
    output = tmp_path / "streamed.tsv"

    # When: the full Root inventory is exported.
    summary = module.write_casc_inventory(StreamingProbeSource(tmp_path), output)

    # Then: rows were written before enumeration ended and only the final file remains.
    assert summary.total == 2
    assert output.stat().st_size > 100_000
    assert not tuple(tmp_path.glob(".w3xray-stage-*.tmp"))


def test_inventory_tsv_preserves_resolved_paths_ids_and_content_keys(tmp_path: Path) -> None:
    # Given: a root path plus an unknown-path entry addressable by FileDataID.
    entries = (
        _entry("UI\\TriggerData.txt", CascNameType.FULL),
        _entry("File00000077", CascNameType.FILE_DATA_ID),
    )
    module = importlib.import_module("w3xtool.casc_inventory")
    output = tmp_path / "casc-root.tsv"

    # When: the entire streaming root is exported.
    summary = module.write_casc_inventory(FakeInventorySource(entries), output)

    # Then: the report is complete and every entry remains addressable.
    text = output.read_text(encoding="utf-8")
    assert summary.total == 2
    assert summary.resolved_paths == 1
    assert summary.unknown_paths == 1
    assert "UI\\TriggerData.txt\tfull" in text
    assert "File00000077\tfile_data_id\t77" in text
    assert "ab" * 16 in text


def test_inventory_limit_is_explicitly_reported_not_silently_complete(tmp_path: Path) -> None:
    # Given: more root entries than the caller's diagnostic preview limit.
    entries = tuple(_entry(f"File{index:08d}", CascNameType.FILE_DATA_ID) for index in range(3))
    module = importlib.import_module("w3xtool.casc_inventory")

    # When: inventory is intentionally limited to two rows.
    summary = module.write_casc_inventory(
        FakeInventorySource(entries),
        tmp_path / "limited.tsv",
        limit=2,
    )

    # Then: callers can distinguish a preview from a complete Root walk.
    assert summary.total == 2
    assert summary.was_limited


def test_main_casc_help_exposes_inventory_and_selected_extract_commands() -> None:
    # Given: the same public entrypoint used by source and packaged builds.
    root = Path(__file__).resolve().parents[1]

    # When: a user requests CASC command help on any platform.
    result = subprocess.run(
        [sys.executable, str(root / "main.py"), "casc", "--help"],
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        check=False,
        timeout=5,
    )

    # Then: it does not launch the GUI and documents both usable operations.
    assert result.returncode == 0
    assert "inventory" in result.stdout
    assert "extract" in result.stdout
