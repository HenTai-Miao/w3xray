"""Read-only acceptance checks for the 39-map schema-v2 publication."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

from w3xtool.batch_models import BATCH_SCHEMA_VERSION, MapBatchResult
from w3xtool.batch_state_io import parse_batch_state_json
from w3xtool.item_relation_exports import (
    format_equipment_skills_tsv,
    format_item_acquisition_tsv,
)
from w3xtool.item_relation_models import (
    ItemRelationKind,
    RelationCompleteness,
    RelationConfidence,
)
from w3xtool.item_relation_query import filter_item_relations
from w3xtool.map_loader import load_map

from tests.real_map_text_acceptance import (
    TsvTable,
    legacy_report_value,
    legacy_text_report_value,
    missing_legacy_text,
    read_tsv,
    read_tsv_text,
)

_ENV_NAMES: Final = (
    "W3XRAY_MAPS_ROOT",
    "W3XRAY_OLD_OUTPUT",
    "W3XRAY_NEW_OUTPUT",
)
_HEX_256: Final = re.compile(r"[0-9a-f]{64}")
_REQUIRED_ARTIFACTS: Final = frozenset(
    (
        "对象描述.tsv",
        "对象完整描述.tsv",
        "掉落与获取关系.tsv",
        "装备技能关系.tsv",
        "关系完整性.txt",
    )
)
_ACQUISITION_REQUIRED: Final = frozenset(
    (
        "关系ID",
        "关系类型",
        "装备ID",
        "装备名称",
        "证据文件",
        "可信度",
        "完整性",
        "未解析原因",
    )
)
_SKILL_REQUIRED: Final = frozenset(
    (
        "关系ID",
        "装备ID",
        "装备名称",
        "关系角色",
        "技能ID",
        "技能名称",
        "字段来源",
        "可信度",
        "完整性",
        "未解析原因",
    )
)
_SKILL_KINDS: Final = frozenset(
    (ItemRelationKind.ITEM_ABILITY, ItemRelationKind.COOLDOWN_ABILITY)
)

pytestmark = pytest.mark.skipif(
    not all(os.environ.get(name) for name in _ENV_NAMES),
    reason="set W3XRAY_MAPS_ROOT/W3XRAY_OLD_OUTPUT/W3XRAY_NEW_OUTPUT",
)


@dataclass(frozen=True, slots=True)
class AcceptanceContext:
    maps: tuple[Path, ...]
    old_by_digest: Mapping[str, Path]
    new_by_digest: Mapping[str, Path]
    results: tuple[MapBatchResult, ...]


@pytest.fixture(scope="module")
def acceptance_context() -> AcceptanceContext:
    maps_root = Path(os.environ["W3XRAY_MAPS_ROOT"])
    old_root = Path(os.environ["W3XRAY_OLD_OUTPUT"])
    new_root = Path(os.environ["W3XRAY_NEW_OUTPUT"])
    maps = tuple(
        sorted(
            (
                path
                for path in maps_root.rglob("*")
                if path.is_file() and path.suffix.casefold() in {".w3x", ".w3m", ".w3n"}
            ),
            key=lambda path: str(path).casefold(),
        )
    )
    old_by_digest = _output_directories(old_root)
    state = parse_batch_state_json(
        (new_root / "批量提取状态.json").read_text(encoding="utf-8")
    )
    new_by_digest = {
        result.source.sha256: new_root / result.output_directory
        for result in state.results
    }
    return AcceptanceContext(maps, old_by_digest, new_by_digest, state.results)


def test_v2_batch_covers_all_sources_and_required_artifacts(
    acceptance_context: AcceptanceContext,
) -> None:
    # Given: schema-v2 state and the read-only source directory.
    context = acceptance_context

    # When: publication identities and per-map files are enumerated.
    source_paths = {str(path.resolve()) for path in context.maps}
    published_paths = {
        str(Path(result.source.path).resolve()) for result in context.results
    }

    # Then: every one of the 39 sources has one complete artifact set.
    assert BATCH_SCHEMA_VERSION == 3
    assert len(context.maps) == len(context.results) == 39
    assert source_paths == published_paths
    assert set(context.old_by_digest) == set(context.new_by_digest)
    for output in context.new_by_digest.values():
        assert _REQUIRED_ARTIFACTS <= {path.name for path in output.iterdir()}


def test_every_old_non_placeholder_raw_text_remains_v2_evidence(
    acceptance_context: AcceptanceContext,
) -> None:
    # Given: legacy reports and matching v2 outputs are joined by source digest.
    context = acceptance_context

    # When: every legacy raw tip and description is compared with v2 raw evidence.
    missing: list[str] = []
    for digest, old_output in context.old_by_digest.items():
        old = read_tsv(old_output / "对象描述.tsv")
        new = read_tsv(context.new_by_digest[digest] / "对象完整描述.tsv")
        missing.extend(missing_legacy_text(digest, old, new))

    # Then: no legacy value disappears, including its historical escaped form.
    assert not missing, "\n".join(missing)


def test_relation_rows_keep_stable_evidence_and_explicit_unresolved_state(
    acceptance_context: AcceptanceContext,
) -> None:
    # Given: every v2 acquisition and skill table is parseable as standard TSV.
    direct_doo_rows = 0
    for output in acceptance_context.new_by_digest.values():
        acquisition = read_tsv(output / "掉落与获取关系.tsv")
        skills = read_tsv(output / "装备技能关系.tsv")
        assert _ACQUISITION_REQUIRED <= set(acquisition.header)
        assert _SKILL_REQUIRED <= set(skills.header)

        # When/Then: each relation retains stable identity and static provenance.
        _assert_relation_rows(acquisition, "证据文件")
        _assert_relation_rows(skills, "字段来源")
        for row in acquisition.rows:
            if acquisition.value(row, "关系类型") in {
                ItemRelationKind.UNIT_DROP.value,
                ItemRelationKind.DESTRUCTABLE_DROP.value,
            } and acquisition.value(row, "证据文件").casefold().endswith(".doo"):
                direct_doo_rows += 1
                assert acquisition.value(row, "掉落组")
                assert acquisition.value(row, "组内序号")
    assert direct_doo_rows > 0


def test_representative_maps_match_gui_query_and_exporter_counts(
    acceptance_context: AcceptanceContext,
) -> None:
    # Given: smallest, largest, and most script-reward-heavy source maps.
    context = acceptance_context
    smallest = min(context.results, key=lambda result: result.source.size)
    largest = max(context.results, key=lambda result: result.source.size)
    script_heavy = max(context.results, key=_script_reward_count)
    assert _script_reward_count(script_heavy) > 0

    # When: each representative map is loaded through the real static pipeline.
    for result in {smallest, largest, script_heavy}:
        md = load_map(result.source.path)
        try:
            visible = filter_item_relations(md.item_relations.records, "")
            acquisition = read_tsv_text(format_item_acquisition_tsv(md.item_relations))
            skills = read_tsv_text(format_equipment_skills_tsv(md.item_relations))
            published_acquisition = read_tsv(
                context.new_by_digest[result.source.sha256] / "掉落与获取关系.tsv"
            )
            published_skills = read_tsv(
                context.new_by_digest[result.source.sha256] / "装备技能关系.tsv"
            )

            # Then: GUI, formatter, persisted tables, and index expose the same rows.
            assert len(visible) == len(md.item_relations.records)
            assert len(acquisition.rows) == len(published_acquisition.rows)
            assert len(skills.rows) == len(published_skills.rows)
            assert len(acquisition.rows) + len(skills.rows) == len(visible)
        finally:
            md.close()


def test_tsv_text_reader_preserves_physical_newlines() -> None:
    # Given: one quoted TSV field contains a physical newline.
    payload = '证据\n"第一行\n第二行"\n'

    # When: the acceptance reader parses the in-memory export.
    table = read_tsv_text(payload)

    # Then: standard CSV semantics preserve the newline byte-for-character.
    assert table.rows == (("第一行\n第二行",),)


def test_legacy_report_value_matches_historical_lossy_serialization() -> None:
    # Given: exact v2 evidence contains CRLF, a tab, and a physical newline.
    raw = "第一行\r\n第二行\t字段\n第三行"

    # When/Then: compatibility comparison reproduces only the old TSV encoding.
    assert legacy_report_value(raw) == "第一行\\n第二行 字段\\n第三行"


def test_legacy_text_report_value_matches_historical_parser_trimming() -> None:
    # Given: anonymous text evidence retains source whitespace in schema v2.
    raw = "  第一行\r\n第二行\t字段  "

    # When/Then: compatibility reproduces the old parser and TSV transforms.
    assert legacy_text_report_value(raw) == "第一行\\n第二行 字段"


def _output_directories(root: Path) -> Mapping[str, Path]:
    summary = read_tsv(root / "批量提取汇总.tsv")
    return {
        summary.value(row, "SHA256"): root / summary.value(row, "输出目录")
        for row in summary.rows
    }


def _assert_relation_rows(table: TsvTable, evidence_column: str) -> None:
    relation_ids = tuple(table.value(row, "关系ID") for row in table.rows)
    assert len(relation_ids) == len(set(relation_ids))
    for row, relation_id in zip(table.rows, relation_ids, strict=True):
        assert _HEX_256.fullmatch(relation_id)
        assert table.value(row, evidence_column)
        assert table.value(row, "可信度") in {item.value for item in RelationConfidence}
        completeness = table.value(row, "完整性")
        assert completeness in {item.value for item in RelationCompleteness}
        if completeness == RelationCompleteness.UNRESOLVED.value:
            assert table.value(row, "未解析原因")
        for name_column in ("装备名称", "技能名称"):
            if (
                name_column in table.header
                and table.value(row, name_column) == "未解析"
            ):
                assert completeness == RelationCompleteness.UNRESOLVED.value


def _script_reward_count(result: MapBatchResult) -> int:
    return dict(result.relation_counts).get(ItemRelationKind.SCRIPT_REWARD.value, 0)
