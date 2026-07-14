"""Per-map icon path reconciliation tests."""

from __future__ import annotations

from pathlib import Path

import w3xtool.batch_map_icons as batch_map_icons
from w3xtool.batch_icon_export import (
    IconExportRecord,
    IconExportState,
    IconKind,
)


def test_canonicalize_icon_paths_records_actual_filesystem_casing(
    tmp_path: Path,
) -> None:
    # Given
    original = Path("图标/原始/具名/ReplaceableTextures/CommandButtons/BTNtemp.blp")
    png = Path("图标/PNG/具名/ReplaceableTextures/CommandButtons/BTNtemp.png")
    for relative in (original, png):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fixture")
    record = IconExportRecord(
        kind=IconKind.NAMED,
        requested_path=r"replaceableTextures\CommandButtons\BTNtemp.blp",
        resolved_path=r"replaceableTextures\CommandButtons\BTNtemp.blp",
        source_path="war3.mpq",
        block_index=None,
        sha256="a" * 64,
        original_relative_path=str(original).replace(
            "ReplaceableTextures", "replaceableTextures"
        ),
        png_relative_path=str(png).replace(
            "ReplaceableTextures", "replaceableTextures"
        ),
        original_written=True,
        png_written=True,
        state=IconExportState.COMPLETE,
        error="",
        objects=(),
    )

    # When
    (canonical,) = batch_map_icons.canonicalize_icon_paths(tmp_path, (record,))

    # Then
    assert canonical.original_relative_path == original.as_posix()
    assert canonical.png_relative_path == png.as_posix()
