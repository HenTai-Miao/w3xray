"""Synthetic contracts for lossless War3Tools configuration inspection."""

from __future__ import annotations

import base64
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from gametool import war3tools_config
from gametool.war3tools_config import (
    format_war3tools_inspection,
    inspect_war3tools_config,
    revalidate_war3tools_inspection,
    war3tools_result_to_dict,
)


def write_ini(
    root: Path, text: str, name: str = "Features.ini", encoding: str = "utf-8"
) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode(encoding))
    return path


def diagnostic_codes(result):
    return {note.code for note in result.diagnostics}


def test_complete_raw_bytes_lines_offsets_and_declared_switch_without_side_effects(
    tmp_path,
):
    text = ";comment\r\n[Features]\r\nExtendedChatInput=1\nUnicodeClipboardPaste=0\r\n\r\nUnknown= a=b;literal \t"
    path = write_ini(tmp_path, text)
    before = path.read_bytes(), path.stat().st_mtime_ns
    result = inspect_war3tools_config(path)
    assert result.inspection_complete and result.stable and result.exit_code == 0
    assert not result.runtime_verified
    file = result.files[0]
    assert base64.b64decode(file.source.raw_base64) == before[0]
    assert file.source.sha256 == hashlib.sha256(before[0]).hexdigest()
    assert file.source.raw_text == text
    assert "".join(record.raw for record in file.records) == text
    for record in file.records:
        assert (
            before[0][record.byte_offset : record.byte_end].decode("utf-8")
            == record.raw
        )
    assert [setting.interpreted for setting in file.settings] == [True, False, None]
    assert file.settings[-1].value == " a=b;literal \t"
    assert file.settings[-1].state == "unknown"
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert "未知" in result.render()
    assert json.loads(json.dumps(war3tools_result_to_dict(result)))["files_total"] == 1


def test_duplicate_sections_keys_case_aliases_and_broken_lines_do_not_select_winners(
    tmp_path,
):
    text = "[Features]\nExtendedChatInput=1\nextendedchatinput=0\n[features]\nMystery=tail\nnot-an-entry\n[broken\nExtendedChatInput=1\n=empty-key\n"
    path = write_ini(tmp_path, text)
    result = inspect_war3tools_config(path)
    assert result.exit_code == 2
    assert result.stable
    assert {
        "duplicate-section",
        "duplicate-key",
        "malformed-line",
        "entry-without-section",
    } <= diagnostic_codes(result)
    assert "".join(row.raw for row in result.files[0].records) == text
    assert all(row.state == "ambiguous" for row in result.files[0].settings[:3])
    last = result.files[0].settings[-1]
    assert last.section == "" and last.state == "unknown"
    assert last.interpreted is None
    assert result.files[0].records[-1].raw == "=empty-key\n"


@pytest.mark.parametrize(
    "encoding,bom",
    [
        ("utf-8", b"\xef\xbb\xbf"),
        ("utf-16-le", b"\xff\xfe"),
        ("utf-16-be", b"\xfe\xff"),
    ],
)
def test_bom_decode_roundtrip_and_non_ascii_line_byte_offsets(tmp_path, encoding, bom):
    text = "[Features]\r\nUnknown=完整中文\r\nExtendedChatInput=1\r\n"
    path = tmp_path / "Features.ini"
    payload = bom + text.encode(encoding)
    path.write_bytes(payload)
    result = inspect_war3tools_config(path)
    file = result.files[0]
    assert result.exit_code == 0
    assert file.source.bom_bytes == len(bom)
    assert file.source.encoding == encoding
    assert base64.b64decode(file.source.raw_base64) == payload
    for record in file.records:
        assert (
            payload[record.byte_offset : record.byte_end].decode(encoding) == record.raw
        )
    assert file.records[-1].byte_end == len(payload)


def test_non_utf8_auto_requires_explicit_encoding_and_never_replaces_bytes(tmp_path):
    text = "[Features]\nUnknown=完整中文\nExtendedChatInput=1\n"
    path = write_ini(tmp_path, text, encoding="gb18030")
    failed = inspect_war3tools_config(path)
    assert failed.exit_code == 2
    assert failed.files[0].source.raw_text is None
    assert base64.b64decode(failed.files[0].source.raw_base64) == path.read_bytes()
    assert "source-encoding" in diagnostic_codes(failed)
    explicit = inspect_war3tools_config(path, text_encoding="gb18030")
    assert explicit.exit_code == 0
    assert explicit.files[0].source.raw_text == text
    assert explicit.files[0].source.encoding == "gb18030"


def test_bom_conflict_and_bomless_utf16_retain_bytes_with_encoding_recovery(tmp_path):
    text = "[Features]\nExtendedChatInput=1\n"
    path = write_ini(tmp_path, text, encoding="utf-16-le")
    assert inspect_war3tools_config(path).exit_code == 2
    assert inspect_war3tools_config(path, text_encoding="utf-16-le").exit_code == 0
    path.write_bytes(b"\xff\xfe" + text.encode("utf-16-le"))
    conflict = inspect_war3tools_config(path, text_encoding="utf-8")
    assert conflict.exit_code == 2
    assert conflict.files[0].records == ()
    assert base64.b64decode(conflict.files[0].source.raw_base64) == path.read_bytes()


def test_all_known_domains_and_unknown_modes_keep_exact_numeric_spelling(tmp_path):
    samples = {
        "Camera.ini": "[Camera]\nDistanceEnabled=1\nDistance=1.234567890123456789\nTilt=+00304\n[CameraMapProfile20000]\nMapNameHex=E6B58BE8AF95\nDistance=-7.00\n",
        "Cooldown.ini": "[Cooldown]\nEnabled=0\nMaximumDisplayedSeconds=999999999999999999999999999999999999\nSendCooldownModifier=91\nFontColor=00FFFFFF\n",
        "Features.ini": "[Features]\nDamageFloatingEnabled=1\nDamageFloatingDurationMs=1200\nDamageFloatingNumberMode=17\n",
        "Settings.ini": "[Settings]\nLanguage=zh-CN\nMenuShortcutKey=191\nMenuShortcutEnabled=1\n",
        "UI.ini": "[UI]\nManaBarEnabled=1\nManaBarHeight=0.003000\nBlackBarDisplayLogic=72\n",
    }
    for name, text in samples.items():
        write_ini(tmp_path, text, name)
    result = inspect_war3tools_config(tmp_path)
    assert result.exit_code == 0
    settings = {
        setting.key: setting for file in result.files for setting in file.settings
    }
    assert settings["MapNameHex"].interpreted == "测试"
    assert settings["Tilt"].interpreted == "+00304"
    assert settings["SendCooldownModifier"].interpreted == "91"
    assert settings["BlackBarDisplayLogic"].interpreted == "72"
    assert settings["DamageFloatingNumberMode"].kind == "integer"
    assert settings["FontColor"].interpreted == "00FFFFFF"


def test_packed_data_names_and_signal_points_are_lossless_without_layout_guesses(
    tmp_path,
):
    packed = "00Ab" * 9000
    write_ini(
        tmp_path,
        f"[ConversionProfile999999]\nNameHex=E6B58BE8AF95\nDataHex={packed}\n",
        "KeyMapping.ini",
    )
    write_ini(
        tmp_path,
        "[MinimapSignals]\nMinimapSignalProfile90001NameHex=E6B58BE8AF95\nMinimapSignalProfile90001Points=011000FF\nMinimapSignalProfile90001Preset=2\n",
        "MinimapSignals.ini",
    )
    result = inspect_war3tools_config(tmp_path)
    assert result.exit_code == 0
    opaque = [
        setting
        for file in result.files
        for setting in file.settings
        if setting.state == "opaque"
    ]
    assert len(opaque) == 2
    assert opaque[0].value == packed
    assert opaque[0].interpreted == packed
    assert result.bindings == ()
    assert packed in format_war3tools_inspection(result)


@pytest.mark.parametrize(
    "declaration",
    [
        "ExtendedChatInput=2",
        "DamageFloatingFontSize=no",
        "AttackRangeCustomRange=NaN",
        "AttackRangeColor=FFFF",
        "CameraUnitLockShortcutKey=99999999999999999999",
    ],
)
def test_invalid_known_values_preserve_original_declaration_and_diagnostic(
    tmp_path, declaration
):
    path = write_ini(tmp_path, "[Features]\n" + declaration + "\n")
    result = inspect_war3tools_config(path)
    assert result.exit_code == 2
    assert "invalid-setting-value" in diagnostic_codes(result)
    assert result.files[0].settings[0].state == "invalid"
    assert declaration in result.render()


def test_empty_and_zero_keys_are_not_bindings_and_disabled_keys_do_not_conflict(
    tmp_path,
):
    write_ini(
        tmp_path,
        "[Conversion]\nConversionEnabled=0\nSkillKey01=81\nSkillKey02=81\nSkillKey03=0\nSkillKey04=\nKeyboardMapSource01=0\nKeyboardMapTarget01=0\n",
        "KeyMapping.ini",
    )
    result = inspect_war3tools_config(tmp_path)
    assert len(result.bindings) == 2
    assert all(binding.enabled is False for binding in result.bindings)
    assert result.conflicts == ()
    assert sum(setting.state == "unbound" for setting in result.files[0].settings) == 4


def test_cross_context_and_same_group_duplicate_keys_remain_potential_without_activation_proof(
    tmp_path,
):
    path = write_ini(
        tmp_path,
        "[Conversion]\nConversionEnabled=1\nConversionMode=1\nSkillKey01=81\nSkillSlot01=0\nSkillKey02=81\nSkillSlot02=0\nSpellbookSkillKey01=81\nSpellbookSkillSlot01=0\n",
        "KeyMapping.ini",
    )
    result = inspect_war3tools_config(path)
    assert result.exit_code == 1
    assert len(result.bindings) == 3
    assert all(not binding.activation_proven for binding in result.bindings)
    assert len(result.conflicts) == 1
    assert result.conflicts[0].state == "potential"
    assert result.conflicts[0].binding_indexes == (0, 1, 2)


def test_keyboard_pairs_keep_sparse_targets_and_do_not_match_different_number_spellings(
    tmp_path,
):
    path = write_ini(
        tmp_path,
        "[Conversion]\nConversionEnabled=1\nKeyboardMapSource00001=81\nKeyboardMapTarget1=87\nKeyboardMapSource999999=69\nKeyboardMapTarget999999=82\n",
        "KeyMapping.ini",
    )
    result = inspect_war3tools_config(path)
    assert len(result.bindings) == 2
    assert result.bindings[0].target is None
    assert result.bindings[0].state == "incomplete"
    assert result.bindings[1].target == "82"
    assert "binding-target-unresolved" in diagnostic_codes(result)
    assert result.files[0].settings[2].value == "87"


def test_repeated_key_values_remain_individual_binding_evidence_without_guessing(
    tmp_path,
):
    path = write_ini(
        tmp_path,
        "[Conversion]\nConversionEnabled=1\nSkillKey01=81\nSkillKey01=87\n",
        "KeyMapping.ini",
    )
    result = inspect_war3tools_config(path)
    assert result.exit_code == 2
    assert [binding.key_code for binding in result.bindings] == [81, 87]
    assert all(binding.state == "ambiguous" for binding in result.bindings)
    assert result.conflicts == ()


def test_unknown_keys_do_not_acquire_roles_from_suffixes_or_other_file_names(tmp_path):
    path = write_ini(
        tmp_path,
        "[Features]\nMadeUpEnabled=1\nMadeUpShortcutKey=81\nSkillKey01=81\n",
        "Unrelated.ini",
    )
    result = inspect_war3tools_config(path)
    assert result.exit_code == 0
    assert all(setting.state == "unknown" for setting in result.files[0].settings)
    assert result.bindings == ()


def test_known_vocabulary_never_leaks_into_another_declared_section_role(tmp_path):
    write_ini(
        tmp_path,
        "[Conversion]\nDataHex=0000\nNameHex=41\n"
        "[ConversionProfile01]\nConversionEnabled=1\nSkillKey01=81\n",
        "KeyMapping.ini",
    )
    write_ini(
        tmp_path,
        "[Camera]\nMapNameHex=41\n[CameraMapProfile01]\nCameraMapProfileCount=1\n",
        "Camera.ini",
    )
    write_ini(
        tmp_path,
        "[Catalog]\nEnabled=1\nNameUtf8=41\n"
        "[Group01]\nFormatVersion=1\n[Group01Profile01]\nCount=9\n",
        "GroundItemHighlight/Index.ini",
    )
    result = inspect_war3tools_config(tmp_path)
    assert result.inspection_complete
    assert result.settings_total == 10
    assert all(
        setting.state == "unknown" for file in result.files for setting in file.settings
    )
    assert result.bindings == ()


def test_recursive_inventory_keeps_all_files_and_empty_extensions_without_loading_payloads(
    tmp_path, monkeypatch
):
    for index in range(75):
        write_ini(
            tmp_path,
            f"[Features]\nExtendedChatInput={index % 2}\n",
            f"sub{index}/Features.INI",
        )
    executable = tmp_path / "helper.exe"
    executable.write_bytes(b"MZ\x00not executable input")
    (tmp_path / "Dumps").mkdir()
    original = war3tools_config._capture_source
    seen: list[str] = []

    def capture(path, relative, encoding):
        seen.append(path.suffix.lower())
        return original(path, relative, encoding)

    monkeypatch.setattr(war3tools_config, "_capture_source", capture)
    result = inspect_war3tools_config(tmp_path)
    assert result.exit_code == 0
    assert result.files_total == 75
    assert result.records_total == 150
    assert len(result.inventory) == 152
    assert all(entry.identity[0] and entry.identity[1] for entry in result.inventory)
    assert set(seen) == {".ini"}
    assert "empty-directory" in diagnostic_codes(result)
    assert any(entry.relative_path == "helper.exe" for entry in result.inventory)


def test_explicit_single_ini_does_not_discover_siblings(tmp_path):
    selected = write_ini(tmp_path, "[Features]\nExtendedChatInput=1\n")
    write_ini(tmp_path, "[Camera]\nDistance=1650\n", "Camera.ini")
    result = inspect_war3tools_config(selected)
    assert result.files_total == 1
    assert len(result.inventory) == 1
    assert result.files[0].source.relative_path == "Features.ini"


@pytest.mark.parametrize("mutation", ["edit", "delete", "replace"])
def test_final_source_replay_preserves_old_complete_evidence_on_every_change(
    tmp_path, mutation
):
    path = write_ini(tmp_path, "[Features]\nExtendedChatInput=1\n")
    result = inspect_war3tools_config(path)
    original = result.files[0]
    if mutation == "delete":
        path.unlink()
    elif mutation == "replace":
        other = tmp_path / "replacement.ini"
        other.write_bytes(path.read_bytes())
        other.replace(path)
    else:
        path.write_bytes(b"[Features]\nExtendedChatInput=0\n")
    replayed = revalidate_war3tools_inspection(result)
    assert replayed.exit_code == 2 and not replayed.stable
    assert not replayed.inspection_complete
    assert replayed.files[0].source.raw_base64 == original.source.raw_base64
    assert replayed.files[0].records == original.records
    assert replayed.files[0].settings == original.settings
    assert "source-changed-before-delivery" in diagnostic_codes(replayed)
    assert result.stable


@pytest.mark.parametrize("name", ["New.INI", "new.dll", "Dumps/new.dmp"])
def test_inventory_replay_detects_added_ini_and_non_ini_members(tmp_path, name):
    write_ini(tmp_path, "[Features]\nExtendedChatInput=1\n")
    result = inspect_war3tools_config(tmp_path)
    added = tmp_path / name
    added.parent.mkdir(parents=True, exist_ok=True)
    added.write_bytes(b"not loaded")
    replayed = revalidate_war3tools_inspection(result)
    assert replayed.exit_code == 2
    assert not replayed.inventory_complete
    assert "inventory-changed-before-delivery" in diagnostic_codes(replayed)
    assert replayed.inventory == result.inventory
    assert replayed.files == result.files


def test_inventory_replay_detects_removed_extension_and_keeps_original_inventory(
    tmp_path,
):
    write_ini(tmp_path, "[Features]\nExtendedChatInput=1\n")
    extension = tmp_path / "data.bin"
    extension.write_bytes(b"kept as inventory only")
    result = inspect_war3tools_config(tmp_path)
    extension.unlink()
    replayed = revalidate_war3tools_inspection(result)
    assert replayed.exit_code == 2
    assert any(entry.relative_path == "data.bin" for entry in replayed.inventory)


def test_mid_read_instability_retains_source_bytes_and_never_claims_complete(
    tmp_path, monkeypatch
):
    path = write_ini(tmp_path, "[Features]\nExtendedChatInput=1\n")
    original = war3tools_config._capture_source

    def capture(path, relative, encoding):
        source, notes = original(path, relative, encoding)
        return replace(source, stable=False), notes

    monkeypatch.setattr(war3tools_config, "_capture_source", capture)
    result = inspect_war3tools_config(path)
    assert result.exit_code == 2
    assert result.files[0].source.raw_text == path.read_text()
    assert len(result.files[0].settings) == 1


def test_missing_path_invalid_encoding_empty_directory_and_empty_file_are_distinct(
    tmp_path,
):
    missing = inspect_war3tools_config(tmp_path / "missing.ini")
    assert missing.input_error and missing.exit_code == 2
    assert inspect_war3tools_config(tmp_path, text_encoding="guess").input_error
    assert inspect_war3tools_config("").input_error
    empty_dir = inspect_war3tools_config(tmp_path)
    assert "no-ini-files" in diagnostic_codes(empty_dir)
    empty = write_ini(tmp_path, "")
    empty_file = inspect_war3tools_config(empty)
    assert empty_file.files_total == 1
    assert empty_file.files[0].source.sha256 == hashlib.sha256(b"").hexdigest()
    assert empty_file.records_total == 0
    assert empty_file.inspection_complete
