"""Paged CASC inventory and selected-entry export tests."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass, field
import importlib
from pathlib import Path

from w3xtool.casclib_enumeration import CascEntry, CascNameType


def _entry(name: str, name_type: CascNameType) -> CascEntry:
    return CascEntry(
        name=name,
        name_type=name_type,
        file_data_id=123 if name_type is CascNameType.FILE_DATA_ID else None,
        ckey="01" * 16,
        ekey="02" * 16,
        size=4,
        is_local=True,
        locale_flags=0,
        content_flags=0,
    )


@dataclass(slots=True)  # noqa: MUTABLE_OK - fake records read requests.
class FakeInventorySource:
    entries: tuple[CascEntry, ...]
    reads: list[str] = field(default_factory=list)

    def iter_entries(
        self,
        mask: str = "*",
        listfile: str | None = None,
    ) -> Generator[CascEntry, None, None]:
        del listfile
        for entry in self.entries:
            if mask == "*" or mask.strip("*").lower() in entry.name.lower():
                yield entry

    def read_file(self, name: str) -> bytes:
        self.reads.append(name)
        return b"data"


def test_inventory_pages_include_resolved_and_unknown_root_entries() -> None:
    # Given: a full-root source with one path and one anonymous FileDataID.
    entries = (
        _entry("UI\\TriggerData.txt", CascNameType.FULL),
        _entry("File00000123", CascNameType.FILE_DATA_ID),
    )
    casc_browser = importlib.import_module("w3xtool.casc_browser")
    browser_type = getattr(casc_browser, "CascBrowserModel")
    browser = browser_type(FakeInventorySource(entries), page_size=1)

    # When: the inventory is consumed page by page.
    first = browser.next_page()
    second = browser.next_page()
    final = browser.next_page()

    # Then: no entry type is hidden and completion is explicit.
    assert first.entries == (entries[0],)
    assert second.entries == (entries[1],)
    assert not first.is_complete
    assert second.is_complete
    assert final.entries == ()
    assert final.is_complete


def test_export_selected_unknown_entry_uses_stable_read_name(tmp_path: Path) -> None:
    # Given: a selected unknown-path entry that remains addressable by FileDataID.
    entry = _entry("File00000123", CascNameType.FILE_DATA_ID)
    source = FakeInventorySource((entry,))
    casc_browser = importlib.import_module("w3xtool.casc_browser")
    browser_type = getattr(casc_browser, "CascBrowserModel")
    browser = browser_type(source, page_size=10)

    # When: the selected entry is exported.
    exported = browser.export_entry(entry, tmp_path)

    # Then: CascLib is called with the stable ID and output stays under the chosen root.
    assert source.reads == ["File00000123"]
    assert exported == tmp_path / "UnknownCASC" / "File00000123"
    assert exported.read_bytes() == b"data"
