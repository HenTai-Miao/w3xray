"""Release regressions for batch source discovery and authoritative resume."""

from __future__ import annotations

from pathlib import Path

import pytest

import gametool.batch_map_attempt as batch_map_attempt
import gametool.batch_map_processing as batch_map_processing
import gametool.batch_runner as batch_runner
from gametool.batch_configuration import BatchOptions
from gametool.batch_global_publication import load_current_batch_state
from gametool.batch_models import MapBatchResult, SourceFingerprint
from gametool.batch_status import KnowledgeGapReason, MapBatchState
from gametool.extraction_diagnostics import record_component_parse_issue
from gametool.load_context import MapLoadContext
from tests.batch_map_processing_fixture import loaded_map
from tests.batch_publication_fixture import publish_empty_result


@pytest.mark.parametrize("change", ("renamed", "changed_first", "earlier_duplicate"))
def test_resume_keeps_every_current_distinct_source_after_path_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    source_root = tmp_path / "maps"
    source_root.mkdir()
    original = source_root / "b_original.w3x"
    original.write_bytes(b"original contents")
    processed: list[str] = []
    monkeypatch.setattr(
        batch_runner, "build_map_load_context", lambda **_kwargs: MapLoadContext()
    )
    monkeypatch.setattr(
        batch_map_attempt,
        "fingerprint_dependencies",
        lambda fingerprint, *_args: fingerprint.sha256,
    )

    def process(
        index: int,
        fingerprint: SourceFingerprint,
        options: BatchOptions,
        _context: MapLoadContext,
    ) -> MapBatchResult:
        processed.append(fingerprint.path)
        return publish_empty_result(index, fingerprint, options.output_root)

    monkeypatch.setattr(batch_runner, "process_one_map", process)
    options = BatchOptions(str(source_root), str(tmp_path / "output"))
    first = batch_runner.run_batch(options)
    assert len(first.results) == 1

    if change == "renamed":
        original.rename(source_root / "c_renamed.w3x")
        expected_names = {"c_renamed.w3x"}
    elif change == "changed_first":
        (source_root / "c_duplicate.w3x").write_bytes(original.read_bytes())
        original.write_bytes(b"changed contents")
        expected_names = {"b_original.w3x", "c_duplicate.w3x"}
    else:
        (source_root / "a_duplicate.w3x").write_bytes(original.read_bytes())
        expected_names = {"a_duplicate.w3x"}

    second = batch_runner.run_batch(options)

    assert {
        Path(result.source.path).name for result in second.results
    } == expected_names
    assert len({result.source.sha256 for result in second.results}) == len(
        expected_names
    )
    assert load_current_batch_state(options.output_root) == second
    calls_after_second = len(processed)
    assert batch_runner.run_batch(options) == second
    assert len(processed) == calls_after_second


@pytest.mark.parametrize("campaign", (False, True))
def test_batch_retains_component_failures_beside_confirmed_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    campaign: bool,
) -> None:
    source_path = tmp_path / ("sample.w3n" if campaign else "sample.w3x")
    source_path.write_bytes(b"map")
    root, archive = loaded_map(str(source_path), r"Icons\BTNHero.blp")
    if campaign:
        child, _child_archive = loaded_map("chapter.w3x", r"Icons\BTNHero.blp")
        child.name = "确认章节"
        root.sub_maps.append(child)
        record_component_parse_issue(
            root, "campaign-child", "missing.w3x", "child archive unreadable"
        )
        record_component_parse_issue(
            child, "preplaced", "war3mapUnits.doo", "record 2 truncated"
        )
    else:
        record_component_parse_issue(
            root, "object-binary", "war3map.w3u", "record 2 truncated"
        )
    monkeypatch.setattr(
        batch_map_processing, "load_map", lambda *_args, **_kwargs: root
    )
    monkeypatch.setattr(
        batch_map_processing, "open_game_data_source", lambda _path: None
    )
    options = BatchOptions(str(tmp_path), str(tmp_path / "output"))

    result = batch_map_processing.process_one_map(
        1, batch_runner.fingerprint_source(str(source_path)), options, MapLoadContext()
    )

    assert result.state is MapBatchState.PARTIAL
    assert KnowledgeGapReason.SOURCE_COVERAGE_MISSING in result.knowledge_gap_reasons
    assert result.source_coverage_gap_count == (2 if campaign else 1)
    diagnostic_report = Path(
        options.output_root, result.output_directory, "组件诊断.tsv"
    ).read_text(encoding="utf-8")
    assert "record 2 truncated" in diagnostic_report
    if campaign:
        assert "missing.w3x" in diagnostic_report
        assert "child archive unreadable" in diagnostic_report
        assert "chapter.w3x" in diagnostic_report
    assert archive.closed
