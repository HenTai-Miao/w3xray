"""Read-only acceptance checks for the current 39-map publication."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

from gametool.acceptance_batch import require_authoritative_batch
from gametool.batch_models import MapBatchResult
from gametool.item_relation_models import (
    ItemRelationKind,
    RelationCompleteness,
    RelationConfidence,
)

from tests.real_map_text_acceptance import (
    TsvTable,
    legacy_report_value,
    legacy_text_report_value,
    read_tsv,
    read_tsv_text,
)

_ENV_NAMES: Final = (
    "GAMEXRAY_MAPS_ROOT",
    "GAMEXRAY_OLD_OUTPUT",
    "GAMEXRAY_NEW_OUTPUT",
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


@dataclass(frozen=True, slots=True)
class AcceptanceContext:
    maps: tuple[Path, ...]
    old_by_digest: Mapping[str, Path]
    new_by_digest: Mapping[str, Path]
    results: tuple[MapBatchResult, ...]


@pytest.fixture(scope="module")
def acceptance_context() -> AcceptanceContext:
    maps_root = Path(os.environ["GAMEXRAY_MAPS_ROOT"])
    old_root = Path(os.environ["GAMEXRAY_OLD_OUTPUT"])
    new_root = Path(os.environ["GAMEXRAY_NEW_OUTPUT"])
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
    authority = require_authoritative_batch(new_root)
    state = authority.generation.state
    new_by_digest = {
        result.source.sha256: directory for result, directory in authority.publications
    }
    return AcceptanceContext(maps, old_by_digest, new_by_digest, state.results)


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
