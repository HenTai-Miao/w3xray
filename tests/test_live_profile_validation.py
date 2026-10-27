"""All profile integer domains, data-only boundaries, and offline coverage."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from gametool.live_profile_validation import (
    HANDLE_INTEGER_KEYS,
    inspect_profile_support,
    parse_field_layouts,
    validate_profile_data,
)


def profile() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "game_version": "1.27.0.52240",
        "engine": "classic",
        "arch": "x86",
        "source": "independently measured fixture",
        "handle_chain": {
            **dict.fromkeys(HANDLE_INTEGER_KEYS, 4),
            "source": "fixture snapshot",
        },
    }


def field(**changes: object) -> dict[str, object]:
    return {
        "scope": "unit",
        "key": "test_health",
        "type": "f32",
        "offset": -4,
        "source": "independent fixture",
        "evidence": "declared-layout-only",
        **changes,
    }


@pytest.mark.parametrize("key", HANDLE_INTEGER_KEYS)
@pytest.mark.parametrize("value", [True, False, 4.5, "4", None, [], {}])
def test_every_handle_integer_rejects_coercion(key: str, value: object) -> None:
    data = profile()
    data["handle_chain"][key] = value
    with pytest.raises(ValueError, match=f"handle_chain.{key}"):
        validate_profile_data(data)


@pytest.mark.parametrize("key", ["schema_version", "game_struct_rva", "unit_list_rva"])
@pytest.mark.parametrize("value", [True, False, 1.0, "1", [], {}])
def test_top_integer_members_are_strict(key: str, value: object) -> None:
    data = profile()
    data[key] = value
    with pytest.raises(ValueError, match=key):
        validate_profile_data(data)


@pytest.mark.parametrize("key", ["game_struct_rva", "unit_list_rva"])
@pytest.mark.parametrize("value", [-1, 1 << 32])
def test_pe_rvas_reject_outside_encoded_domain(key: str, value: int) -> None:
    data = profile()
    data[key] = value
    with pytest.raises(ValueError, match=key):
        validate_profile_data(data)


def test_signed_structure_offsets_are_not_mistaken_for_unsigned_rvas() -> None:
    data = profile()
    for key in HANDLE_INTEGER_KEYS:
        if key.endswith("_off"):
            data["handle_chain"][key] = -((1 << 32) - 1)
    valid = validate_profile_data(data)
    assert valid["handle_chain"]["unit_type_off"] == -((1 << 32) - 1)
    data["handle_chain"]["vmctx_global_rva"] = -1
    with pytest.raises(ValueError, match="vmctx_global_rva"):
        validate_profile_data(data)


@pytest.mark.parametrize("stride", [0, -1, 1 << 32])
def test_inventory_stride_uses_positive_architecture_span(stride: int) -> None:
    data = profile()
    data["handle_chain"]["inv_slot_stride"] = stride
    with pytest.raises(ValueError, match="inv_slot_stride"):
        validate_profile_data(data)


def test_offset_address_domains_follow_architecture() -> None:
    data = profile()
    data["handle_chain"]["unit_type_off"] = 1 << 40
    with pytest.raises(ValueError, match="unit_type_off"):
        validate_profile_data(data)
    data["arch"] = "x64"
    data["pointer_size"] = 8
    assert validate_profile_data(data)["handle_chain"]["unit_type_off"] == 1 << 40


@pytest.mark.parametrize("width", [True, False, 4.0, "4", 0, 5, 8])
def test_pointer_width_is_strict_and_matches_architecture(width: object) -> None:
    data = profile()
    data["pointer_size"] = width
    with pytest.raises(ValueError, match="pointer_size"):
        validate_profile_data(data)


@pytest.mark.parametrize("version", [None, 1, True, "1.27", "١.٢.٣.٤", "1.2.3.-4"])
def test_versions_need_four_ascii_word_segments(version: object) -> None:
    data = profile()
    data["game_version"] = version
    with pytest.raises(ValueError, match="game_version"):
        validate_profile_data(data)


def test_versions_enforce_actual_word_bounds_without_string_quotas() -> None:
    data = profile()
    data["game_version"] = "65535.0.65535.0"
    assert validate_profile_data(data)["game_version"] == data["game_version"]
    data["game_version"] = ".".join(["0" * 6000 + "1"] * 4)
    assert validate_profile_data(data)["game_version"] == data["game_version"]
    data["game_version"] = "1.2.3.65536"
    with pytest.raises(ValueError, match="WORD"):
        validate_profile_data(data)


@pytest.mark.parametrize("key", ["machine", "timestamp", "image_size"])
@pytest.mark.parametrize("value", [True, 5.0, "5", [], None, -1, 1 << 32])
def test_fingerprint_numeric_members_are_strict(key: str, value: object) -> None:
    data = profile()
    fingerprint: dict[str, object] = {
        "machine": 0x14C,
        "timestamp": 0,
        "image_size": 0x1000,
    }
    fingerprint[key] = value
    data["fingerprint"] = fingerprint
    with pytest.raises(ValueError, match=f"fingerprint.{key}"):
        validate_profile_data(data)


@pytest.mark.parametrize(
    ("arch", "machine"), [("x86", 0x8664), ("x64", 0x14C), ("x86", 1 << 16)]
)
def test_pe_machine_qualification_matches_architecture(arch: str, machine: int) -> None:
    data = profile()
    data["arch"] = arch
    data["fingerprint"] = {"machine": machine, "timestamp": 0, "image_size": 0x1000}
    with pytest.raises(ValueError, match="machine"):
        validate_profile_data(data)


@pytest.mark.parametrize("value", [True, False, "4", 4.0, -1, 1 << 32])
def test_check_rva_is_strict(value: object) -> None:
    data = profile()
    data["checks"] = [{"rva": value, "bytes": "00"}]
    with pytest.raises(ValueError, match=r"checks\[0\].rva"):
        validate_profile_data(data)


@pytest.mark.parametrize("value", [None, 90, True, [], "", "0", "zz"])
def test_check_bytes_need_actual_nonempty_hex(value: object) -> None:
    data = profile()
    data["checks"] = [{"rva": 0, "bytes": value}]
    with pytest.raises(ValueError, match=r"checks\[0\].bytes"):
        validate_profile_data(data)


def test_checks_and_pointer_anchors_respect_encoded_image_boundaries() -> None:
    data = profile()
    data["checks"] = [{"rva": (1 << 32) - 1, "bytes": "0000"}]
    with pytest.raises(ValueError, match="RVA"):
        validate_profile_data(data)
    data["fingerprint"] = {"machine": 0x14C, "timestamp": 0, "image_size": 0x100}
    data["checks"] = [{"rva": 0xFF, "bytes": "00"}]
    assert validate_profile_data(data)["checks"][0]["bytes"] == "00"
    data["checks"][0]["bytes"] = "0000"
    with pytest.raises(ValueError, match="image_size"):
        validate_profile_data(data)
    data["checks"] = []
    data["handle_chain"]["vmctx_global_rva"] = 0xFE
    with pytest.raises(ValueError, match="vmctx_global_rva"):
        validate_profile_data(data)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("checks", {}),
        ("checks", [None]),
        ("checks", [{}]),
        ("checks", [{"rva": 1, "bytes": "90", "provider": "code.py"}]),
        ("fingerprint", []),
        ("fingerprint", {}),
        ("handle_chain", []),
        ("handle_chain", {}),
        ("source", 3),
        ("id", False),
        ("status", ""),
        ("arch", "arm64"),
        ("tier", "guessed"),
        ("engine", []),
        ("field_layouts", {}),
    ],
)
def test_explicit_malformed_members_never_become_absence(
    key: str, value: object
) -> None:
    data = profile()
    data[key] = value
    with pytest.raises(ValueError, match=key):
        validate_profile_data(data)


@pytest.mark.parametrize(
    "key", ["provider", "python", "dll", "code", "address", "extra"]
)
def test_unknown_top_level_keys_reject_code_or_silent_extensions(key: str) -> None:
    data = profile()
    data[key] = "anything"
    with pytest.raises(ValueError, match="未知键"):
        validate_profile_data(data)


def test_complete_legacy_builtins_roundtrip_through_public_profile_api() -> None:
    from gametool.live_handle_chain import (
        build_profiles,
        profile_from_dict,
        profile_to_dict,
        resolve_profile,
    )

    profiles = [*build_profiles().values(), resolve_profile("1.99.0.1")]
    profiles.append(resolve_profile("3.0.0.24268", "reforged", "x64"))
    for original in profiles:
        encoded = profile_to_dict(original)
        validated = validate_profile_data(encoded)
        assert profile_to_dict(profile_from_dict(validated)) == encoded


def test_validated_data_is_independent_and_preserves_id_status() -> None:
    data = profile()
    data["id"] = "independent-build-r2"
    data["status"] = "candidate"
    data["checks"] = [{"rva": 0, "bytes": "00 FF", "domain": "context"}]
    data["field_layouts"] = [field()]
    before = deepcopy(data)
    validated = validate_profile_data(data)
    assert data == before
    assert validated["id"] == "independent-build-r2"
    assert validated["status"] == "candidate"
    assert validated["checks"][0]["bytes"] == "00ff"
    validated["field_layouts"][0]["key"] = "changed"
    assert data["field_layouts"][0]["key"] == "test_health"


@pytest.mark.parametrize(
    "changes",
    [
        {"scope": "unsupported"},
        {"key": ""},
        {"type": "python"},
        {"source": ""},
        {"evidence": "guessed"},
        {"offset": True},
        {"offset": 1.5},
        {"offset": "4"},
        {"offset": 1 << 32},
        {"label": 4},
        {"provider": "plugin.py"},
        {"pointer_offsets": [4, 8]},
    ],
)
def test_layout_schema_is_pure_and_explicit(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="field_layouts"):
        parse_field_layouts([field(**changes)])


@pytest.mark.parametrize("chain", [[], None, "4", [True], [4.0], ["4"], [1 << 32]])
def test_all_pointer_chain_offsets_are_strict(chain: object) -> None:
    recipe = field()
    del recipe["offset"]
    recipe["pointer_offsets"] = chain
    with pytest.raises(ValueError, match="pointer_offsets"):
        parse_field_layouts([recipe])


def test_layouts_have_no_field_chain_or_string_length_quotas() -> None:
    recipe = field(key="label" * 1500, source="source" * 1500)
    del recipe["offset"]
    recipe["pointer_offsets"] = [-4] * 1500
    layouts = parse_field_layouts([recipe] * 1500)
    assert len(layouts) == 1500
    assert len(layouts[-1].pointer_offsets) == 1500
    assert layouts[-1].to_dict() == recipe


def test_offline_support_keeps_declared_fields_and_unverified_build_truth() -> None:
    data = profile()
    data["tier"] = "template"
    data["field_layouts"] = [field()]
    support = inspect_profile_support(data)
    encoded = support.to_dict()
    assert support.complete and support.supported
    assert encoded["runtime_verified"] is False
    assert len(encoded["fields"]) == 4
    assert {entry["key"] for entry in encoded["fields"]} == {
        "test_health",
        "code",
        "inventory",
    }
    assert any("template" in entry for entry in encoded["diagnostics"])
    data["handle_chain"]["unit_type_off"] = True
    invalid = inspect_profile_support(data)
    assert not invalid.complete and not invalid.supported
    assert "unit_type_off" in invalid.diagnostics[0]


def test_reforged_without_verified_layouts_remains_explicitly_unsupported() -> None:
    support = inspect_profile_support(
        {
            "game_version": "3.0.0.24268",
            "engine": "reforged",
            "arch": "x64",
            "tier": "reforged-pending",
        }
    )
    assert support.complete
    assert not support.supported
    assert support.fields == ()
    assert support.pointer_size == 8
    assert any("HP/MP" in note for note in support.diagnostics)
