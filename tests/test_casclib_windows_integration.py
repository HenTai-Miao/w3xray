"""Opt-in integration against a real Windows Warcraft III installation."""

from __future__ import annotations

import os
import sys
import unittest

from w3xtool.casclib_api import MAX_CASC_FILE_SIZE
from w3xtool.casclib_enumeration import CascNameType
from w3xtool.casclib_source import CascLibDataSource


@unittest.skipUnless(
    sys.platform == "win32" and bool(os.getenv("W3XRAY_WAR3_DIR")),
    "需要 Windows Warcraft III CASC 安装",
)
def test_real_install_reads_trigger_schema_and_icon() -> None:
    # Given: an explicitly selected real Windows Warcraft III installation.
    root = os.environ["W3XRAY_WAR3_DIR"]

    # When: CascLib opens the install and reads runtime game resources.
    with CascLibDataSource(root) as source:
        trigger_data = source.read_file("UI/TriggerData.txt")
        trigger_strings = source.read_file("UI/TriggerStrings.txt")
        icon = source.read_file("ReplaceableTextures/CommandButtons/BTNSelectHeroOn.blp")
        entries = source.iter_entries()
        unknown = None
        try:
            first_root_entry = next(entries)
            for entry in entries:
                if (
                    entry.name_type is not CascNameType.FULL
                    and entry.is_local
                    and entry.size is not None
                    and entry.size <= MAX_CASC_FILE_SIZE
                ):
                    unknown = entry
                    break
        finally:
            entries.close()
        assert unknown is not None
        unknown_payload = source.read_file(unknown.read_name)

    # Then: resources and one synthetic Root identity are both genuinely readable.
    assert trigger_data
    assert trigger_strings
    assert icon
    assert first_root_entry.read_name
    assert len(unknown_payload) == unknown.size
