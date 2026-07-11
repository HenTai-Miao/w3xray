"""Component failures remain visible without aborting static extraction."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from w3xtool.extraction_diagnostics import DiagnosticSeverity, read_component
from w3xtool.cli_summary import iter_cli_summary_lines
from w3xtool.gui_extraction_reports import build_extraction_completeness_block
from w3xtool.knowledge_diagnostics import format_component_diagnostics_tsv
from w3xtool.knowledge_pack import write_knowledge_pack_report
from w3xtool.load_context import MapLoadContext
from w3xtool.map_loader import _load_map_impl
from w3xtool.object_candidates import collect_object_candidates
from w3xtool.map_components import _add_preplaced, _add_w3f, _add_w3i
from w3xtool.map_data import MapData
from w3xtool.map_extras import (
    add_game_configs,
    add_import_summary,
    add_preview_icons,
    add_trigger_summary,
    add_world_metadata,
)
from w3xtool.script_sources import collect_readable_scripts
from w3xtool.slk_objects import parse_category_objects


@dataclass(frozen=True, slots=True)
class _FailingArchive:
    files: set[str]
    path: str = "fixture.w3x"
    _data: bytes = b""

    def has_file(self, name: str) -> bool:
        return name in self.files

    def read_file(self, name: str) -> bytes:
        raise OSError(f"cannot read {name}")

    def list_files(self) -> list[str]:
        return sorted(self.files)

    def close(self) -> None:
        return


@dataclass(frozen=True, slots=True)
class _CampaignArchive(_FailingArchive):
    def read_file(self, name: str) -> bytes:
        if name == "(listfile)":
            return b"Map01.w3x\n"
        return super().read_file(name)


@dataclass(frozen=True, slots=True)
class _MemoryArchive(_FailingArchive):
    payloads: dict[str, bytes] | None = None

    def read_file(self, name: str) -> bytes:
        return (self.payloads or {}).get(name, b"")


def test_read_component_records_typed_recoverable_failure() -> None:
    # Given: one present component whose bounded operation fails.
    md = MapData("fixture.w3x", "fixture")

    # When: the component boundary executes the failing operation.
    result = read_component(
        md,
        "wts",
        "war3map.wts",
        lambda: _raise_value_error("truncated string table"),
    )

    # Then: extraction continues with one source-specific warning.
    assert result is None
    diagnostic = md.diagnostics[0]
    assert diagnostic.component == "wts"
    assert diagnostic.source == "war3map.wts"
    assert diagnostic.stage == "read/parse"
    assert diagnostic.severity is DiagnosticSeverity.WARNING
    assert diagnostic.exception_type == "ValueError"
    assert diagnostic.message == "ValueError: truncated string table"
    assert diagnostic.recoverable


def test_script_and_slk_read_failures_are_recorded() -> None:
    # Given: readable membership says scripts and an embedded SLK exist.
    names = {
        "war3map.j",
        "war3map.lua",
        "war3map.wts",
        "war3map.wct",
        "war3map.w3u",
        "UnitData.slk",
        "Units\\HumanUnitStrings.txt",
    }
    archive = _FailingArchive(names)
    md = MapData(archive.path, "fixture")

    # When: independent script and object-table collectors run.
    scripts = collect_readable_scripts(archive, md=md)
    objects = parse_category_objects(archive, "单位", md=md)
    candidates = collect_object_candidates(archive, {}, md=md)

    # Then: each existing unreadable source is named and no data is invented.
    assert scripts.texts == {}
    assert objects == {}
    assert candidates == ()
    assert {(item.component, item.source) for item in md.diagnostics} == {
        ("script", "war3map.j"),
        ("script", "war3map.lua"),
        ("wts", "war3map.wts"),
        ("wct", "war3map.wct"),
        ("object-binary", "war3map.w3u"),
        ("object-text", "Units\\HumanUnitStrings.txt"),
        ("slk", "UnitData.slk"),
    }


def test_map_component_helpers_record_present_read_failures() -> None:
    # Given: core map and campaign members exist but cannot be read.
    archive = _FailingArchive({
        "war3map.w3i",
        "war3campaign.w3f",
        "war3map.doo",
        "war3mapUnits.doo",
    })
    md = MapData(archive.path, "fixture")

    # When: core metadata and placement helpers run independently.
    _add_w3i(md, archive, {})
    _add_w3f(md, archive, {})
    _add_preplaced(md, archive)

    # Then: all four failed sources remain visible while defaults stay usable.
    assert {(item.component, item.source) for item in md.diagnostics} == {
        ("w3i", "war3map.w3i"),
        ("w3f", "war3campaign.w3f"),
        ("preplaced", "war3map.doo"),
        ("preplaced", "war3mapUnits.doo"),
    }
    assert md.w3i is None
    assert md.w3f is None
    assert md.doodads == []
    assert md.units == []


def test_readable_but_malformed_core_and_world_members_are_diagnosed() -> None:
    # Given: component bodies can be read but contain no valid format header.
    names = {
        "war3map.w3i",
        "war3campaign.w3f",
        "war3map.w3r",
        "war3map.w3c",
        "war3map.w3s",
    }
    archive = _MemoryArchive(names, payloads={name: b"broken" for name in names})
    md = MapData(archive.path, "fixture")

    # When: core and world parsers reject those readable bodies.
    _add_w3i(md, archive, {})
    _add_w3f(md, archive, {})
    add_world_metadata(md, archive, {})

    # Then: parser rejection becomes a typed warning for every present source.
    assert {(item.component, item.source) for item in md.diagnostics} == {
        ("w3i", "war3map.w3i"),
        ("w3f", "war3campaign.w3f"),
        ("world", "war3map.w3r"),
        ("world", "war3map.w3c"),
        ("world", "war3map.w3s"),
    }
    assert {item.exception_type for item in md.diagnostics} == {"ComponentParseError"}


def test_optional_editor_helpers_record_only_present_failures() -> None:
    # Given: every supported optional editor member exists but is unreadable.
    archive = _FailingArchive({
        "war3map.w3r",
        "war3map.w3c",
        "war3map.w3s",
        "war3map.wgc",
        "war3map.wtg",
        "war3map.mmp",
        "war3map.imp",
    })
    md = MapData(archive.path, "fixture")

    # When: all optional metadata helpers run.
    add_world_metadata(md, archive, {})
    add_game_configs(md, archive)
    add_trigger_summary(md, archive)
    add_preview_icons(md, archive)
    add_import_summary(md, archive)

    # Then: each existing source yields one diagnostic with no duplicate noise.
    assert {(item.component, item.source) for item in md.diagnostics} == {
        ("world", "war3map.w3r"),
        ("world", "war3map.w3c"),
        ("world", "war3map.w3s"),
        ("wgc", "war3map.wgc"),
        ("wtg", "war3map.wtg"),
        ("mmp", "war3map.mmp"),
        ("imp", "war3map.imp"),
    }


def test_absent_optional_members_do_not_create_diagnostics() -> None:
    # Given: an archive with none of the optional editor members.
    archive = _FailingArchive(set())
    md = MapData(archive.path, "fixture")

    # When: optional metadata helpers run against the empty archive.
    add_world_metadata(md, archive, {})
    add_game_configs(md, archive)
    add_trigger_summary(md, archive)
    add_preview_icons(md, archive)
    add_import_summary(md, archive)

    # Then: absence remains a normal no-data state, not a warning.
    assert md.diagnostics == []


def test_component_diagnostics_are_exported_as_tsv() -> None:
    # Given: one source failure has been recorded.
    md = MapData("fixture.w3x", "fixture")
    read_component(md, "wts", "war3map.wts", lambda: _raise_value_error("bad bytes"))

    # When: the knowledge-pack diagnostic artifact is formatted.
    text = format_component_diagnostics_tsv(md)

    # Then: stable columns retain component, source, severity, and exception type.
    assert text.startswith("组件\t来源\t阶段\t级别\t异常类型\t可恢复\t消息\n")
    assert "wts\twar3map.wts\tread/parse\twarning\tValueError\t是\tValueError: bad bytes" in text


def test_map_loader_routes_script_and_slk_failures_to_map_diagnostics() -> None:
    # Given: a map advertises unreadable primary scripts, WTS, WCT, and SLK data.
    archive = _FailingArchive({
        "war3map.j",
        "war3map.lua",
        "war3map.wts",
        "war3map.wct",
        "war3map.w3u",
        "UnitData.slk",
        "Units\\HumanUnitStrings.txt",
    })

    # When: the high-level extraction orchestrator loads all independent sources.
    md = _load_map_impl(archive, archive.path, 0, None, MapLoadContext())

    # Then: collector failures reach the returned MapData instead of disappearing.
    assert {(item.component, item.source) for item in md.diagnostics} >= {
        ("script", "war3map.j"),
        ("script", "war3map.lua"),
        ("wts", "war3map.wts"),
        ("wct", "war3map.wct"),
        ("object-binary", "war3map.w3u"),
        ("object-text", "Units\\HumanUnitStrings.txt"),
        ("slk", "UnitData.slk"),
    }


def test_campaign_child_read_failure_is_recorded_without_hiding_siblings() -> None:
    # Given: a campaign listfile declares one child whose archive body is unreadable.
    archive = _CampaignArchive({"(listfile)", "Map01.w3x"}, path="fixture.w3n")

    # When: campaign extraction attempts the declared child.
    md = _load_map_impl(archive, archive.path, 0, None, MapLoadContext())

    # Then: the child stays absent but its exact source failure remains visible.
    assert md.sub_maps == []
    assert any(
        item.component == "campaign-child" and item.source == "Map01.w3x"
        for item in md.diagnostics
    )


def test_reference_graph_failure_is_recorded_as_component_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: optional reference analysis raises after all primary extraction completed.
    monkeypatch.setattr(
        "w3xtool.map_loader.build_reference_graph",
        lambda _md: _raise_runtime_error("graph failed"),
    )

    # When: the normal loader reaches the optional analysis boundary.
    archive = _MemoryArchive(set())
    md = _load_map_impl(archive, archive.path, 0, None, MapLoadContext())

    # Then: extraction remains usable and the exact failed analysis is visible.
    diagnostic = next(item for item in md.diagnostics if item.component == "reference-graph")
    assert diagnostic.source == "objects/scripts/preplaced"
    assert diagnostic.stage == "analyze"
    assert diagnostic.exception_type == "RuntimeError"
    assert diagnostic.message == "RuntimeError: graph failed"
    assert md.ref_low_coverage


def test_knowledge_pack_writes_component_diagnostic_artifact(tmp_path) -> None:
    # Given: the loaded map retained one extraction failure.
    md = MapData("fixture.w3x", "fixture")
    read_component(md, "wts", "war3map.wts", lambda: _raise_value_error("bad bytes"))

    # When: the structured knowledge pack is published.
    report = write_knowledge_pack_report(md, str(tmp_path / "pack"))

    # Then: the diagnostic TSV is written and included in structured outcomes.
    artifact = tmp_path / "pack" / "组件诊断.tsv"
    assert "ValueError: bad bytes" in artifact.read_text(encoding="utf-8")
    assert report.items_by_path["组件诊断.tsv"].written


def test_component_failures_are_visible_in_cli_and_gui_reports() -> None:
    # Given: one map component failed during static extraction.
    md = MapData("fixture.w3x", "fixture")
    read_component(md, "w3i", "war3map.w3i", lambda: _raise_value_error("truncated"))

    # When: users inspect the normal CLI and GUI diagnostic surfaces.
    cli_text = "\n".join(iter_cli_summary_lines(md))
    gui_block = build_extraction_completeness_block(md)
    gui_text = "\n".join(gui_block.lines)

    # Then: both surfaces name the component, source, exception, and warning state.
    assert "组件诊断: 1" in cli_text
    assert "w3i · war3map.w3i · ValueError" in cli_text
    assert "组件诊断 1" in gui_text
    assert "w3i · war3map.w3i · ValueError" in gui_text
    assert gui_block.warning_count >= 1


def _raise_value_error(message: str) -> None:
    raise ValueError(message)


def _raise_runtime_error(message: str) -> None:
    raise RuntimeError(message)
