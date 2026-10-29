"""Authored inert scripts and actual Tk analysis-report acceptance."""

from __future__ import annotations

import json
import re
import tkinter as tk
from typing import TYPE_CHECKING, Any

import customtkinter as ctk

if TYPE_CHECKING:
    from .gui import App
    from .gui_offline_acceptance_support import _Fixtures


# Fixed independent contract data is inserted by the task's preparation script.
DIAGNOSTIC_SOURCES: dict[str, str] = {
    "positive.j": "// GetLocalPlayer() DzGetMouseX() GetCameraTargetPositionX()\n"
    "function LocalCase takes nothing returns nothing\n"
    "if GetLocalPlayer() == Player(0) then\n"
    "if true then\n"
    "call DoNothing()\n"
    "endif\n"
    "loop\n"
    "call CreateUnit(Player(0), 'hfoo', 0, 0, 0)\n"
    "exitwhen true\n"
    "endloop\n"
    "else\n"
    "call SetPlayerState(Player(0), PLAYER_STATE_RESOURCE_GOLD, 5)\n"
    "endif\n"
    "endfunction\n"
    "function LocalRead takes nothing returns player\n"
    "return GetLocalPlayer()\n"
    "endfunction\n"
    "function Independent takes nothing returns nothing\n"
    "call CreateUnit(Player(0), 'hfoo', 1, 2, 0)\n"
    'call DisplayTextToPlayer(Player(0), 0, 0, "GetLocalPlayer() '
    'DzFake()")\n'
    "endfunction\n",
    "positive.lua": "--[=[ GetLocalPlayer() DzGetMouseX() GetCameraTargetPositionX() ]=]\n"
    "local text = [==[GetLocalPlayer() DzFake()]==]\n"
    "local readLocal = GetLocalPlayer\n"
    "local makeUnit = CreateUnit\n"
    "function LocalCase()\n"
    "if readLocal() == Player(0) then\n"
    "if true then DoNothing() end\n"
    "makeUnit(Player(0), FourCC('hfoo'), 0, 0, 0)\n"
    "local callback = function()\n"
    "CreateUnit(Player(0), FourCC('hfoo'), 3, 4, 0)\n"
    "end\n"
    "else\n"
    "SetPlayerState(Player(0), PLAYER_STATE_RESOURCE_GOLD, 5)\n"
    "end\n"
    "end\n"
    "function Independent()\n"
    "CreateUnit(Player(0), FourCC('hfoo'), 1, 2, 0)\n"
    "end\n",
    "negative.j": "// GetLocalPlayer() DzGetMouseX() GetCameraTargetPositionX()\n"
    "function Independent takes nothing returns nothing\n"
    'call DisplayTextToPlayer(Player(0), 0, 0, "GetLocalPlayer() '
    'DzFake()")\n'
    "call CreateUnit(Player(0), 'hfoo', 0, 0, 0)\n"
    "endfunction\n",
    "negative.lua": "--[====[ GetLocalPlayer() DzGetMouseX() GetCameraTargetPositionX() "
    "]====]\n"
    "local text = [==[GetLocalPlayer() DzFake()]==]\n"
    "function GetLocalPlayer() return nil end\n"
    "function Independent()\n"
    "if GetLocalPlayer() then\n"
    "CreateUnit(Player(0), FourCC('hfoo'), 0, 0, 0)\n"
    "end\n"
    "end\n",
}
DIAGNOSTIC_CONTRACTS: tuple[dict[str, Any], ...] = (
    {
        "file": "positive.j",
        "source": "war3map.j",
        "local_reads": [
            {"callee": "GetLocalPlayer", "line": 3, "offset": 113},
            {"callee": "GetLocalPlayer", "line": 16, "offset": 395},
        ],
        "mutations": [
            {"callee": "CreateUnit", "line": 8, "offset": 194},
            {"callee": "SetPlayerState", "line": 12, "offset": 265},
        ],
        "expected_codes": [
            "script.get_local_player",
            "script.get_local_player.sync_mutation",
        ],
        "forbidden_codes": [
            "script.local_state.camera",
            "script.local_state.mouse",
            "script.dz_api",
            "script.binding.unknown",
            "script.local_mutation.unknown",
        ],
        "owner_of_mutations": "LocalCase",
        "non_mutation_owners": ["Independent", "LocalRead", "<anonymous callback>"],
    },
    {
        "file": "positive.lua",
        "source": "war3map.lua",
        "local_reads": [{"callee": "readLocal", "line": 6, "offset": 200}],
        "mutations": [
            {"callee": "makeUnit", "line": 8, "offset": 259},
            {"callee": "SetPlayerState", "line": 13, "offset": 388},
        ],
        "expected_codes": [
            "script.get_local_player",
            "script.get_local_player.sync_mutation",
        ],
        "forbidden_codes": [
            "script.local_state.camera",
            "script.local_state.mouse",
            "script.dz_api",
            "script.binding.unknown",
            "script.local_mutation.unknown",
        ],
        "owner_of_mutations": "LocalCase",
        "non_mutation_owners": ["Independent", "LocalRead", "<anonymous callback>"],
    },
    {
        "file": "negative.j",
        "source": "war3map.j",
        "local_reads": [],
        "mutations": [],
        "expected_codes": [],
        "forbidden_codes": [
            "script.local_state.camera",
            "script.local_state.mouse",
            "script.dz_api",
            "script.binding.unknown",
            "script.local_mutation.unknown",
        ],
        "owner_of_mutations": "LocalCase",
        "non_mutation_owners": ["Independent", "LocalRead", "<anonymous callback>"],
    },
    {
        "file": "negative.lua",
        "source": "war3map.lua",
        "local_reads": [],
        "mutations": [],
        "expected_codes": [],
        "forbidden_codes": [
            "script.local_state.camera",
            "script.local_state.mouse",
            "script.dz_api",
            "script.binding.unknown",
            "script.local_mutation.unknown",
        ],
        "owner_of_mutations": "LocalCase",
        "non_mutation_owners": ["Independent", "LocalRead", "<anonymous callback>"],
    },
)


def diagnostic_fixture_payloads() -> dict[str, bytes]:
    from .gui_offline_acceptance_support import _fixture_mpq

    payloads = {}
    for contract in DIAGNOSTIC_CONTRACTS:
        name = contract["file"]
        payload = DIAGNOSTIC_SOURCES[name].encode("utf-8")
        payloads[f"diagnostics/{name}"] = payload
        payloads[f"diagnostics/{name}.w3x"] = _fixture_mpq(
            {contract["source"]: payload}
        )
    payloads["diagnostics/expected.json"] = (
        json.dumps(DIAGNOSTIC_CONTRACTS, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    return payloads


def validate_diagnostic_lines(name: str, lines: tuple[str, ...]) -> None:
    """Verify independently specified calls, scopes and source spans in display text."""
    from .gui_offline_acceptance_support import _require

    contract = next(row for row in DIAGNOSTIC_CONTRACTS if row["file"] == name)
    if not contract["expected_codes"]:
        _require(not lines, f"注释、字符串或自定义绑定产生虚假诊断: {name}")
        return
    titles = ("本地玩家分支", "本地条件内的状态修改调用")
    _require(
        len(lines) == len(titles)
        and all(
            line.startswith(f"[警告] {title}:") for line, title in zip(lines, titles)
        ),
        f"脚本诊断分组错误: {name}",
    )
    source = DIAGNOSTIC_SOURCES[name]
    language = "JASS" if name.endswith(".j") else "Lua"
    for line, key in zip(lines, ("local_reads", "mutations"), strict=True):
        expected_calls = contract[key]
        actual = re.findall(
            r"(?m)^([^\n]+? / 偏移 \d+:\d+ · (?:JASS|Lua) · 所属函数 [^\n]+)",
            line,
        )
        _require(len(actual) == len(expected_calls), f"诊断调用数量错误: {name}/{key}")
        for expected in expected_calls:
            start = expected["offset"]
            callee = expected["callee"]
            if key == "local_reads":
                raw = f"{callee}()"
                canonical = "GetLocalPlayer"
                owner = (
                    "LocalRead"
                    if name.endswith(".j") and expected["line"] == 16
                    else "LocalCase"
                )
            else:
                raw = source[start:].split("\n", 1)[0]
                canonical = "CreateUnit" if callee == "makeUnit" else callee
                owner = contract["owner_of_mutations"]
            _require(source[start : start + len(raw)] == raw, "诊断固定源偏移契约失配")
            prefix = (
                f"{contract['source']}:{expected['line']} / 偏移 {start}:{start + len(raw)} · "
                f"{language} · 所属函数 {owner} · 调用 {callee} → {canonical} · 绑定 standard-global"
            )
            _require(
                line.count(prefix) == 1 and f"原文 {raw}" in line,
                f"诊断来源证据遗漏或重复: {name}/{callee}@{start}",
            )
        if key == "mutations":
            _require(
                all(
                    f"所属函数 {owner} ·" not in line
                    for owner in contract["non_mutation_owners"]
                )
                and line.count("此前分支不成立") == 1
                and line.count("当前条件") == 1
                and line.count("范围完整") == 2,
                f"本地条件跨函数污染、嵌套丢失或 else 证据错误: {name}",
            )
            read = contract["local_reads"][0]
            _require(
                line.count(f"本地调用 {read['callee']}@{read['offset']}") == 2,
                f"本地谓词来源缺失: {name}",
            )


def _labels(widget: tk.Misc) -> list[str]:
    pending = [widget]
    result = []
    while pending:
        child = pending.pop()
        if isinstance(child, ctk.CTkLabel):
            result.append(str(child.cget("text")))
        pending.extend(reversed(child.winfo_children()))
    return result


def exercise_script_diagnostics(
    app: App, fixtures: _Fixtures, owned: list[tk.Toplevel], errors: list[str]
) -> None:
    from .gui_offline_acceptance_support import _require, _wait_for
    from .gui_offline_acceptance_support import loaded_acceptance_map

    _ = owned
    for contract in DIAGNOSTIC_CONTRACTS:
        name = contract["file"]
        with loaded_acceptance_map(app, fixtures.root / "diagnostics" / f"{name}.w3x"):
            app.tabs.set("分析报告")
            _wait_for(
                app,
                lambda: app.tabs.get() == "分析报告" and bool(app.analysis_cards),
                "真实脚本诊断分析面板",
                errors,
            )
            cards = [_labels(card) for card in app.analysis_cards]
            matched = [labels for labels in cards if "脚本诊断" in labels]
            expected_groups = len(contract["expected_codes"])
            _require(
                len(matched) == (1 if expected_groups else 0),
                f"实际分析卡片脚本诊断存在性不符: {name}",
            )
            labels = matched[0] if matched else []
            lines = tuple(
                label[2:] for label in labels if label.startswith("● [警告] ")
            )
            validate_diagnostic_lines(name, lines)
            _require(
                (f"警告 {len(lines)}" in labels if lines else not labels),
                f"脚本诊断实际卡片状态不符: {name}",
            )
            _require(app.analysis_box is not None, "实际完整分析报告部件缺失")
            assert app.analysis_box is not None
            full_report = app.analysis_box.get("1.0", "end-1c")
            rendered = (
                (
                    full_report.split("【脚本诊断】", 1)[1]
                    .split("\n\n【", 1)[0]
                    .removeprefix("\n")
                )
                if lines
                else ""
            )
            _require(
                rendered == "\n".join(lines)
                and (bool(lines) or "【脚本诊断】" not in full_report),
                f"脚本诊断可见卡片与完整文本不一致: {name}",
            )
            destination = fixtures.root / "reports" / f"diagnostics-{name}.json"
            destination.parent.mkdir(exist_ok=True)
            destination.write_text(
                json.dumps(
                    {
                        "input": f"diagnostics/{name}.w3x",
                        "source": contract["source"],
                        "static_only": True,
                        "script_executed": False,
                        "visible_labels": labels,
                        "diagnostic_lines": lines,
                        "full_report": full_report,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
