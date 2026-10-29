"""Independent evidence checks shared by pure tests and actual GUI exports."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any

from .gui_offline_acceptance_support import _require
from .gui_offline_acceptance_v12_fixtures import (
    CALL_SOURCES,
    CAMPAIGN_NAME,
    CHAPTER_NAME,
    CHAPTER_TITLE,
    CHILD_MEMBER,
    HUGE_QUANTITY,
    MAP_DESCRIPTION,
    MAP_NAME,
    SIX_CODES,
    authored_call_rows,
    authored_w3f,
)


def validate_call_evidence(rows: list[dict[str, Any]]) -> None:
    expected = authored_call_rows()
    keys = tuple(expected[0])
    observed = [
        {key: list(row[key]) if key == "arguments" else row[key] for key in keys}
        for row in rows
    ]

    def order(row: dict[str, Any]) -> tuple[str, int, str]:
        return row["source"], row["offset"], row["callee"]

    _require(
        sorted(observed, key=order) == sorted(expected, key=order),
        "调用记录缺失、重复、错误绑定或原文位置不符",
    )
    for row in rows:
        _require(
            row["source_fingerprint"]
            == hashlib.sha256(CALL_SOURCES[row["source"]].encode("utf-8")).hexdigest(),
            "调用源文本 SHA 不符",
        )
        _require(
            row["binding"]
            == ("unknown" if row["callee"] == "MysteryAction" else "standard-global"),
            "自定义未知调用被误标标准绑定",
        )
    change = next(row for row in rows if row["callee"] == "SetPlayerState")
    mystery = next(row for row in rows if row["callee"] == "MysteryAction")
    _require(
        bool(change["controls"]) and bool(mystery["controls"]), "条件或 else 上下文丢失"
    )
    _require(
        any(
            predicate["negated"]
            for control in mystery["controls"]
            for predicate in control["predicates"]
        ),
        "else 缺少前置分支否定证据",
    )


def read_loadout_export(path: Path) -> dict[str, Any]:
    text = path.read_text("utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    if path.suffix == ".tsv":
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter="\t"))
        complete = [row for row in rows if row[0] == "complete_source"]
        _require(len(complete) == 1, "TSV 完整来源证据行遗漏或重复")
        value = json.loads(complete[0][-1])
        expected = value["selection"]["matched_records"]
        _require(
            sum(row[0] == "record" for row in rows) == expected,
            "TSV 方案行未按完整记录选择",
        )
        ordinals = set(value["selection"]["ordinals"])
        slots = sum(
            len(row["slots"])
            for row in value["document"]["records"]
            if row["ordinal"] in ordinals
        )
        _require(sum(row[0] == "slot" for row in rows) == slots, "TSV 槽位行遗漏或重复")
        return value
    marker = text.index("## 完整来源与证据")
    start = text.index("\n{", marker) + 1
    return json.JSONDecoder().raw_decode(text[start:])[0]


def validate_loadout_evidence(
    value: dict[str, Any],
    payload: bytes,
    name: str,
    *,
    selected: tuple[int, ...] | None = None,
) -> None:
    document = value["document"]
    _require(
        value["report_type"] == "offline-loadout-inspection"
        and value["report_is_plan"] is False
        and value["source_stable"] is True,
        "导出报告误作可写方案或来源未复验",
    )
    _require(
        base64.b64decode(document["raw_base64"], validate=True) == payload
        and document["sha256"] == hashlib.sha256(payload).hexdigest()
        and document["size"] == len(payload),
        "方案原始字节、长度或 SHA 丢失",
    )
    records = document["records"]
    expected_count = {"six": 1, "nine": 2, "partial": 2, "empty": 0}[name]
    _require(
        len(records) == expected_count
        and value["selection"]["total_records"] == expected_count,
        "原始完整方案记录数不符",
    )
    expected_selected = list(
        selected if selected is not None else range(1, expected_count + 1)
    )
    _require(
        value["selection"]["ordinals"] == expected_selected
        and value["selection"]["matched_records"] == len(expected_selected),
        "筛选完整方案集合不符",
    )
    _require(
        document["status"] == ("partial" if name == "partial" else "confirmed")
        and value["exit_code"] == (2 if name == "partial" else 0),
        "空记录、完整或部分诊断状态混淆",
    )
    text = document["raw_text"]
    for node in document["nodes"]:
        raw = payload[node["byte_offset"] : node["byte_end"]]
        _require(
            raw.decode(document["encoding"]) == text[node["offset"] : node["end"]],
            "节点原文字符/字节区间不符",
        )
    if name == "six":
        _require(
            document["kind"] == "artifact-plan"
            and document["encoding"] == "utf-16-le"
            and document["bom_bytes"] == 2,
            "六槽 UTF16 BOM 或结构声明丢失",
        )
        _require(
            [slot["code"] for slot in records[0]["slots"]] == list(SIX_CODES),
            "重复、空格或 Latin1 四码被改写",
        )
        _require(
            [slot["index"] for slot in records[0]["slots"]] == list(range(1, 7)),
            "六槽原始顺序丢失",
        )
    elif name == "nine":
        _require(
            [record["name"] for record in records] == ["远征甲", "守城乙"]
            and [record["unit_code"] for record in records] == ["Hpal", "Hamg"],
            "九槽名称/单位证据不符",
        )
        for index, record in enumerate(records):
            _require(
                len(record["slots"]) == len(record["charges"]) == 9
                and record["requires_any_slot"] is False,
                "九槽或数量原文被截断",
            )
            _require(
                record["slots"][0]["state"] == "empty"
                and record["slots"][0]["code"] is None,
                "空槽被猜测成物品",
            )
            _require(
                [slot["code"] for slot in record["slots"][1:]]
                == ["I001" if index == 0 else "I002"] * 8,
                "重复九槽物品被去重",
            )
            _require(
                [slot["charge_literal"] for slot in record["slots"]]
                == ([HUGE_QUANTITY] if index == 0 else ["0"])
                + [str(number) for number in range(1, 9)],
                "数量 token 损失或超过整数字符配额",
            )
    elif name == "partial":
        _require(
            [len(row["slots"]) for row in records] == [6, 1],
            "重复 codes 声明被选取一个赢家",
        )
        _require(
            sum(row["code"] == "duplicate-json-key" for row in document["diagnostics"])
            == 2,
            "重复字段完整诊断丢失",
        )
        _require(
            all(
                slot["state"] == "unverified"
                for record in records
                for slot in record["slots"]
            ),
            "歧义 codes 被提升为确认物品",
        )


def validate_map_object(value: dict[str, Any]) -> None:
    _require(
        [row["id"] for row in value["records"]] == ["yV12"],
        "独立地图子物品筛选丢失或串入父物品",
    )
    record = value["records"][0]
    _require(record["label"] == MAP_NAME, "UTF16 WTS 名称未进入继承物品")
    pairs = {(row["key"], row["value"]) for row in record["values"]}
    _require(
        {("ides", MAP_DESCRIPTION), ("igol", "7"), ("igol", "91")} <= pairs,
        "继承字段、覆写价格或被覆写证据丢失",
    )
    _require(
        any(
            row["key"] == "igol"
            and row["value"] == "91"
            and row["state"] == "overridden"
            for row in record["values"]
        ),
        "被子物品覆写的父价格仍被导出为当前确认值",
    )


def validate_campaign_metadata(
    value: dict[str, Any], *, trailing: bool = False
) -> None:
    raw = authored_w3f() + (b"\xde\xad\xbe\xef" if trailing else b"")
    _require(base64.b64decode(value["raw_bytes_base64"]) == raw, "W3F 原始完整字节丢失")
    _require(
        value["name"] == CAMPAIGN_NAME and value["version"] == 3,
        "战役 UTF16BE 名称或版本不符",
    )
    expected = {
        "fog_height_start": 16.0,
        "fog_height_end": 256.0,
        "fog_linear_start": 32.0,
        "fog_linear_end": 512.0,
        "fog_max_opacity": 0.75,
        "fog_draw_over_sky": 1,
        "background_version": 9,
    }
    _require(
        all(value[key] == expected_value for key, expected_value in expected.items()),
        "W3F v3 fog/background 字段错位",
    )
    _require(
        value["maps"]
        == [
            {
                "path": CHILD_MEMBER,
                "display_name": CHAPTER_TITLE,
                "chapter_name": CHAPTER_NAME,
                "initially_visible": True,
            }
        ],
        "战役显示字符串被当作成员路径或标题丢失",
    )
    _require(
        value["complete"] is (not trailing) and value["maps_complete"] is True,
        "W3F 已确认地图与剩余字节边界混淆",
    )
    _require(
        base64.b64decode(value["unconsumed_data_base64"])
        == (b"\xde\xad\xbe\xef" if trailing else b""),
        "W3F 未解析尾部丢失",
    )


__all__ = (
    "read_loadout_export",
    "validate_call_evidence",
    "validate_campaign_metadata",
    "validate_loadout_evidence",
    "validate_map_object",
)
