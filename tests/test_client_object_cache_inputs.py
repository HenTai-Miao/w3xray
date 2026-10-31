"""Client snapshot reuse follows every named source byte, including Skin layers."""

from __future__ import annotations

import json
import os
import pickle
import struct
from pathlib import Path

import pytest

from gametool import client_object_data as client
from gametool.game_data_source import DirectoryDataSource

_NAME_FIELDS = {
    "w3u": "unam",
    "w3t": "unam",
    "w3a": "anam",
    "w3q": "gnam",
    "w3b": "bnam",
    "w3d": "dnam",
    "w3h": "fnam",
}


def _binary(ext: str, value: str) -> bytes:
    mod = _NAME_FIELDS[ext].encode("ascii") + struct.pack("<i", 3)
    if ext in {"w3a", "w3q", "w3d"}:
        mod += struct.pack("<ii", 0, 0)
    mod += value.encode("utf-8") + b"\0S001"
    return (
        struct.pack("<iii", 3, 0, 1)
        + b"ratcS001"
        + struct.pack("<iiii", 2, 0, 1, 1)
        + mod
    )


def _write(root: Path, member: str, payload: bytes) -> Path:
    path = root.joinpath(*member.replace("\\", "/").split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _snapshot(root: Path) -> client.ClientObjectSnapshot:
    source = DirectoryDataSource(str(root))
    try:
        return client.snapshot_client_base_objects(source)
    finally:
        source.close()


def _values(snapshot: client.ClientObjectSnapshot) -> set[str]:
    return {field.value for item in snapshot.objects for field in item.evidence_fields}


def _enable_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    root, cache = tmp_path / "source", tmp_path / "c"
    root.mkdir()
    monkeypatch.setenv("GAMEXRAY_CACHE_DIR", str(cache))
    monkeypatch.setenv("GAMEXRAY_SNAPSHOT_CACHE", "1")
    return root, cache


@pytest.mark.parametrize(
    "prefix", ("war3map", "war3mapSkin", "war3campaign", "war3campaignSkin")
)
@pytest.mark.parametrize("ext", tuple(_NAME_FIELDS))
def test_all_binary_layer_bytes_invalidate_same_size_same_mtime_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prefix: str, ext: str
) -> None:
    root, cache = _enable_cache(tmp_path, monkeypatch)
    path = _write(root, f"{prefix}.{ext}", _binary(ext, "FIRST"))
    calls = []
    collect = client.collect_object_candidates

    def traced(*args, **kwargs):
        calls.append(kwargs.get("prefix"))
        return collect(*args, **kwargs)

    monkeypatch.setattr(client, "collect_object_candidates", traced)
    first = _snapshot(root)
    assert "FIRST" in _values(first)
    assert all(
        json.loads(field.encoded_evidence)["extra_ints"] == [0, 1]
        for obj in first.objects
        for field in obj.evidence_fields
    )
    first_cache = next(cache.rglob("*.pkl"))
    retained = first_cache.read_bytes(), first_cache.stat().st_mtime_ns
    count = len(calls)
    assert _snapshot(root) == first
    assert len(calls) == count  # A real cache hit bypasses collection.

    before = path.stat()
    path.write_bytes(_binary(ext, "OTHER"))
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    changed = _snapshot(root)

    assert "OTHER" in _values(changed) and "FIRST" not in _values(changed)
    assert len(calls) > count
    assert (first_cache.read_bytes(), first_cache.stat().st_mtime_ns) == retained
    assert len(tuple(cache.rglob("*.pkl"))) == 2


@pytest.mark.parametrize("prefix", ("war3map", "war3campaign"))
def test_shared_wts_bytes_refresh_skin_values_in_the_correct_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    root, cache = _enable_cache(tmp_path, monkeypatch)
    _write(root, f"{prefix}Skin.w3t", _binary("w3t", "TRIGSTR_7"))
    _write(root, f"{prefix}Skin.wts", b"STRING 7\n{\nWRONG\n}\n")
    table = _write(root, f"{prefix}.wts", b"STRING 7\n{\nFIRST\n}\n")

    first = _snapshot(root)
    table.write_bytes(b"STRING 7\n{\nOTHER\n}\n")
    second = _snapshot(root)

    assert "FIRST" in _values(first) and "OTHER" in _values(second)
    assert "WRONG" not in _values(first) | _values(second)
    assert any(
        field.value_source == f"{prefix}.wts#STRING 7"
        for obj in second.objects
        for field in obj.evidence_fields
    )
    table.unlink()
    removed = _snapshot(root)
    assert "TRIGSTR_7" in _values(removed)
    assert not {"FIRST", "OTHER", "WRONG"} & _values(removed)
    assert len(tuple(cache.rglob("*.pkl"))) == 3


def _slk(value: str) -> bytes:
    return (
        "ID;P\nB;X2;Y2\n"
        'C;X1;Y1;K"unitID"\nC;X2;Y1;K"Name"\n'
        f'C;X1;Y2;K"hX01"\nC;X2;Y2;K"{value}"\nE\n'
    ).encode("utf-8")


@pytest.mark.parametrize(
    "member", ("UnitData.slk", "Units\\unitdata.slk", "Doodads\\UNITDATA.SLK")
)
def test_supported_slk_alias_contents_participate_in_snapshot_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, member: str
) -> None:
    root, cache = _enable_cache(tmp_path, monkeypatch)
    path = _write(root, member, _slk("FIRST"))

    first = _snapshot(root)
    path.write_bytes(_slk("OTHER"))
    second = _snapshot(root)

    assert "FIRST" in _values(first) and "OTHER" in _values(second)
    assert "FIRST" not in _values(second)
    assert len(tuple(cache.rglob("*.pkl"))) == 2


def test_new_and_removed_binary_sources_cannot_reuse_an_older_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, cache = _enable_cache(tmp_path, monkeypatch)
    _write(root, "Units\\HumanUnitStrings.txt", b"[hX01]\nName=Anchor\n")
    initial = _snapshot(root)
    binary = _write(root, "war3mapSkin.w3t", _binary("w3t", "ADDED"))
    added = _snapshot(root)
    binary.unlink()
    removed = _snapshot(root)

    assert "ADDED" not in _values(initial)
    assert "ADDED" in _values(added)
    assert "ADDED" not in _values(removed)
    assert removed == initial
    assert len(tuple(cache.rglob("*.pkl"))) == 2


def test_text_and_locale_source_changes_refresh_the_cached_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, cache = _enable_cache(tmp_path, monkeypatch)
    text = _write(root, "Units\\HumanUnitStrings.txt", b"[hX01]\nName=Neutral\n")
    initial = _snapshot(root)
    text.write_bytes(b"[hX01]\nName=Changed\n")
    changed = _snapshot(root)
    _write(
        root,
        "war3.w3mod\\_locales\\zhcn.w3mod\\Units\\HumanUnitStrings.txt",
        "[hX01]\nName=中文\n".encode("utf-8"),
    )
    localized = _snapshot(root)

    assert "Neutral" in _values(initial)
    assert "Changed" in _values(changed)
    assert "中文" in _values(localized)
    assert len(tuple(cache.rglob("*.pkl"))) == 3


def test_v4_cache_is_rejected_and_retained_beside_new_v5_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, cache = _enable_cache(tmp_path, monkeypatch)
    _write(root, "war3mapSkin.w3t", _binary("w3t", "CURRENT"))
    old = cache / "client-snapshots" / "old-v4.pkl"
    old.parent.mkdir(parents=True)
    old.write_bytes(
        b"gamexray-client-snapshot-v4\n"
        + pickle.dumps(client.ClientObjectSnapshot((), False))
    )
    retained = old.read_bytes(), old.stat().st_mtime_ns

    assert client._load_snapshot_cache(old) is None
    snapshot = _snapshot(root)

    assert "CURRENT" in _values(snapshot)
    assert (old.read_bytes(), old.stat().st_mtime_ns) == retained
    new = next(path for path in cache.rglob("*.pkl") if path != old)
    assert new.read_bytes().startswith(b"gamexray-client-snapshot-v5\n")


@pytest.mark.parametrize("cached", (False, True))
def test_input_changes_during_snapshot_never_publish_or_reuse_stale_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cached: bool
) -> None:
    root, cache = _enable_cache(tmp_path, monkeypatch)
    path = _write(root, "war3mapSkin.w3t", _binary("w3t", "FIRST"))
    if cached:
        assert "FIRST" in _values(_snapshot(root))
    prior = {file: file.read_bytes() for file in cache.rglob("*.pkl")}
    assert bool(prior) is cached
    source = DirectoryDataSource(str(root))
    read_file = source.read_file
    changed = False

    def mutate_after_read(name: str) -> bytes:
        nonlocal changed
        payload = read_file(name)
        if name == "war3mapSkin.w3t" and not changed:
            changed = True
            path.write_bytes(_binary("w3t", "OTHER"))
        return payload

    monkeypatch.setattr(source, "read_file", mutate_after_read)
    with pytest.raises(OSError, match="source changed"):
        client.snapshot_client_base_objects(source)

    assert {file: file.read_bytes() for file in cache.rglob("*.pkl")} == prior
