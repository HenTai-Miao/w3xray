"""Reference inheritance labels follow proved map versus campaign scopes."""

from __future__ import annotations

from pathlib import Path
import struct

import pytest

from gametool.extraction_profile import ExtractionProfile
from gametool.knowledge_pack import write_knowledge_pack_report
from gametool.map_loader import load_map
from gametool.reference_catalog import load_reference_catalog
from tests.skin_layers_fixture import mpq, object_file


@pytest.mark.parametrize("reference_source", ("map", "pack"))
@pytest.mark.parametrize("campaign", (False, True))
def test_reference_inherited_values_keep_their_actual_scope(
    tmp_path: Path, reference_source: str, campaign: bool
) -> None:
    parent = object_file(
        "w3t",
        (
            ("unam", "parent name", 0, 0),
            ("ides", "parent description", 0, 0),
            ("igol", 91, 0, 0),
        ),
        code="I001",
        base="ratf",
    )
    child = object_file("w3t", (("igol", 7, 0, 0),), code="I002", base="I001")
    path = tmp_path / ("source.w3n" if campaign else "source.w3x")
    source_bytes = (
        mpq(
            {
                "war3campaign.w3t": parent,
                "Chapter.w3x": mpq({"war3map.w3t": child}),
            }
        )
        if campaign
        else mpq(
            {"war3map.w3t": struct.pack("<iii", 2, 0, 2) + child[12:] + parent[12:]}
        )
    )
    path.write_bytes(source_bytes)
    stamp = path.stat().st_mtime_ns
    loaded = load_map(str(path))
    pack = tmp_path / "pack"
    try:
        md = loaded.sub_maps[0] if campaign else loaded
        item = md.obj_identity_index[("物品", "I002")]
        assert item.name == "parent name" and item.field_values["igol"] == "7"
        assert any(
            row.key == "igol" and row.value == "91" and row.state == "overridden"
            for row in item.field_evidence
        )
        if reference_source == "pack":
            written = write_knowledge_pack_report(
                md,
                str(pack),
                game_data_path=str(tmp_path / "absent-client"),
                profile=ExtractionProfile(),
            )
            assert written.failed_count == 0, written.first_failure
    finally:
        loaded.close()
    catalog = (
        load_reference_catalog(pack_dir=pack)
        if reference_source == "pack"
        else load_reference_catalog(map_path=path)
    )
    record = next(
        row for row in catalog.records if row.category == "物品" and row.id == "I002"
    )
    overridden = [
        row for row in record.values if row.key == "igol" and row.value == "91"
    ]
    assert overridden
    assert {row.state for row in overridden} == {
        "overridden-campaign" if campaign else "overridden"
    }
    assert any(
        row.key == "ides"
        and row.value == "parent description"
        and row.state == ("campaign-inherited" if campaign else "inherited-evidence")
        for row in record.values
    )
    if not campaign:
        assert not any("campaign" in row.state for row in record.values)
    assert path.read_bytes() == source_bytes and path.stat().st_mtime_ns == stamp
