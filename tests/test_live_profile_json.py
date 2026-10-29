"""Live and offline profile imports share one lossless declaration boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from gametool.live_handle_chain import profile_to_dict
from gametool.live_inventory import load_profile_override
from gametool.live_profile_json import parse_live_profile_json
from gametool.reference_catalog import _external_profile
from gametool.reference_sources import PackReferenceSources


_DUPLICATES = (
    ('{"game_version":"1.2.3.4","game_version":"2.3.4.5"}', "game_version"),
    (
        '{"game_version":"1.2.3.4","fingerprint":'
        '{"machine":34404,"machine":332,"timestamp":0,"image_size":4096}}',
        "machine",
    ),
    (
        '{"game_version":"1.2.3.4","checks":[{"rva":16,"rva":32,"bytes":"00"}]}',
        "rva",
    ),
    (
        '{"game_version":"1.2.3.4","field_layouts":'
        '[{"scope":"unit","key":"hp","type":"f32","offset":16,"offset":32,'
        '"source":"synthetic","evidence":"declared-layout-only"}]}',
        "offset",
    ),
    (
        '{"game_version":"1.2.3.4","handle_chain":'
        '{"vmctx_global_rva":16,"vmctx_global_rva":32}}',
        "vmctx_global_rva",
    ),
    ('{"game_version":"1.2.3.4","source":"same","source":"same"}', "source"),
    (
        '{"game_version":"1.2.3.4","source":"one","so\\u0075rce":"two"}',
        "source",
    ),
)


@pytest.mark.parametrize(("payload", "key"), _DUPLICATES)
def test_duplicate_declarations_are_rejected_by_both_imports(
    tmp_path: Path, payload: str, key: str
) -> None:
    path = tmp_path / "profile.json"
    original = payload.encode("utf-8")
    path.write_bytes(original)
    with pytest.raises(ValueError, match="重复键") as parsed:
        parse_live_profile_json(original)
    assert repr(key) in str(parsed.value)

    loaded, note = load_profile_override(str(path))
    assert loaded is None
    assert str(parsed.value) in note
    assert "回退内置" in note
    with pytest.raises(ValueError, match="重复键") as offline:
        _external_profile(path, PackReferenceSources())
    assert str(offline.value) == str(parsed.value)
    assert path.read_bytes() == original


def _valid_profile() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "game_version": "9.8.7.6",
        "engine": "reforged",
        "arch": "x64",
        "pointer_size": 8,
        "tier": "reforged-pending",
        "source": "synthetic \ufeff source",
        "fingerprint": {"machine": 0x8664, "timestamp": 0, "image_size": 4096},
        "checks": [
            {"rva": 16, "bytes": "00 FF", "domain": "resolver"},
            {"rva": 32, "bytes": "AA 55", "domain": "context"},
        ],
        "field_layouts": [
            {
                "scope": "unit",
                "key": "hp",
                "type": "f32",
                "offset": 256,
                "source": "synthetic fixture",
                "evidence": "declared-layout-only",
            },
            {
                "scope": "item",
                "key": "charges",
                "type": "u32",
                "pointer_offsets": [16, 32],
                "source": "synthetic fixture",
                "evidence": "declared-layout-only",
            },
        ],
    }


@pytest.mark.parametrize("bom", (False, True))
def test_valid_profiles_preserve_full_evidence_in_both_imports(
    tmp_path: Path, bom: bool
) -> None:
    data = _valid_profile()
    text = ("\ufeff" if bom else "") + json.dumps(data, ensure_ascii=False)
    payload = text.encode("utf-8")
    path = tmp_path / "profile.json"
    path.write_bytes(payload)
    parsed = parse_live_profile_json(payload)
    assert parsed == parse_live_profile_json(text)
    assert parsed["source"] == data["source"]
    assert len(parsed["checks"]) == 2
    assert len(parsed["field_layouts"]) == 2

    loaded, note = load_profile_override(str(path))
    assert loaded is not None and "已加载" in note
    normalized = profile_to_dict(loaded)
    assert normalized["source"] == parsed["source"]
    assert normalized["fingerprint"] == parsed["fingerprint"]
    assert normalized["checks"] == parsed["checks"]
    assert normalized["field_layouts"] == parsed["field_layouts"]
    adapter = PackReferenceSources()
    offline = _external_profile(path, adapter)
    assert offline.id == loaded.version
    assert offline.coverage is not None
    assert offline.coverage["runtime_verified"] is False
    assert offline.coverage["fields"] == parsed["field_layouts"]
    assert dict(offline.details)["原始 JSON"] == text.removeprefix("\ufeff")
    assert adapter.sources[str(path)].sha256 == hashlib.sha256(payload).hexdigest()
    assert path.read_bytes() == payload


@pytest.mark.parametrize(
    ("payload", "message"),
    (
        ('{"schema_version":2,"game_version":"1.2.3.4"}', "schema v2"),
        ('{"game_version":"1.2.3.4","unknown":1}', "未知键"),
        ('{"game_version":"1.2.3"}', "四段"),
        ('{"game_version":"1.2.3.4","checks":{}}', "checks"),
        ('{"game_version":"1.2.3.4","game_struct_rva":true}', "整数"),
        ("[]", "需要对象"),
        ("{", "property name"),
    ),
)
def test_schema_and_json_errors_remain_consistent(
    tmp_path: Path, payload: str, message: str
) -> None:
    path = tmp_path / "invalid.json"
    path.write_text(payload, encoding="utf-8")
    loaded, note = load_profile_override(str(path))
    assert loaded is None
    assert "回退内置" in note and message in note
    with pytest.raises(ValueError, match=message) as offline:
        _external_profile(path, PackReferenceSources())
    assert str(offline.value) in note


@pytest.mark.parametrize("encoding", ("utf-16", "utf-32"))
def test_non_utf8_profiles_are_not_reinterpreted(tmp_path: Path, encoding: str) -> None:
    path = tmp_path / "profile.json"
    path.write_bytes(json.dumps(_valid_profile()).encode(encoding))
    loaded, note = load_profile_override(str(path))
    assert loaded is None and "UnicodeDecodeError" in note
    with pytest.raises(UnicodeDecodeError):
        _external_profile(path, PackReferenceSources())


def test_complete_large_declarations_have_no_imported_trainer_quota(
    tmp_path: Path,
) -> None:
    data = _valid_profile()
    data["source"] = "x" * (2 * 1024 * 1024 + 1)
    data["field_layouts"] = data["field_layouts"] * 751
    payload = json.dumps(data).encode("utf-8")
    path = tmp_path / "large.json"
    path.write_bytes(payload)
    loaded, _note = load_profile_override(str(path))
    assert loaded is not None
    assert loaded.source == data["source"]
    assert len(loaded.field_layouts) == 1502
    offline = _external_profile(path, PackReferenceSources())
    assert offline.coverage is not None
    assert len(offline.coverage["fields"]) == 1502
    assert dict(offline.details)["原始 JSON"] == payload.decode("utf-8")
