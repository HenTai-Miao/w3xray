"""Opt-in integration against a real Windows Warcraft III installation."""

from __future__ import annotations

import os
import sys
import unittest

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

    # Then: all three resource classes are non-empty.
    assert trigger_data
    assert trigger_strings
    assert icon
