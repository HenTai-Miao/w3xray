"""Complete-text and item-relation publication integration tests."""

from __future__ import annotations

import csv
import io
from dataclasses import replace
from pathlib import Path

import pytest

from tests.batch_map_processing_fixture import COMPLETE_RAW, ArchiveSource, loaded_map
import w3xtool.batch_map_processing as batch_map_processing
from w3xtool.batch_map_processing import process_one_map
from w3xtool.batch_item_reports import build_batch_item_reports
from w3xtool.batch_models import MapBatchResult, MapBatchState
from w3xtool.batch_runner import BatchOptions, fingerprint_source
from w3xtool.item_relation_models import ItemRelationIndex, RelationCompleteness
from w3xtool.load_context import MapLoadContext
from w3xtool.object_text_models import (
    ObjectTextIndex,
    ObjectTextState,
    TextSelectionReason,
    TextSourcePriority,
)


def test_process_one_map_publishes_lossless_text_and_relation_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given / When
    result, output, archive_source = _process_loaded_map(tmp_path, monkeypatch)

    # Then
    with (output / "对象完整描述.tsv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        complete_text = next(csv.DictReader(handle, delimiter="\t"))
    acquisition = tuple(
        csv.DictReader(
            io.StringIO((output / "掉落与获取关系.tsv").read_text(encoding="utf-8")),
            delimiter="\t",
        )
    )
    skills = tuple(
        csv.DictReader(
            io.StringIO((output / "装备技能关系.tsv").read_text(encoding="utf-8")),
            delimiter="\t",
        )
    )
    assert complete_text["原始全文"] == COMPLETE_RAW
    assert complete_text["规范字段身份"] == "ubertip"
    assert complete_text["证据优先级"] == "600"
    assert complete_text["是否当前值"] == "是"
    assert complete_text["选择原因"] == "最高优先级唯一值"
    assert [row["关系类型"] for row in acquisition] == ["怪物直接掉落"]
    assert [row["关系角色"] for row in skills] == ["装备技能"]
    assert "关系总数：2" in (output / "关系完整性.txt").read_text(encoding="utf-8")
    assert result.relation_incomplete_count == 0
    assert dict(result.relation_counts)["怪物直接掉落"] == 1
    assert archive_source.closed


@pytest.mark.parametrize(
    "text_state",
    (
        ObjectTextState.AUTHOR_UNDEFINED,
        ObjectTextState.SOURCE_UNAVAILABLE,
        ObjectTextState.SOURCE_CONFLICT,
    ),
)
def test_process_one_map_marks_incomplete_complete_text_as_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    text_state: ObjectTextState,
) -> None:
    # Given / When
    result, _output, _source = _process_loaded_map(
        tmp_path,
        monkeypatch,
        text_state=text_state,
    )

    # Then
    assert result.state is MapBatchState.PARTIAL


def test_process_one_map_treats_explicit_empty_text_as_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given / When
    result, _output, _source = _process_loaded_map(
        tmp_path,
        monkeypatch,
        text_state=ObjectTextState.MAP_EXPLICIT_EMPTY,
    )

    # Then
    assert result.state is MapBatchState.COMPLETE


def test_process_one_map_counts_incomplete_relations_and_marks_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given / When
    result, _output, _source = _process_loaded_map(
        tmp_path,
        monkeypatch,
        relation_completeness=RelationCompleteness.PARTIAL,
    )

    # Then
    assert result.state is MapBatchState.PARTIAL
    assert result.relation_incomplete_count == 2


def test_batch_item_reports_aggregate_campaign_children_without_rescanning() -> None:
    # Given
    root, root_source = loaded_map("root.w3n", r"Icons\BTNHero.blp")
    child, child_source = loaded_map("child.w3x", r"Icons\BTNHero.blp")
    child.item_relations = ItemRelationIndex.build(
        replace(relation, map_name="子图") for relation in child.item_relations.records
    )
    root.sub_maps.append(child)

    # When
    reports = build_batch_item_reports(root)

    # Then
    assert reports.maps == (root, child)
    assert len(reports.object_texts.records) == 2
    assert len(reports.item_relations.records) == 4
    root.close()
    assert root_source.closed and child_source.closed


def test_description_counts_include_current_and_lower_priority_evidence() -> None:
    # Given: one map retains a current binary row and a lower-priority SLK row.
    root, source = loaded_map("root.w3x", r"Icons\BTNHero.blp")
    current = root.object_texts.records[0]
    lower = replace(
        current,
        raw_value="旧说明",
        readable_value="旧说明",
        source_kind="地图SLK",
        source_path="AbilityData.slk",
        source_priority=int(TextSourcePriority.MAP_SLK),
        is_current=False,
        selection_reason=TextSelectionReason.LOWER_PRIORITY,
        evidence_ordinal=2,
    )
    root.object_texts = ObjectTextIndex.build((current, lower))

    # When: batch summaries count complete-text evidence.
    reports = build_batch_item_reports(root)

    # Then: both retained rows contribute, independent of current selection.
    assert dict(reports.description_counts)[ObjectTextState.MAP_VALUE.value] == 2
    root.close()
    assert source.closed


def _process_loaded_map(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    text_state: ObjectTextState = ObjectTextState.MAP_VALUE,
    relation_completeness: RelationCompleteness = RelationCompleteness.COMPLETE,
) -> tuple[MapBatchResult, Path, ArchiveSource]:
    source_path = tmp_path / "sample.w3x"
    source_path.write_bytes(b"map")
    loaded, archive_source = loaded_map(
        str(source_path),
        r"Icons\BTNHero.blp",
        text_state=text_state,
        relation_completeness=relation_completeness,
    )
    monkeypatch.setattr(
        batch_map_processing, "load_map", lambda *_args, **_kwargs: loaded
    )
    monkeypatch.setattr(
        batch_map_processing, "open_game_data_source", lambda _path: None
    )
    options = BatchOptions(str(tmp_path), str(tmp_path / "output"))
    result = process_one_map(
        1,
        fingerprint_source(str(source_path)),
        options,
        MapLoadContext(),
    )
    return result, Path(options.output_root, result.output_directory), archive_source
