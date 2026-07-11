"""Malformed present components retain tolerant output and emit diagnostics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from w3xtool.load_context import MapLoadContext
from w3xtool.map_components import _add_w3f
from w3xtool.map_data import MapData
from w3xtool.map_loader import _load_map_impl
from w3xtool.mpq import MPQArchive
from w3xtool.object_text_sources import collect_text_object_records
from w3xtool.slk_objects import parse_category_objects


@dataclass(frozen=True, slots=True)
class _Archive:
    payloads: Mapping[str, bytes]
    failures: frozenset[str] = frozenset()
    path: str = "fixture.w3x"
    _data: bytes = field(default=b"", repr=False)

    def has_file(self, name: str) -> bool:
        return name in self.payloads or name in self.failures

    def read_file(self, name: str) -> bytes:
        if name in self.failures:
            raise OSError(f"cannot read {name}")
        return self.payloads[name]

    def list_files(self) -> list[str]:
        return sorted((*self.payloads, *self.failures))

    def close(self) -> None:
        return


class _TextObjectParseError(ValueError):
    """Synthetic parser failure used at the component boundary."""


def test_tolerant_parsers_diagnose_malformed_present_components() -> None:
    # Given: readable members are malformed in six independently tolerant formats.
    archive = _Archive({
        "war3map.wts": b"STRING 1\n{\nunterminated",
        "war3map.w3u": b"\x02\x00\x00\x00\x01",
        "UnitData.slk": b"not an slk",
        "Units\\HumanUnitStrings.txt": b"[H001]\n",
        "war3map.imp": b"broken",
        "war3map.doo": b"broken",
    })

    # When: the normal loader keeps extracting independent components.
    md = _load_map_impl(archive, archive.path, 0, None, MapLoadContext())

    # Then: every present malformed source is visible rather than masquerading as absent.
    observed = {(item.component, item.source) for item in md.diagnostics}
    assert {
        ("wts", "war3map.wts"),
        ("object-binary", "war3map.w3u"),
        ("slk", "UnitData.slk"),
        ("object-text", "Units\\HumanUnitStrings.txt"),
        ("imp", "war3map.imp"),
        ("preplaced", "war3map.doo"),
    }.issubset(observed)


def test_wct_read_failure_emits_exactly_one_diagnostic() -> None:
    # Given: WCT exists but fails before parser bytes are available.
    archive = _Archive({}, frozenset({"war3map.wct"}))

    # When: the normal loader collects scripts and parse status.
    md = _load_map_impl(archive, archive.path, 0, None, MapLoadContext())

    # Then: the read failure is not duplicated as a synthetic parse failure.
    diagnostics = [item for item in md.diagnostics if item.component == "wct"]
    assert len(diagnostics) == 1
    assert diagnostics[0].stage == "read"


def test_truncated_w3f_model_diagnostic_reaches_map_diagnostics() -> None:
    # Given: a real W3F body is truncated after its parser has accepted the header.
    fixture = Path(__file__).parent / "fixtures" / "reference" / "stormlib-reference-parity-campaign.w3n"
    with MPQArchive(str(fixture)) as source:
        payload = source.read_file("war3campaign.w3f")
    archive = _Archive({"war3campaign.w3f": payload[:-8]}, path="fixture.w3n")
    md = MapData(archive.path, "fixture")

    # When: campaign metadata is parsed through the component boundary.
    _add_w3f(md, archive, {})

    # Then: retained partial metadata is accompanied by one W3F diagnostic.
    assert md.w3f is not None
    assert any(item.component == "w3f" for item in md.diagnostics)


def test_text_object_parser_exception_is_captured_at_parse_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a trusted readable text table reaches a parser failure.
    archive = _Archive({"Units\\HumanUnitStrings.txt": b"[H001]\nName=Unit\n"})
    md = MapData(archive.path, "fixture")

    def fail_parser(_text: str):
        raise _TextObjectParseError("bad text object syntax")

    monkeypatch.setattr("w3xtool.object_text_sources.parse_text_objects", fail_parser)

    # When: named text objects are collected.
    records = collect_text_object_records(archive, md=md)

    # Then: the exception becomes one parse diagnostic and no object is invented.
    assert records == ()
    assert len(md.diagnostics) == 1
    assert md.diagnostics[0].stage == "parse"
    assert md.diagnostics[0].exception_type == "_TextObjectParseError"


def test_missing_declared_campaign_child_reaches_loader_diagnostics() -> None:
    # Given: a real W3F declaration exists but its child member is absent.
    fixture = Path(__file__).parent / "fixtures" / "reference" / "stormlib-reference-parity-campaign.w3n"
    with MPQArchive(str(fixture)) as source:
        payload = source.read_file("war3campaign.w3f")
    archive = _Archive({"war3campaign.w3f": payload}, path="fixture.w3n")

    # When: campaign loading attempts every W3F declaration.
    md = _load_map_impl(archive, archive.path, 0, None, MapLoadContext())

    # Then: the missing child is retained as a source-specific warning.
    assert md.sub_maps == []
    assert any(
        item.component == "campaign-child" and item.source == "Maps\\Parity01.w3x"
        for item in md.diagnostics
    )


def test_failed_campaign_child_does_not_consume_retained_byte_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one malformed child precedes a valid child that fits the retained-byte budget by itself.
    fixture = Path(__file__).parent / "fixtures" / "reference" / "stormlib-huffman-map.w3x"
    valid_child = fixture.read_bytes()
    malformed_child = b"bad!"
    archive = _Archive(
        {
            "Maps\\Bad.w3x": malformed_child,
            "Maps\\Good.w3x": valid_child,
        },
        path="fixture.w3n",
    )
    monkeypatch.setattr(
        "w3xtool.map_loader._MAX_CAMPAIGN_CHILD_BYTES",
        len(valid_child) + len(malformed_child) - 1,
    )

    # When: campaign children are loaded in archive order.
    md = _load_map_impl(archive, archive.path, 0, None, MapLoadContext())

    # Then: the failed child is diagnosed without preventing the valid sibling from loading.
    assert [child.path for child in md.sub_maps] == ["Maps\\Good.w3x"]
    assert any(
        item.component == "campaign-child" and item.source == "Maps\\Bad.w3x"
        for item in md.diagnostics
    )


def test_nonempty_wts_without_string_header_is_diagnosed() -> None:
    # Given: a present WTS member contains non-comment garbage and no STRING block.
    archive = _Archive({"war3map.wts": b"not a WTS string table"})

    # When: the normal loader parses the component.
    md = _load_map_impl(archive, archive.path, 0, None, MapLoadContext())

    # Then: the malformed member does not masquerade as a valid empty table.
    assert any(
        item.component == "wts" and item.source == "war3map.wts"
        for item in md.diagnostics
    )


def test_unsupported_doo_version_is_diagnosed_even_when_empty() -> None:
    # Given: a present placement table has the right magic but an unsupported header pair.
    payload = b"W3do" + (99).to_bytes(4, "little", signed=True)
    payload += (77).to_bytes(4, "little", signed=True) + (0).to_bytes(4, "little", signed=True)
    archive = _Archive({"war3map.doo": payload})

    # When: the normal loader parses the empty placement table.
    md = _load_map_impl(archive, archive.path, 0, None, MapLoadContext())

    # Then: unsupported metadata remains visible despite the zero record count.
    assert any(
        item.component == "preplaced" and item.source == "war3map.doo"
        for item in md.diagnostics
    )


def test_truncated_w3i_retains_partial_model_with_diagnostic() -> None:
    # Given: a recognized W3I version is truncated after its first complete field.
    payload = (28).to_bytes(4, "little", signed=True) + (1).to_bytes(4, "little", signed=True)
    archive = _Archive({"war3map.w3i": payload})

    # When: the normal loader reads map metadata.
    md = _load_map_impl(archive, archive.path, 0, None, MapLoadContext())

    # Then: confirmed metadata remains available and its incomplete state is explicit.
    assert md.w3i is not None
    assert md.w3i.version == 28
    assert any(item.component == "w3i" for item in md.diagnostics)


def test_truncated_world_records_are_diagnosed() -> None:
    # Given: three recognized world-data headers each declare one missing record.
    one = (1).to_bytes(4, "little", signed=True)
    archive = _Archive(
        {
            "war3map.w3r": (5).to_bytes(4, "little", signed=True) + one,
            "war3map.w3c": (0).to_bytes(4, "little", signed=True) + one,
            "war3map.w3s": (1).to_bytes(4, "little", signed=True) + one,
        },
    )

    # When: the normal loader parses world metadata.
    md = _load_map_impl(archive, archive.path, 0, None, MapLoadContext())

    # Then: every incomplete source is retained as a component warning.
    assert {
        item.source
        for item in md.diagnostics
        if item.component == "world"
    } == {"war3map.w3r", "war3map.w3c", "war3map.w3s"}


def test_unterminated_slk_retains_rows_with_diagnostic() -> None:
    # Given: a valid SLK row is present but the file terminator is missing.
    text = (
        'ID;P\nC;X1;Y1;K"unitID"\nC;X2;Y1;K"race"\n'
        'C;X1;Y2;K"hfoo"\nC;X2;Y2;K"human"\n'
    )
    archive = _Archive({"UnitData.slk": text.encode("ascii")})
    md = MapData(archive.path, "fixture")

    # When: the tolerant SLK collector parses the source.
    rows = parse_category_objects(archive, "单位", md=md)

    # Then: confirmed rows survive and the missing terminator is reported.
    assert rows["hfoo"]["race"] == "human"
    assert any(item.component == "slk" for item in md.diagnostics)


def test_mixed_text_object_sections_retain_valid_rows_with_diagnostic() -> None:
    # Given: a trusted table contains one valid object followed by one empty section.
    archive = _Archive(
        {"Units\\HumanUnitStrings.txt": b"[H001]\nName=Footman\n[H002]\n"},
    )
    md = MapData(archive.path, "fixture")

    # When: text-object records are collected.
    records = collect_text_object_records(archive, md=md)

    # Then: the valid object survives and the dropped section is observable.
    assert [record.obj_id for record in records] == ["H001"]
    assert any(item.component == "object-text" for item in md.diagnostics)
