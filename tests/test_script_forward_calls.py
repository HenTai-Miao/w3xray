"""JASS declaration-order evidence respects source language and exact bindings."""

import csv
from dataclasses import replace
from io import StringIO

import pytest

from gametool.audit import build_audit_report
from gametool.batch_tsv import decode_tsv_cell
from gametool.batch_tsv import format_tsv_rows
from gametool.cli_detail_summary import iter_script_diagnostic_lines
from gametool.diagnostics import build_script_diagnostics
from gametool.map_data import MapData
from gametool.script_forward_calls import (
    build_forward_call_report,
    format_forward_call_report_tsv,
)
from gametool.script_sources import WCT_TEXT_NAME
from gametool import script_forward_calls
from gametool import script_control_ranges
from gametool.script_scopes import script_structure
from gametool.script_symbols import ScriptSymbols
from gametool.script_control_ranges import control_ranges, prepare_control_source


def _jass(body: str, *, name: str = "Entry") -> str:
    return f"function {name} takes nothing returns nothing\n{body}\nendfunction\n"


def _map(script: str, *, source: str = "war3map.j") -> MapData:
    return MapData(
        path="synthetic-forward.w3x", name="前向引用", scripts={source: script}
    )


def test_direct_calls_and_function_references_have_separate_exact_evidence() -> None:
    script = (
        "// 中文 source offsets\r\n"
        + _jass(
            "call Later()\ncall TriggerAddAction(t,function Later)\n"
            "call Earlier()\ncall Entry()\n"
            '// call Hidden()\ncall BJDebugMsg("function Hidden call Hidden()")'
        )
        + _jass("", name="Later")
    )
    script = _jass("", name="Earlier") + script
    md = _map(script)
    report = build_forward_call_report(md)
    assert [(item.callee, item.form) for item in report.forward_calls] == [
        ("Later", "call"),
        ("Later", "function-reference"),
    ]
    assert not any(item.callee == "Hidden" for item in report.items)
    for item in report.forward_calls:
        assert item.language == "JASS" and item.owner == "Entry"
        assert script[item.offset : item.end_offset] == item.raw
        assert item.line == len(script[: item.offset].splitlines())
        assert item.binding == "source-function" and "Later" in item.declarations[0]
        assert item.source_fingerprint.startswith("analysis-text-sha256:")
    assert {
        item.state for item in report.items if item.callee in {"Entry", "Earlier"}
    } == {"declared"}
    assert md.scripts["war3map.j"] == script


def test_nested_expression_forward_call_is_also_a_direct_call() -> None:
    script = _jass("call BJDebugMsg(I2S(Later()))") + _jass("return 1", name="Later")
    assert [
        item.callee for item in build_forward_call_report(_map(script)).forward_calls
    ] == ["Later"]


def test_standard_dependency_never_hides_a_source_visible_override() -> None:
    md = _map(_jass("call CreateUnit(p,'hfoo',0,0,0)"))
    (native,) = [
        item
        for item in build_forward_call_report(md).items
        if item.callee == "CreateUnit"
    ]
    assert native.state == "external" and native.binding == "standard-dependency"
    md.scripts["war3map.j"] += _jass("", name="CreateUnit")
    assert [item.callee for item in build_forward_call_report(md).forward_calls] == [
        "CreateUnit"
    ]


def test_declared_native_and_duplicate_native_keep_order_uncertainty() -> None:
    script = "native CustomNative takes nothing returns nothing\n" + _jass(
        "call CustomNative()"
    )
    (item,) = build_forward_call_report(_map(script)).items
    assert item.state == "declared" and item.binding == "source-native"
    duplicate = build_forward_call_report(
        _map(script + "native CustomNative takes nothing returns nothing\n")
    )
    assert (
        duplicate.items[0].state == "unknown"
        and "不唯一" in duplicate.items[0].diagnostic
    )
    late_native = build_forward_call_report(
        _map(
            _jass("call CustomNative()")
            + "native CustomNative takes nothing returns nothing\n"
        )
    )
    assert late_native.items[0].state == "unknown" and not late_native.forward_calls


@pytest.mark.parametrize(
    "local", ["local code Later", "local code Later = null", "local integer Later = 0"]
)
def test_local_overrides_never_bind_the_global_forward_definition(local: str) -> None:
    md = _map(_jass(local + "\ncall Later()") + _jass("", name="Later"))
    report = build_forward_call_report(md)
    assert not report.forward_calls
    call = next(item for item in report.items if item.callee == "Later")
    assert call.state == "unknown" and call.binding == "source-binding"


def test_alias_binding_is_not_promoted_into_a_direct_call() -> None:
    script = _jass("local code Alias = function Later\ncall Alias()") + _jass(
        "", name="Later"
    )
    report = build_forward_call_report(_map(script))
    (alias,) = [item for item in report.items if item.callee == "Alias"]
    assert alias.state == "unknown" and alias.binding == "alias"
    assert "Later" in alias.declarations[0]
    assert [(item.callee, item.form) for item in report.forward_calls] == [
        ("Later", "function-reference")
    ]


def test_duplicate_definitions_and_cross_source_matches_are_diagnostics() -> None:
    md = _map(
        _jass("call Target()") + _jass("", name="Target") + _jass("", name="Target")
    )
    report = build_forward_call_report(md)
    assert not report.forward_calls and len(report.items[0].declarations) == 2
    md.scripts = {
        "war3map.j": _jass("call Target()"),
        "custom.j": _jass("", name="Target"),
    }
    (item,) = build_forward_call_report(md).items
    assert item.binding == "cross-source" and item.state == "unknown"
    assert item.declarations[0].startswith("custom.j:")


@pytest.mark.parametrize("source", ["war3map.lua", "script.txt"])
def test_lua_and_unknown_sources_never_receive_jass_order_verdicts(source: str) -> None:
    script = _jass("call Later()") + _jass("", name="Later")
    report = build_forward_call_report(_map(script, source=source))
    assert not report.items and len(report.source_diagnostics) == 1
    assert report.source_diagnostics[0][1] == (
        "Lua" if source.endswith("lua") else "unknown"
    )


def test_wct_uses_declared_primary_language_without_moving_offsets() -> None:
    script = (
        "// ===== 全局自定义脚本 =====\n"
        + _jass("call Later()")
        + _jass("", name="Later")
    )
    md = _map("function main takes nothing returns nothing endfunction")
    md.scripts[WCT_TEXT_NAME] = script
    report = build_forward_call_report(md)
    (item,) = report.forward_calls
    assert item.source == WCT_TEXT_NAME and script[item.offset :].startswith(item.raw)
    md.scripts = {"war3map.lua": "function main() end", WCT_TEXT_NAME: script}
    assert not build_forward_call_report(md).forward_calls


def test_incomplete_owner_or_call_never_becomes_confirmed_forward() -> None:
    script = "function Entry takes nothing returns nothing\ncall Later(\n" + _jass(
        "", name="Later"
    )
    report = build_forward_call_report(_map(script))
    assert not report.forward_calls and report.items[0].state == "unknown"
    assert "未闭合" in report.items[0].diagnostic


def test_shared_contexts_retain_all_visible_call_sites() -> None:
    script = (
        _jass("call Later()", name="Helper")
        + _jass("call Helper()\ncall Helper()")
        + _jass("", name="Later")
    )
    (item,) = build_forward_call_report(_map(script)).forward_calls
    assert len([context for context in item.contexts if "Helper()" in context]) == 2


def test_full_call_coverage_and_reversible_query_table() -> None:
    count = 1300
    script = _jass("\n".join("call Later()" for _ in range(count))) + _jass(
        "", name="Later"
    )
    report = build_forward_call_report(_map(script))
    assert len(report.forward_calls) == count
    rows = list(
        csv.reader(StringIO(format_forward_call_report_tsv(report)), delimiter="\t")
    )
    assert len(rows) == count + 1
    assert decode_tsv_cell(rows[-1][12]) == "Later()"


def test_existing_analysis_and_cli_show_source_locatable_forward_diagnostics() -> None:
    md = _map(_jass("call Later()") + _jass("", name="Later"))
    diagnostic = next(
        item
        for item in build_script_diagnostics(md).items
        if item.code.startswith("script.jass.forward.")
    )
    assert diagnostic.evidence is not None and diagnostic.evidence.callee == "Later"
    output = "\n".join(iter_script_diagnostic_lines(md))
    assert (
        "JASS 直接前向引用" in output and "war3map.j:2" in output and "偏移" in output
    )
    assert "script.diagnostics" in build_audit_report(md).by_code


def test_changed_loaded_script_snapshot_never_delivers_confirmed_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    md = _map(_jass("call Later()") + _jass("", name="Later"))
    original = script_forward_calls.script_functions

    def changed(text: str, *, lua: bool | None):
        md.scripts["war3map.j"] += "\n// concurrent replacement"
        return original(text, lua=lua)

    monkeypatch.setattr(script_forward_calls, "script_functions", changed)
    report = build_forward_call_report(md)
    assert not report.forward_calls and report.items[0].state == "unknown"
    assert "快照" in report.items[0].diagnostic
    assert report.source_diagnostics[-1][0] == "<loaded-script-snapshot>"


def test_each_owner_reuses_the_bound_full_source_view_after_global_cache_eviction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    count = 64
    source = "\n".join(
        _jass("if true then\ncall External()\nendif", name=f"F{index}")
        for index in range(count)
    )
    structure = script_structure(source, lua=False)
    symbols = ScriptSymbols(source, structure, lua=False)
    original = script_control_ranges.script_views
    full_source_preparations = 0

    def observed(text: str, *, lua: bool | None = None):
        nonlocal full_source_preparations
        if text is source:
            full_source_preparations += 1
        return original(text, lua=lua)

    monkeypatch.setattr(script_control_ranges, "script_views", observed)
    for function in structure.functions:
        # Evict the process-global lexical LRU with unrelated expressions. The
        # source-bound owner index must remain independent of cache residency.
        for index in range(9):
            original(f"different_{function.start}_{index}()", lua=False)
        ranges, _lookup = symbols.control_data(function.start)
        assert len(ranges) == 1 and ranges[0].condition == "true"
        assert source[ranges[0].start : ranges[0].end].strip() == "call External()"
    assert full_source_preparations == 0


def test_all_owner_contexts_are_flattened_once_without_losing_any_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body_count, incoming_count = 48, 32
    source = (
        _jass("\n".join("call Later()" for _ in range(body_count)), name="Helper")
        + _jass("\n".join("call Helper()" for _ in range(incoming_count)))
        + _jass("", name="Later")
    )
    original = script_forward_calls._contexts
    preparations: dict[int | None, int] = {}

    def observed(contexts, owner):
        preparations[owner] = preparations.get(owner, 0) + 1
        return original(contexts, owner)

    monkeypatch.setattr(script_forward_calls, "_contexts", observed)
    report = build_forward_call_report(_map(source))
    assert len(report.items) == body_count + incoming_count
    helper = [item for item in report.items if item.owner == "Helper"]
    assert len(helper) == body_count and len(helper[0].contexts) == incoming_count
    assert all(item.contexts == helper[0].contexts for item in helper)
    assert all(item.contexts is helper[0].contexts for item in helper)
    assert set(preparations.values()) == {1}


@pytest.mark.parametrize("lua", [False, True])
def test_prepared_owner_ranges_equal_legacy_ranges_with_full_raw_offsets(
    lua: bool,
) -> None:
    source = (
        'function Outer()\nif flag then\nEmit("end if")\n'
        'local function Child() if inner then Emit("child") end end\n'
        'elseif other then Emit("second") else Emit("last") end\nend'
        if lua
        else _jass(
            'if flag then\ncall Emit("endif if")\nelseif other then\n'
            'loop\ncall Emit("loop")\nendloop\nelse\ncall Emit("last")\nendif'
        )
    )
    structure = script_structure(source, lua=lua)
    prepared = prepare_control_source(source, structure, lua)
    for function in (None, *structure.functions):
        legacy = control_ranges(source, function, structure, lua)
        shared = control_ranges(source, function, structure, lua, prepared=prepared)
        assert shared == legacy
        assert [source[item.start : item.end] for item in shared] == [
            source[item.start : item.end] for item in legacy
        ]


def test_prepared_control_views_reject_foreign_source_language_structure_and_owner() -> (
    None
):
    source = _jass("if true then\ncall Work()\nendif")
    structure = script_structure(source, lua=False)
    prepared = prepare_control_source(source, structure, False)
    (function,) = structure.functions
    foreign_source = source.encode("utf-8").decode("utf-8")
    assert foreign_source == source and foreign_source is not source
    requests = [
        (foreign_source, function, structure, False),
        (source, function, structure, True),
        (source, function, script_structure(source + "\n", lua=False), False),
        (source, replace(function), structure, False),
    ]
    for text, owner, scopes, lua in requests:
        with pytest.raises(ValueError, match="identity/language/function"):
            control_ranges(text, owner, scopes, lua, prepared=prepared)


def test_formatter_joins_shared_context_once_and_preserves_every_full_record() -> None:
    iterations = 0

    class ObservedContexts(tuple[str, ...]):
        def __iter__(self):
            nonlocal iterations
            iterations += 1
            return super().__iter__()

    report = build_forward_call_report(
        _map(_jass("call Later()\ncall Later()") + _jass("", name="Later"))
    )
    contexts = ObservedContexts(
        ("first\tcontext", "second\r\ncontext", "'\u2060literal-prefix")
    )
    shared = replace(
        report, items=tuple(replace(item, contexts=contexts) for item in report.items)
    )
    encoded = format_forward_call_report_tsv(shared)
    rows = list(csv.reader(StringIO(encoded, newline=""), delimiter="\t"))
    assert len(rows) == len(shared.items) + 1
    assert [decode_tsv_cell(row[12]) for row in rows[1:]] == [
        item.raw for item in shared.items
    ]
    assert all(
        decode_tsv_cell(row[13])
        == "first\tcontext\nsecond\r\ncontext\n'\u2060literal-prefix"
        for row in rows[1:]
    )
    assert iterations == 1


def test_forward_tsv_bytes_match_the_legacy_flat_record_contract() -> None:
    report = build_forward_call_report(
        _map(
            _jass("call Later()\ncall TriggerAddAction(t,function Later)")
            + _jass("", name="Later")
        )
    )
    report = replace(
        report,
        items=tuple(
            replace(item, contexts=("all\tcontext", "all\r\nsource", "'\u2060literal"))
            for item in report.items
        ),
        source_diagnostics=(("raw\t源.lua", "Lua", "Lua\r\n边界"),),
    )
    # This is the pre-optimization on-disk schema: same records, ordering,
    # complete contexts and shared reversible cell serialization.
    legacy = [
        (
            "来源",
            "语言",
            "行",
            "偏移",
            "结束偏移",
            "调用名",
            "形式",
            "所属函数",
            "绑定",
            "状态",
            "声明证据",
            "诊断",
            "原始证据",
            "调用上下文",
            "来源指纹",
        )
    ]
    for item in report.items:
        legacy.append(
            (
                item.source,
                item.language,
                str(item.line),
                str(item.offset),
                str(item.end_offset),
                item.callee,
                item.form,
                item.owner,
                item.binding,
                item.state,
                "\n".join(item.declarations),
                item.diagnostic,
                item.raw,
                "\n".join(item.contexts),
                item.source_fingerprint,
            )
        )
    for source, language, diagnostic in report.source_diagnostics:
        legacy.append(
            (
                source,
                language,
                "",
                "",
                "",
                "",
                "source-coverage",
                "",
                "",
                "not-applied",
                "",
                diagnostic,
                "",
                "",
                "",
            )
        )
    assert format_forward_call_report_tsv(report).encode("utf-8") == format_tsv_rows(
        legacy
    ).encode("utf-8")
