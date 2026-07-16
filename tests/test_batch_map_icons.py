"""Per-map icon path reconciliation tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from tests.batch_map_processing_fixture import loaded_map
import w3xtool.batch_map_icons as batch_map_icons
from w3xtool.batch_icon_export import (
    IconExportRecord,
    IconExportState,
    IconKind,
)
from w3xtool.icon_evidence_models import IconResolutionLayer
from w3xtool.map_data import GameObjectFieldEvidence, MapData


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


def test_export_map_icons_returns_exports_with_the_immutable_map_index(
    tmp_path: Path,
) -> None:
    # Given
    root, _source = loaded_map("map.w3x", r"Icons\BTNHero.blp")
    _attach_icon_evidence(root)

    # When
    evidence = batch_map_icons.export_map_icons(root, (root,), tmp_path, None)

    # Then
    assert evidence.index == root.icon_evidence
    assert len(evidence.index.resolved) == 1
    assert len(evidence.index.anonymous) == 1
    named = next(record for record in evidence.exports if record.kind is IconKind.NAMED)
    assert named.resolution_layer is IconResolutionLayer.CURRENT_MAP


def test_export_map_icons_merges_exact_field_references_for_one_payload(
    tmp_path: Path,
) -> None:
    # Given
    root, _source = loaded_map("map.w3x", r"Icons\BTNHero.blp")
    _attach_icon_evidence(root)
    original = root.objects["技能"][0]
    root.objects["技能"].append(replace(original, obj_id="A002", name="第二个引用对象"))

    # When
    evidence = batch_map_icons.export_map_icons(root, (root,), tmp_path, None)

    # Then
    named = tuple(
        record for record in evidence.exports if record.kind is IconKind.NAMED
    )
    assert len(named) == 1
    assert tuple(reference.object_id for reference in named[0].objects) == (
        "A001",
        "A002",
    )
    assert len(evidence.index.resolved) == 2


def _attach_icon_evidence(md: MapData) -> None:
    obj = md.objects["技能"][0]
    evidence = GameObjectFieldEvidence(
        key="aart",
        label="图标 - 普通",
        value=obj.icon,
        source="war3map.w3a",
        source_priority=40,
        value_type="icon",
    )
    obj.field_evidence = (evidence,)
    obj.icon_field_evidence = evidence
