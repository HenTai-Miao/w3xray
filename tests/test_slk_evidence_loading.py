"""SLK source conflicts and explicit empty overrides in the real object pipeline."""

from __future__ import annotations

import json

import pytest

from gametool.item_relation_fields import object_field_relations
from gametool.map_data import MapData
from gametool.object_candidate_models import (
    ObjectCandidate,
    ObjectFieldValue,
    ObjectSourceKind,
)
from gametool.object_candidate_text_tables import collect_slk_candidates
from gametool.object_pipeline import populate_object_pipeline
from gametool.slk_objects import parse_category_evidence, parse_category_objects
from gametool.slkmeta import build_slk_inventory


class _Archive:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.path = "synthetic.w3x"
        self._data = b""

    def has_file(self, name: str) -> bool:
        return name in self.files

    def read_file(self, name: str) -> bytes:
        return self.files[name]

    def list_files(self) -> list[str]:
        return list(self.files)

    def close(self) -> None:
        pass


def _slk(
    header: str = "unitID", field: str = "Name", value: str = '"Footman"'
) -> bytes:
    return (
        f'ID;P\r\nC;X1;Y1;K"{header}"\r\nC;X2;Y1;K"{field}"\r\n'
        f'C;X1;Y2;K"hfoo"\r\nC;X2;Y2;K{value}\r\nE\r\n'
    ).encode()


def _issues(md: MapData) -> list[dict[str, object]]:
    return [
        json.loads(diagnostic.message.removeprefix("ComponentParseError: "))
        for diagnostic in md.diagnostics
    ]


def test_map_loader_retains_full_conflicting_and_opaque_records_in_diagnostics() -> (
    None
):
    payload = _slk().replace(
        b"E\r\n", b'C;X2;Y2;K"Other"\r\nC;X99;Y2;K"opaque\ttext"\r\nE\r\n'
    )
    archive = _Archive({"UnitData.slk": payload})
    md = MapData("synthetic.w3x", "synthetic")
    assert parse_category_objects(archive, "单位", md=md) == {"hfoo": {}}
    issues = _issues(md)
    assert {issue["code"] for issue in issues} >= {"duplicate_cell", "unnamed_column"}
    assert all(issue["category"] == "单位" for issue in issues)
    combined = json.dumps(issues, ensure_ascii=False)
    assert "Footman" in combined and "Other" in combined and "opaque\\ttext" in combined
    source = parse_category_evidence(archive, "单位")[0]
    assert source.source == "UnitData.slk" and source.category == "单位"
    assert source.table.raw_bytes == payload


def test_cross_file_conflicts_do_not_overwrite_or_restore_an_uncertain_field() -> None:
    first = _slk().replace(b"E\r\n", b'C;X3;Y1;K"race"\r\nC;X3;Y2;K"human"\r\nE\r\n')
    archive = _Archive({"UnitData.slk": first, "UnitUI.slk": _slk(value='"Other"')})
    md = MapData("synthetic.w3x", "synthetic")
    assert parse_category_objects(archive, "单位", md=md) == {"hfoo": {"race": "human"}}
    issue = next(
        issue for issue in _issues(md) if issue["code"] == "cross_source_field_conflict"
    )
    encoded = json.dumps(issue)
    assert "UnitData.slk" in encoded and "UnitUI.slk" in encoded
    assert "Footman" in encoded and "Other" in encoded
    ambiguous = first.replace(b"E\r\n", b'C;X2;Y2;K"conflict"\r\nE\r\n')
    archive.files["UnitData.slk"] = ambiguous
    assert parse_category_objects(archive, "单位") == {"hfoo": {"race": "human"}}


def test_equal_spelling_but_different_source_types_is_a_conflict() -> None:
    archive = _Archive(
        {"UnitData.slk": _slk(value="42"), "UnitUI.slk": _slk(value='"42"')}
    )
    assert parse_category_objects(archive, "单位") == {"hfoo": {}}


def test_invalid_coordinate_does_not_poison_independent_later_rows() -> None:
    payload = _slk().replace(
        b"E\r\n",
        b'C;X0;Y3;K"invalid"\r\nC;X2;K"unbound"\r\n'
        b'C;X1;Y4;K"hrif"\r\nC;X2;K"Rifleman"\r\nE\r\n',
    )
    archive = _Archive({"UnitData.slk": payload})
    md = MapData("synthetic.w3x", "synthetic")
    assert parse_category_objects(archive, "单位", md=md) == {
        "hfoo": {"Name": "Footman"},
        "hrif": {"Name": "Rifleman"},
    }
    assert any(issue["code"] == "invalid_coordinate" for issue in _issues(md))


def test_unknown_category_key_role_stays_diagnostic_and_never_becomes_an_object() -> (
    None
):
    archive = _Archive({"ItemData.slk": _slk(header="unitID")})
    md = MapData("synthetic.w3x", "synthetic")
    assert parse_category_objects(archive, "物品", md=md) == {}
    source = parse_category_evidence(archive, "物品")[0]
    assert not source.identity_confirmed
    assert any(
        issue.code == "unsupported_key_header" for issue in source.table.diagnostics
    )
    assert any(issue["code"] == "unsupported_key_header" for issue in _issues(md))


def test_inventory_counts_physical_rows_and_opaque_columns_without_guessing() -> None:
    payload = _slk().replace(
        b"E\r\n", b'C;X99;Y2;K"opaque"\r\nC;X1;Y3;K"hfoo"\r\nE\r\n'
    )
    summary = build_slk_inventory({"table.slk": payload}).files[0]
    assert summary.rows == 2 and summary.columns == 2
    assert summary.evidence is not None and summary.evidence.raw_bytes == payload
    assert len(summary.evidence.rows) == 2


@pytest.mark.parametrize(
    ("category", "filename", "header", "field", "label"),
    [
        ("单位", "UnitData.slk", "unitID", "Sellitems", "Sellitems"),
        ("物品", "ItemData.slk", "itemID", "iabi", "iabi"),
        ("单位", "UnitData.slk", "unitID", "HP", "生命"),
        ("单位", "UnitData.slk", "unitID", "Name", "名称"),
    ],
)
def test_explicit_empty_slk_cells_override_inherited_values_through_pipeline(
    category: str, filename: str, header: str, field: str, label: str
) -> None:
    archive = _Archive({filename: _slk(header=header, field=field, value='""')})
    md = MapData("synthetic.w3x", "synthetic")
    slk_candidates = collect_slk_candidates(archive, {}, md)
    inherited = ObjectCandidate(
        category,
        "hfoo",
        "hfoo",
        False,
        "base",
        (ObjectFieldValue(field, label, "A000", "inherited", ObjectSourceKind.BASE),),
        (),
    )
    assert len(slk_candidates) == 1
    assert slk_candidates[0].fields[0].value == ""
    populate_object_pipeline(
        md, (inherited, *slk_candidates), {}, include_named_bases=False
    )
    obj = md.obj_identity_index[(category, "hfoo")]
    public_field = "display:name" if field == "Name" else field
    assert obj.field_values[public_field] == ""
    assert (label, "A000") not in obj.fields
    assert not tuple(object_field_relations(md))


def test_four_byte_latin1_ids_keep_punctuation_and_boundary_whitespace() -> None:
    payload = _slk().decode().replace("hfoo", " ÿ! ").encode()
    archive = _Archive({"UnitData.slk": payload})
    assert parse_category_objects(archive, "单位") == {" ÿ! ": {"Name": "Footman"}}
