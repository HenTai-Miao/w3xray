"""Selected offline evidence stays complete and bound to its own source scope."""

from __future__ import annotations

import csv
from dataclasses import asdict, replace
import io
import json
import os
from pathlib import Path
import re

import pytest

from gametool.batch_tsv import decode_tsv_cell
from gametool.gui_reference_selection import (
    format_reference_selection,
    format_reference_selection_tsv,
    reference_pack_query_target,
    reference_selection_to_dict,
    write_reference_selection,
)
from gametool.reference_models import (
    ReferenceMapScope,
    ReferenceRecord,
    ReferenceSearchResult,
    ReferenceSource,
    ReferenceValue,
)
from gametool.search import compile_query, encode_literal_query


def _json_value(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def _evidence(tmp_path):
    pack = tmp_path / "pack"
    child = pack / "子地图" / "second"
    source = ReferenceSource(
        str(pack / "对象ID" / "物品.tsv"),
        str(pack / "对象ID" / "物品.tsv"),
        "a" * 64,
        "完整来源",
        state="map-evidence",
    )
    record = ReferenceRecord(
        "objects",
        "-001",
        '=标签\t换行\r\n"引号"\ufeff\'\u2060原样',
        category="物品",
        scope=str(pack),
        aliases=("\ufeff内部BOM",),
        sources=(source.id,),
        state="map-evidence",
        values=(
            ReferenceValue(
                "iTip",
                "提示",
                "首行\t\r\n" + "完整尾部" * 2500,
                source=source.id,
                extras=(("扩展", "'\u2060=保留\r\n"),),
                category="物品",
                object_id="-001",
            ),
            ReferenceValue("usei", "货架", "", source=source.id),
        ),
        details=(("显式空值", ""),),
        diagnostics=("独立对象诊断",),
        raw_rows=(("物品", "-001", "\t原始\r\n完整", "\ufeff"),),
        coverage={"complete": False, "extra": ["全部扩展"]},
    )
    return ReferenceSearchResult(
        (
            record,
            replace(record, category="单位", label="同码不同类别"),
            replace(record, scope=str(child), label="同码不同章节"),
            replace(record, label="同类别同码独立记录"),
        ),
        (source, replace(source, id="unselected-source", path=str(tmp_path / "old"))),
        ("未选中来源也保留的完整诊断",),
        19,
        8,
        4,
        query="原查询",
        limit=4,
        catalog_complete=False,
        input_roots=(str(pack),),
        map_scopes=(
            ReferenceMapScope(
                str(child),
                "campaign.w3n",
                "Maps/Missing.w3x",
                "仅诊断章节",
                "",
                diagnostics=("章节不可读取",),
                complete=False,
            ),
        ),
    )


def test_selected_json_keeps_independent_identities_and_complete_context(tmp_path):
    result = _evidence(tmp_path)
    payload = reference_selection_to_dict(result, (3, 0, 2, 0))
    assert _json_value(payload["records"]) == [
        _json_value(asdict(result.records[index])) for index in (0, 2, 3)
    ]
    assert payload["selection"] == {
        "indices": [0, 2, 3],
        "selected": 3,
        "displayed": 4,
        "matched": 8,
        "omitted_by_query": 4,
    }
    for key in ("sources", "map_scopes", "diagnostics", "input_roots"):
        assert payload[key] == asdict(result)[key]
    assert payload["matched"] == 8 and payload["omitted"] == 4
    assert payload["limit"] == 4
    assert result.records[1].category == "单位"


def test_selected_markdown_and_tsv_roundtrip_every_record_and_context(tmp_path):
    result = _evidence(tmp_path)
    indices = (0, 1, 2, 3)
    payload = _json_value(reference_selection_to_dict(result, indices))
    text = format_reference_selection(result, indices)
    fences = [
        json.loads(value) for value in re.findall(r"```json\n(.*?)\n```", text, re.S)
    ]
    assert fences[:-1] == payload["records"]
    assert fences[-1] == {
        key: value for key, value in payload.items() if key != "records"
    }
    assert "来源不完整" in text
    assert "（显式空值）" in text
    rows = [
        [decode_tsv_cell(cell) for cell in row]
        for row in csv.reader(
            io.StringIO(format_reference_selection_tsv(result, indices), newline=""),
            delimiter="\t",
            strict=True,
        )
    ]
    assert len(rows) == 6
    assert rows[1][0] == "catalog"
    assert json.loads(rows[1][-1]) == fences[-1]
    for ordinal, row in enumerate(rows[2:]):
        record = result.records[ordinal]
        assert row[0] == "record" and row[1] == str(ordinal + 1)
        assert row[3:7] == [record.category, record.id, record.label, record.scope]
        assert json.loads(row[-1]) == payload["records"][ordinal]
        assert json.loads(row[-2]) == list(record.sources)


@pytest.mark.parametrize("suffix", (".json", ".md", ".tsv"))
def test_selected_exports_write_full_evidence_and_reject_all_input_assets(
    tmp_path, suffix
):
    result = _evidence(tmp_path)
    source = Path(result.sources[0].path)
    source.parent.mkdir(parents=True)
    source.write_bytes(b"original source bytes")
    destination = tmp_path / f"selected{suffix}"
    write_reference_selection(destination, result, (0, 2))
    assert destination.is_file()
    with pytest.raises(ValueError, match="输入"):
        write_reference_selection(source, result, (2,))
    with pytest.raises(ValueError, match="只读输入"):
        write_reference_selection(source.parent / f"new{suffix}", result, (2,))
    alias = tmp_path / f"source-alias{suffix}"
    os.link(source, alias)
    with pytest.raises(ValueError, match="输入"):
        write_reference_selection(alias, result, (2,))
    assert source.read_bytes() == b"original source bytes"


@pytest.mark.parametrize("indices", ((), (-1,), (4,), (False,), (1.5,)))
def test_empty_or_stale_selection_never_writes_a_report(tmp_path, indices):
    destination = tmp_path / "no-report.json"
    with pytest.raises(ValueError):
        write_reference_selection(destination, _evidence(tmp_path), indices)
    assert not destination.exists()


@pytest.mark.parametrize(
    ("category", "command"),
    (
        ("物品", "item"),
        ("单位", "units"),
        ("英雄", "heroes"),
        ("技能", "skills"),
        ("增益", "buffs"),
        ("科技", "tech"),
        ("装饰物", "search"),
        ("可破坏物", "search"),
    ),
)
def test_query_target_uses_source_chapter_category_and_literal_code(
    tmp_path, category, command
):
    result = _evidence(tmp_path)
    scope = tmp_path / "pack" / "子地图" / "second"
    source = replace(
        result.sources[0],
        id=str(scope / "对象字段.tsv"),
        path=str(scope / "对象字段.tsv"),
    )
    code = '|"%\\'
    record = replace(
        result.records[0],
        id=code,
        category=category,
        scope=str(scope),
        sources=(source.id,),
        state="field-only",
    )
    result = replace(result, records=(record,), sources=(source,))
    query = encode_literal_query(code)
    expected_query = f"{category}:{query}" if command == "search" else query
    assert reference_pack_query_target(result, 0, str(tmp_path / "pack")) == (
        str(scope),
        command,
        expected_query,
    )
    assert compile_query(query).score_fields((code,)) is not None
    assert compile_query(query).score_fields(("not the code",)) is None


@pytest.mark.parametrize(
    "change",
    (
        "map",
        "external",
        "builtin",
        "other-pack",
        "nested",
        "missing-source",
        "archive-source",
        "unproved-root",
    ),
)
def test_unbound_reference_never_borrows_a_current_pack(tmp_path, change):
    result = _evidence(tmp_path)
    pack = str(tmp_path / "pack")
    if change == "map":
        result = replace(result, map_path=str(tmp_path / "map.w3x"))
    elif change in {"external", "builtin"}:
        record = replace(
            result.records[0],
            state="external-label" if change == "external" else "static-definition",
        )
        result = replace(result, records=(record,))
    elif change == "other-pack":
        pack = str(tmp_path / "different-current-pack")
    elif change == "nested":
        record = replace(
            result.records[0],
            scope=str(tmp_path / "pack" / "子地图" / "one" / "nested"),
        )
        result = replace(result, records=(record,))
    elif change == "missing-source":
        result = replace(result, sources=())
    elif change == "archive-source":
        result = replace(
            result, sources=(replace(result.sources[0], member_path="war3map.w3t"),)
        )
    else:
        result = replace(result, input_roots=())
    assert reference_pack_query_target(result, 0, pack) is None
