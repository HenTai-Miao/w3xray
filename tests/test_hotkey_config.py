"""Independent synthetic inputs exercise the offline hotkey evidence boundary."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from gametool import hotkey_config
from gametool.hotkey_config import (
    canonical_hotkey,
    diff_hotkey_configs,
    inspect_hotkey_config,
    parse_hotkey_json,
    raw_hotkey_node,
)
from gametool.hotkey_config_cli import hotkey_result_to_dict
from gametool.windows_output_paths import native_output_path


def binding(name="ability_1", source="M", target="M", group="ability", slot=0, **extra):
    return {
        "binding_id": name,
        "source": source,
        "target": target,
        "group": group,
        "slot_index": slot,
        **extra,
    }


def config(*bindings, **profile_fields) -> dict[str, Any]:
    return {
        "language": "auto",
        "active_profile": "One",
        "profiles": {"One": {"bindings": list(bindings), **profile_fields}},
    }


def write_config(tmp_path: Path, value, name="config.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def codes(result, basis=None):
    return {d.code for d in result.diagnostics if basis is None or d.basis == basis}


def test_independent_minimal_profile_keeps_original_and_fills_projection_only(tmp_path):
    path = write_config(tmp_path, config(binding()))
    before = path.read_bytes(), path.stat().st_mtime_ns
    result = inspect_hotkey_config(path)
    assert result.exit_code == 0
    assert result.inspection_complete
    assert result.source.sha256 == hashlib.sha256(before[0]).hexdigest()
    assert base64.b64decode(result.source.raw_base64) == before[0]
    assert len(result.profiles[0].bindings) == 1
    assert len(result.profiles[0].compatibility_bindings) == 42
    assert result.profiles[0].compatibility_bindings[-1].binding_id == "shop_12"
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert not result.runtime_verified
    assert "静态读取合同重建" in result.contract_basis


def test_nonempty_target_rewrite_and_empty_target_are_separate_evidence(tmp_path):
    path = write_config(tmp_path, config(binding(target="F24")))
    result = inspect_hotkey_config(path)
    assert result.profiles[0].bindings[0].target == "F24"
    assert result.profiles[0].compatibility_bindings[0].target == "M"
    assert "compatibility-target-rewritten" in codes(result)
    empty = inspect_hotkey_config(
        write_config(tmp_path, config(binding(target="")), "empty.json")
    )
    assert empty.exit_code == 0
    assert empty.profiles[0].compatibility_bindings[0].target == ""


def test_duplicate_json_keys_and_all_nested_extensions_remain_lossless(tmp_path):
    text = '{"language":"auto","active_profile":"One","profiles":{"One":{"bindings":[{"binding_id":"ability_1","source":"M","source":"Q","target":"M","group":"ability","slot_index":0,"extra":{"k":1,"k":2}}],"ext":"a\\tb\\n\\r\\n\\ufeff"},"One":{"bindings":[]}},"extra":17,"extra":18}'
    path = tmp_path / "duplicates.json"
    path.write_text(text, encoding="utf-8")
    result = inspect_hotkey_config(path)
    assert result.exit_code == 2
    assert len(result.profiles) == 2
    assert not result.profiles[0].compatibility_complete
    assert sum(d.code == "duplicate-json-key" for d in result.diagnostics) == 4
    encoded = hotkey_result_to_dict(result)
    assert encoded["source"]["utf8_text"] == text
    source_nodes = [
        n for n in result.nodes if n.kind == "string" and n.value in {"M", "Q"}
    ]
    assert len(source_nodes) == 3
    assert any(
        n.kind == "string" and n.value == "a\tb\n\r\n\ufeff" for n in result.nodes
    )
    assert '"source":"M","source":"Q"' in raw_hotkey_node(
        result, result.profiles[0].bindings[0].node
    )


def test_repeated_id_and_slot_keep_rows_and_show_explicit_last_row_projection(tmp_path):
    path = write_config(
        tmp_path,
        config(
            binding(),
            binding(source="F24", target="F24"),
            binding("custom_x", "F23", "F23", slot=0),
        ),
    )
    result = inspect_hotkey_config(path)
    assert len(result.profiles[0].bindings) == 3
    assert {
        "duplicate-binding-id",
        "duplicate-slot",
        "compatibility-last-id-wins",
        "compatibility-dropped-id",
    } <= codes(result)
    projection = result.profiles[0].compatibility_bindings
    assert projection[0].source == "F24"
    assert projection[0].origin_ordinal == 2
    assert all(row.binding_id != "custom_x" for row in projection)
    assert (
        len(next(d for d in result.diagnostics if d.code == "duplicate-slot").related)
        == 3
    )


def test_legacy_roles_preserved_and_known_prefixes_migrate_independently(tmp_path):
    path = write_config(
        tmp_path,
        config(
            binding("command_1", group="command"),
            binding("inventory_1", "1", "1", "inventory"),
        ),
    )
    result = inspect_hotkey_config(path)
    rows = result.profiles[0].bindings
    assert [(r.binding_id, r.declared_group) for r in rows] == [
        ("command_1", "command"),
        ("inventory_1", "inventory"),
    ]
    assert [(r.compatible_id, r.compatible_group) for r in rows] == [
        ("ability_1", "ability"),
        ("item_1", "item"),
    ]
    assert result.exit_code == 0


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (" shift + control + q ", "CTRL+SHIFT+Q"),
        ("Ctl+Ctl+F24", "CTRL+F24"),
        ("numpad2", "NUM2"),
        ("Mouse 4", "MOUSE4"),
        ("+q++", "Q"),
        ("SEMICOLON", "SEMICOLON"),
    ],
)
def test_evidenced_key_grammar(source, expected):
    assert canonical_hotkey(source) == expected


@pytest.mark.parametrize(
    "source", ["+", "Ctrl", "Q+W", "NUM+", "Ctrl+NUM+", ";", "F25", "LeftMouse"]
)
def test_unknown_or_ambiguous_key_grammar_is_not_guessed(source):
    with pytest.raises(ValueError):
        canonical_hotkey(source)


def test_source_mouse_allowed_but_target_and_projected_mouse_rejected(tmp_path):
    assert canonical_hotkey("XButton1") == "MOUSE4"
    with pytest.raises(ValueError, match="禁止鼠标"):
        canonical_hotkey("XButton1", allow_mouse=False)
    result = inspect_hotkey_config(
        write_config(tmp_path, config(binding(source="Mouse4")))
    )
    assert result.profiles[0].bindings[0].canonical_source == "MOUSE4"
    assert any(
        d.code == "key-parse" and d.basis == "static_compatibility"
        for d in result.diagnostics
    )


def test_disabled_bindings_and_disabled_camera_still_have_syntax_diagnostics(tmp_path):
    result = inspect_hotkey_config(
        write_config(
            tmp_path,
            config(
                binding(source="NOT_A_KEY", enabled=False),
                camera_enabled=False,
                camera_rotate_up_key="MOUSE5",
            ),
        )
    )
    errors = [d for d in result.diagnostics if d.code == "key-parse"]
    assert any("source" in d.path for d in errors)
    assert any("camera_rotate_up_key" in d.path for d in errors)
    assert "duplicate-source" not in codes(result, "original_declaration")


def test_slot_none_default_is_not_final_validation_acceptance(tmp_path):
    row = binding()
    del row["slot_index"]
    result = inspect_hotkey_config(write_config(tmp_path, config(row)))
    assert "slot-range" in codes(result)
    assert result.exit_code == 1
    assert result.profiles[0].compatibility_bindings[0].state == "invalid_declared_slot"


def test_command_contexts_are_exclusive_and_item_overlap_is_conditional(tmp_path):
    result = inspect_hotkey_config(
        write_config(
            tmp_path,
            config(
                binding(source="Q", target="Q"),
                binding("spellbook_1", "Q", "Q", "spellbook"),
                binding("shop_1", "Q", "Q", "shop"),
                binding("item_1", "Ctrl+Q", "Ctrl+Q", "item"),
            ),
        )
    )
    original = [
        d
        for d in result.diagnostics
        if d.code == "possible-overlap" and d.basis == "original_declaration"
    ]
    assert len(original) == 3
    assert all("并发可能" in d.message and "CTRL+Q" in d.message for d in original)
    assert "duplicate-source" not in codes(result, "original_declaration")
    assert "duplicate-source" in codes(result, "static_compatibility")


def test_canonical_same_group_duplicate_and_disabled_group_handling(tmp_path):
    rows = (
        binding(source="CTRL+Q", target="CTRL+Q"),
        binding("ability_2", "control+q", "control+q", slot=1),
    )
    result = inspect_hotkey_config(write_config(tmp_path, config(*rows)))
    assert "duplicate-source" in codes(result, "original_declaration")
    disabled = inspect_hotkey_config(
        write_config(
            tmp_path, config(*rows, enabled_groups={"ability": False}), "disabled.json"
        )
    )
    assert "duplicate-source" not in codes(disabled)


def test_original_control_key_omission_reported_as_possible_overlap(tmp_path):
    result = inspect_hotkey_config(
        write_config(tmp_path, config(binding(source="F12", target="F12")))
    )
    assert any(
        d.code == "possible-control-overlap" and "CTRL+F12" in d.message
        for d in result.diagnostics
    )


def test_flat_parser_keeps_very_deep_extensions_and_large_integer_tokens(tmp_path):
    depth = 1600
    huge = "7" * 6000
    text = (
        '{"language":"auto","active_profile":"One","profiles":{"One":{"bindings":[]}},"extension":'
        + "[" * depth
        + huge
        + "]" * depth
        + "}"
    )
    path = tmp_path / "deep.json"
    path.write_text(text, encoding="utf-8")
    result = inspect_hotkey_config(path)
    assert result.inspection_complete
    assert any(n.kind == "number" and n.value == huge for n in result.nodes)
    assert len([n for n in result.nodes if n.kind == "array"]) == depth + 1
    assert len(json.dumps(hotkey_result_to_dict(result))) > len(text)


@pytest.mark.parametrize(
    "text", ['{"profiles":', '{"profiles":{},}', '{"profiles":{},"n":NaN}', "[]", "{}"]
)
def test_malformed_or_unknown_config_is_nonzero_with_full_raw(tmp_path, text):
    path = tmp_path / "bad.json"
    path.write_text(text, encoding="utf-8")
    result = inspect_hotkey_config(path)
    assert result.exit_code == 2
    assert result.source.utf8_text == text


def test_utf8_bom_recovery_does_not_claim_original_loader_acceptance(tmp_path):
    path = tmp_path / "bom.json"
    data = b"\xef\xbb\xbf" + json.dumps(config(binding())).encode()
    path.write_bytes(data)
    result = inspect_hotkey_config(path)
    assert "json-bom" in codes(result)
    assert result.exit_code == 1
    assert base64.b64decode(result.source.raw_base64) == data
    assert raw_hotkey_node(result, result.profiles[0].node).startswith('{"bindings"')


def test_invalid_utf8_keeps_exact_bytes(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_bytes(b"\xff\x00RAW")
    result = inspect_hotkey_config(path)
    assert result.exit_code == 2
    assert result.source.utf8_text is None
    assert base64.b64decode(result.source.raw_base64) == b"\xff\x00RAW"


def test_selection_retains_other_profile_diagnostics_and_unknown_name_is_error(
    tmp_path,
):
    payload = config(binding())
    payload["profiles"]["Bad"] = {"smartcast_delay_ms": -1, "bindings": []}
    path = write_config(tmp_path, payload)
    selected = inspect_hotkey_config(path, profile="One")
    assert len(selected.profiles) == 1 and selected.profiles_total == 2
    assert "delay-range" in codes(selected)
    assert inspect_hotkey_config(path, profile="missing").exit_code == 2


def test_delays_booleans_and_sparse_required_fields_are_not_coerced(tmp_path):
    bad = binding()
    del bad["target"]
    result = inspect_hotkey_config(
        write_config(
            tmp_path,
            config(bad, enabled="false", smartcast_delay_ms=True, repeat_delay_ms="90"),
        )
    )
    assert {"field-type", "delay-range", "binding-required"} <= codes(result)
    assert not result.profiles[0].compatibility_complete
    assert result.exit_code == 2


def test_source_change_during_analysis_is_detected(tmp_path, monkeypatch):
    path = write_config(tmp_path, config(binding()))
    original = hotkey_config._read_profile

    def mutate(*args):
        value = original(*args)
        path.write_bytes(path.read_bytes() + b" ")
        return value

    monkeypatch.setattr(hotkey_config, "_read_profile", mutate)
    result = inspect_hotkey_config(path)
    assert result.exit_code == 2
    assert "source-changed-before-delivery" in codes(result)
    assert not result.source.stable


def test_diff_uses_unique_original_ids_preserves_all_fields_and_ignores_row_order(
    tmp_path,
):
    first = binding()
    second = binding("item_1", "1", "1", "item", ext={"deep": ["a\tb", "\ufeff"]})
    old_path = write_config(tmp_path, config(first, second), "old.json")
    reordered = write_config(tmp_path, config(second, first), "reordered.json")
    same = diff_hotkey_configs(old_path, reordered)
    assert (
        same.comparison_complete and not same.has_changes and same.exit_code == 1
    )  # Unknown ext is retained as a finding.
    changed = {**second, "ext": {"deep": ["a\tb", "changed"]}}
    new_path = write_config(tmp_path, config(changed, first), "new.json")
    result = diff_hotkey_configs(old_path, new_path)
    assert result.comparison_complete and result.has_changes
    assert len(result.differences) == 1
    assert result.differences[0].path.endswith('["item_1"]["ext"]')
    assert result.differences[0].after is not None
    assert "changed" in result.differences[0].after


def test_diff_duplicate_id_does_not_choose_original_tool_last_winner(tmp_path):
    old_path = write_config(
        tmp_path, config(binding(), binding(source="F24", target="F24")), "old.json"
    )
    new_path = write_config(
        tmp_path, config(binding(source="F24", target="F24")), "new.json"
    )
    result = diff_hotkey_configs(old_path, new_path)
    assert not result.comparison_complete and result.exit_code == 2
    assert any(
        d.code == "diff-ambiguous-binding" and len(d.related) == 3
        for d in result.diagnostics
    )
    assert not result.has_changes


def test_diff_incomplete_old_cannot_claim_new_profiles_are_additions(tmp_path):
    old_path = tmp_path / "old.json"
    old_path.write_text('{"profiles":', encoding="utf-8")
    new_path = write_config(tmp_path, config(binding()), "new.json")
    result = diff_hotkey_configs(old_path, new_path)
    assert not result.comparison_complete and result.exit_code == 2
    assert not result.has_changes
    assert any(d.code == "diff-incomplete-absence" for d in result.diagnostics)


def test_diff_distinguishes_number_spellings_in_extensions(tmp_path):
    first = json.dumps(config(binding()))[:-1] + ',"extension":1.00}'
    second = first.replace('"extension":1.00', '"extension":1e0')
    old_path, new_path = tmp_path / "old.json", tmp_path / "new.json"
    old_path.write_text(first, encoding="utf-8")
    new_path.write_text(second, encoding="utf-8")
    result = diff_hotkey_configs(old_path, new_path)
    assert result.has_changes and result.differences[0].before == "1.00"
    assert result.differences[0].after == "1e0"


def test_diff_distinguishes_missing_and_explicit_empty_binding_container(tmp_path):
    old = write_config(tmp_path, config(), "old.json")
    payload = config()
    del payload["profiles"]["One"]["bindings"]
    new = write_config(tmp_path, payload, "new.json")
    result = diff_hotkey_configs(old, new)
    assert result.comparison_complete and result.has_changes
    assert result.differences[0].path.endswith('["bindings_declaration"]')
    assert result.differences[0].before == "[]"
    assert result.differences[0].after is None


def test_missing_file_and_directory_never_look_like_valid_empty_defaults(tmp_path):
    assert inspect_hotkey_config(tmp_path / "missing.json").exit_code == 2
    assert inspect_hotkey_config(tmp_path).exit_code == 2


def test_flat_json_parser_rejects_trailing_comma_and_partial_number():
    for text in ("[1,]", '{"x":}', "01", "1e", "true false", '{"x" 1}'):
        with pytest.raises(ValueError):
            parse_hotkey_json(text)


def test_zero_and_negative_zero_share_slot_identity_without_rewriting_tokens(tmp_path):
    text = json.dumps(config(binding(), binding("ability_2", "S", "S", slot=0)))
    start, end = text.rsplit('"slot_index": 0', 1)
    path = tmp_path / "zero-spellings.json"
    path.write_text(start + '"slot_index": -0' + end, encoding="utf-8")
    result = inspect_hotkey_config(path)
    rows = [
        row for row in result.profiles[0].compatibility_bindings if row.origin_ordinal
    ]
    assert [row.slot_index for row in rows] == [0, 0]
    assert [row.slot_index_literal for row in rows] == ["0", "-0"]
    duplicate = next(d for d in result.diagnostics if d.code == "duplicate-slot")
    assert len(duplicate.related) == 2
    assert result.source.utf8_text is not None
    assert '"slot_index": -0' in result.source.utf8_text


def test_original_duplicate_targets_are_information_separate_from_projection(tmp_path):
    result = inspect_hotkey_config(
        write_config(
            tmp_path,
            config(
                binding(source="F23", target="Q"),
                binding("ability_2", "F24", "q", slot=1),
            ),
        )
    )
    diagnostic = next(d for d in result.diagnostics if d.code == "duplicate-target")
    assert diagnostic.basis == "original_declaration"
    assert diagnostic.severity == "info" and len(diagnostic.related) == 2
    rows = [
        row for row in result.profiles[0].compatibility_bindings if row.origin_ordinal
    ]
    assert [row.target for row in rows] == ["F23", "F24"]
    assert [row.target for row in result.profiles[0].bindings] == ["Q", "q"]


@pytest.mark.parametrize("flag", ["false", 0, None, []])
def test_invalid_group_flags_keep_conditional_source_conflicts_and_incomplete_projection(
    tmp_path, flag
):
    result = inspect_hotkey_config(
        write_config(
            tmp_path,
            config(
                binding(source="Q", target=""),
                binding("ability_2", "Q", "", slot=1),
                enabled_groups={"ability": flag},
            ),
        )
    )
    assert not result.profiles[0].compatibility_complete
    assert len(result.profiles[0].compatibility_bindings) == 42
    assert "field-type" in codes(result)
    for basis in ("original_declaration", "static_compatibility"):
        rows = [
            d
            for d in result.diagnostics
            if d.code == "possible-duplicate-source" and d.basis == basis
        ]
        assert rows and all("启用状态不明" in d.message for d in rows)


@pytest.mark.parametrize("slot", range(6, 12))
def test_item_projection_uses_its_own_six_slot_range(tmp_path, slot):
    result = inspect_hotkey_config(
        write_config(tmp_path, config(binding("item_1", "1", "1", "item", slot)))
    )
    row = next(
        row
        for row in result.profiles[0].compatibility_bindings
        if row.binding_id == "item_1"
    )
    assert row.state == "invalid_declared_slot" and row.slot_index is None
    assert row.slot_index_literal == str(slot)
    assert not result.profiles[0].compatibility_complete
    assert "slot-range" in codes(result)


def test_long_ordinary_and_extended_sources_keep_display_paths_and_full_evidence(
    tmp_path,
):
    directory = tmp_path.joinpath(*("part" + str(i) + "x" * 55 for i in range(5)))
    Path(native_output_path(str(directory))).mkdir(parents=True)
    path = directory / "source.json"
    encoded = json.dumps(config(binding())).encode("utf-8")
    Path(native_output_path(str(path))).write_bytes(encoded)
    ordinary = inspect_hotkey_config(path)
    extended = inspect_hotkey_config(native_output_path(str(path)))
    assert len(str(path)) > 260
    assert ordinary.exit_code == extended.exit_code == 0
    assert ordinary.source.path == str(path)
    assert (
        ordinary.source.sha256
        == extended.source.sha256
        == hashlib.sha256(encoded).hexdigest()
    )
    assert ordinary.source.identity == extended.source.identity
    assert base64.b64decode(ordinary.source.raw_base64) == encoded


@pytest.mark.parametrize(
    ("settings", "existing"),
    [
        ({"vendor_extension": {"note": "preserve"}}, []),
        ({"enabled_groups": {"ability": "false"}}, []),
        ({"repeat_delay_ms": "invalid-delay"}, []),
        ({"enabled": False}, []),
        ({}, [binding("item_1", "1", "1", "item", 6)]),
    ],
)
@pytest.mark.parametrize("reverse", [False, True])
def test_raw_binding_additions_and_removals_ignore_unrelated_compatibility_validity(
    tmp_path, settings, existing, reverse
):
    empty = write_config(tmp_path, config(*existing, **settings), "empty.json")
    added = write_config(
        tmp_path, config(*existing, binding(), **settings), "added.json"
    )
    old, new = (added, empty) if reverse else (empty, added)
    result = diff_hotkey_configs(old, new)
    assert result.old.inspection_complete and result.new.inspection_complete
    assert result.old.profiles[0].bindings_coverage_complete
    assert result.new.profiles[0].bindings_coverage_complete
    assert result.has_changes and result.comparison_complete
    selected = [d for d in result.differences if d.path.endswith('["ability_1"]')]
    assert len(selected) == 1
    assert selected[0].kind == ("removed" if reverse else "added")
    assert "diff-incomplete-binding-absence" not in codes(result)
    if "vendor_extension" in settings:
        assert not result.old.profiles[0].compatibility_complete
        assert not result.new.profiles[0].compatibility_complete
        assert result.old.source.utf8_text is not None
        assert "preserve" in result.old.source.utf8_text


@pytest.mark.parametrize("raw_bindings", ['"opaque"', "[42]", '[{"source":"M"}]'])
def test_raw_binding_absence_stays_unknown_with_uncovered_container_or_id(
    tmp_path, raw_bindings
):
    old = tmp_path / "old.json"
    old.write_text(
        '{"language":"auto","active_profile":"One","profiles":{"One":{"bindings":'
        + raw_bindings
        + "}}}",
        encoding="utf-8",
    )
    new = write_config(tmp_path, config(binding()), "new.json")
    result = diff_hotkey_configs(old, new)
    assert not result.old.profiles[0].bindings_coverage_complete
    assert not result.comparison_complete
    assert not any(
        d.kind == "added" and "bindings_by_id" in d.path for d in result.differences
    )
    assert any(d.code == "diff-incomplete-binding-absence" for d in result.diagnostics)


def test_duplicate_identity_keeps_ambiguity_but_does_not_hide_another_confirmed_addition(
    tmp_path,
):
    repeated = (binding(), binding(source="F24", target="F24"))
    old = write_config(tmp_path, config(*repeated), "old.json")
    new = write_config(
        tmp_path, config(*repeated, binding("item_1", "1", "1", "item")), "new.json"
    )
    result = diff_hotkey_configs(old, new)
    assert result.old.profiles[0].bindings_coverage_complete
    assert result.has_changes and not result.comparison_complete
    assert any(d.code == "diff-ambiguous-binding" for d in result.diagnostics)
    assert any(
        d.kind == "added" and d.path.endswith('["item_1"]') for d in result.differences
    )


@pytest.mark.parametrize(
    "profile_json",
    [
        '{"bindings":[],"bindings":[]}',
        '{"bindings":[{"binding_id":"ability_1","binding_id":"ability_2","source":"M","target":"M","group":"ability","slot_index":0}]}',
    ],
)
def test_duplicate_container_or_id_roles_block_raw_absence_without_a_winner(
    tmp_path, profile_json
):
    old = tmp_path / "old.json"
    old.write_text(
        '{"language":"auto","active_profile":"One","profiles":{"One":'
        + profile_json
        + "}}",
        encoding="utf-8",
    )
    new = write_config(tmp_path, config(binding()), "new.json")
    result = diff_hotkey_configs(old, new)
    assert not result.old.profiles[0].bindings_coverage_complete
    assert not result.comparison_complete
    assert any(d.code == "duplicate-json-key" for d in result.old.diagnostics)
    assert not any(
        d.kind == "added" and "bindings_by_id" in d.path for d in result.differences
    )


def test_duplicate_profile_identity_blocks_binding_comparison_without_a_winner(
    tmp_path,
):
    old = tmp_path / "old.json"
    old.write_text(
        '{"language":"auto","active_profile":"One","profiles":{"One":{"bindings":[]},"One":{"bindings":[]}}}',
        encoding="utf-8",
    )
    new = write_config(tmp_path, config(binding()), "new.json")
    result = diff_hotkey_configs(old, new)
    assert len(result.old.profiles) == 2
    assert any(d.code == "diff-ambiguous-profile" for d in result.diagnostics)
    assert not result.comparison_complete and not result.has_changes


def test_unrelated_missing_target_does_not_hide_known_raw_binding_addition(tmp_path):
    incomplete = binding("item_1", "1", "1", "item")
    del incomplete["target"]
    old = write_config(tmp_path, config(incomplete), "old.json")
    new = write_config(tmp_path, config(incomplete, binding()), "new.json")
    result = diff_hotkey_configs(old, new)
    assert not result.old.inspection_complete
    assert result.old.profiles[0].bindings_coverage_complete
    assert result.has_changes and not result.comparison_complete
    assert any(
        d.kind == "added" and d.path.endswith('["ability_1"]')
        for d in result.differences
    )
    assert any(d.code == "binding-required" for d in result.old.diagnostics)
