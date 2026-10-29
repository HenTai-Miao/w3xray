"""Exercise the shipped query catalog against a freshly exported pack."""

from __future__ import annotations

import json
from pathlib import Path

from .pack_query_cli import _QUERIES, _object_rows, execute_pack_query
from .pack_query_options import PackQueryCliOptions
from .pack_query_execution import PackQueryResult


def check_query_workflow(pack: Path) -> str:
    """Validate every query mode, a readable export and the shared replay state."""
    if not (pack / "资料包目录.tsv").is_file():
        raise ValueError("查询验收缺少本轮生成的知识包")
    code = ""
    for category in ("单位", "物品", "技能", "英雄", "科技", "增益"):
        rows = _object_rows(pack, category)
        if len(rows) > 1:
            code = rows[1][1]
            break
    target = code or "*"
    queries = {
        "item": "",
        "recipe": target,
        "where": target,
        "drop": target,
        "quest": "",
        "text": target,
        "price": "",
        "shop": "",
        "tech": "",
        "cmd": "",
        "calls": "",
        "refs": target,
        "near": "0 0 500",
        "locate": target,
        "affixes": "",
        "registered": "",
        "diff": "",
        "search": target,
        "list": "",
        "doc": target,
        "buffs": "",
        "export": target,
        "stats": "",
        "synth": "",
        "skills": "",
        "units": "",
        "heroes": "",
        "again": "",
    }
    if set(queries) != set(_QUERIES):
        raise ValueError("查询目录已变化，必须同步完整使用链验收")
    exported = "no object records; empty recovery checked"
    for command, query in queries.items():
        options = PackQueryCliOptions(
            str(pack),
            command,
            query,
            limit=1,
            pack_dir_b=str(pack) if command == "diff" else "",
        )
        result = execute_pack_query(options)
        _require_structured_result(result)
        if command in ("stats", "list") and result.exit_code != 0:
            raise ValueError(f"{command} 不能读取本轮知识包")
        if command == "export" and code:
            paths = [
                Path(line.removeprefix("已导出: "))
                for section in result.sections
                for line in section.lines
                if line.startswith("已导出: ")
            ]
            if result.exit_code != 0 or len(paths) != 1 or not paths[0].is_file():
                raise ValueError("已确认对象的报告无法导出重开")
            text = paths[0].read_text(encoding="utf-8")
            if not text or code not in text:
                raise ValueError("导出的对象报告缺少本轮对象证据")
            exported = str(paths[0])
    # A known successful query must survive an input error and replay identically.
    expected = execute_pack_query(PackQueryCliOptions(str(pack), "list", ""))
    invalid = execute_pack_query(PackQueryCliOptions(str(pack), "near", "invalid"))
    if invalid.exit_code != 2:
        raise ValueError("无效坐标未返回明确输入错误")
    replay = execute_pack_query(PackQueryCliOptions(str(pack), "again", ""))
    expected_lines = tuple(
        line for section in expected.sections for line in section.lines
    )
    replay_lines = tuple(
        line
        for section in replay.sections
        for line in section.lines
        if not line.startswith("[重跑]")
    )
    if replay.exit_code != 0 or replay_lines != expected_lines:
        raise ValueError("失败查询覆盖了最近成功查询，或 again 不能完整重跑")
    return f"modes={len(queries)}; structured JSON; export={exported}; failed-input recovery; again"


def _require_structured_result(result: PackQueryResult) -> None:
    payload = json.loads(result.render(as_json=True))
    if result.exit_code not in (0, 2) or payload["exit_code"] != result.exit_code:
        raise ValueError("查询退出状态与结构化结果不一致")
    if not result.sections or not all(section.lines for section in result.sections):
        raise ValueError("查询没有给出证据或空结果恢复说明")
    if result.command == "calls":
        if not (
            isinstance(payload.get("calls"), list)
            and isinstance(payload.get("call_diagnostics"), list)
            and isinstance(payload.get("checked_packs"), list)
            and payload.get("source_stable") is True
            and type(payload.get("calls_total")) is int
            and type(payload.get("calls_omitted")) is int
            and payload["calls_omitted"] >= 0
            and payload["calls_total"]
            == len(payload["calls"]) + payload["calls_omitted"]
        ):
            raise ValueError("脚本调用缺少完整记录计数、来源稳定性或结构化诊断")
