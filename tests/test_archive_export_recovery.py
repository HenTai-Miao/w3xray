"""Real MPQ recovery keeps exact members and follows only verified hints."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

import pytest

from gametool.api import export_all_files
from gametool.archive_export_recovery import _resource_name_candidates
from gametool.mpq import MPQArchive
from gametool.mpq_crypto import _decrypt, hash_name_bytes
from gametool.mpq_names import HashEntry

from .test_mpq_names_locale import _encrypt


def _archive_bytes(
    members: list[tuple[str, int, int, bytes, bool]],
    *,
    duplicate_hash_entry: bool = False,
    name_codec: str = "utf-8",
) -> bytes:
    """Encode independent blocks, including locale/platform and encrypted data."""
    capacity = 8
    while capacity < len(members) * 2:
        capacity *= 2
    hash_position = 32
    block_position = hash_position + capacity * 16
    position = block_position + len(members) * 16
    empty = (0xFFFFFFFF, 0xFFFFFFFF, 0xFFFF, 0xFFFF, 0xFFFFFFFF)
    hashes: list[tuple[int, int, int, int, int]] = [empty] * capacity
    blocks: list[bytes] = []
    payloads: list[bytes] = []
    for index, (name, locale, platform, payload, encrypted) in enumerate(members):
        raw_name = name.encode(name_codec)
        start = hash_name_bytes(raw_name, 0) & (capacity - 1)
        while hashes[start][4] != 0xFFFFFFFF:
            start = (start + 1) & (capacity - 1)
        entry = (
            hash_name_bytes(raw_name, 1),
            hash_name_bytes(raw_name, 2),
            locale,
            platform,
            index,
        )
        hashes[start] = entry
        if duplicate_hash_entry and index == len(members) - 1:
            slot = (start + 1) & (capacity - 1)
            while hashes[slot][4] != 0xFFFFFFFF:
                slot = (slot + 1) & (capacity - 1)
            hashes[slot] = entry
        flags = 0x81000000 | (0x10000 if encrypted else 0)
        key = hash_name_bytes(raw_name.rsplit(b"\\", 1)[-1], 3)
        stored = _encrypt(payload, key) if encrypted else payload
        blocks.append(struct.pack("<IIII", position, len(stored), len(payload), flags))
        payloads.append(stored)
        position += len(stored)
    return b"".join(
        (
            struct.pack(
                "<4sIIHHIIII",
                b"MPQ\x1a",
                32,
                position,
                0,
                3,
                hash_position,
                block_position,
                capacity,
                len(members),
            ),
            _encrypt(
                b"".join(struct.pack("<IIHHI", *entry) for entry in hashes),
                hash_name_bytes(b"(hash table)", 3),
            ),
            _encrypt(b"".join(blocks), hash_name_bytes(b"(block table)", 3)),
            *payloads,
        )
    )


def _export(
    tmp_path: Path, data: bytes, *, external_names: tuple[str, ...] = ()
) -> Path:
    source = tmp_path / "map.w3x"
    source.write_bytes(data)
    before = source.stat()
    output = tmp_path / "out"
    export_all_files(str(source), str(output), external_names=external_names)
    assert source.read_bytes() == data
    assert source.stat().st_mtime_ns == before.st_mtime_ns
    return output


def _manifest(output: Path) -> list[dict[str, str]]:
    text = (output / "RecoveredNames" / "manifest.tsv").read_text(encoding="utf-8")
    return [
        dict(cell.split("=", 1) for cell in line.split("\t")[1:])
        for line in text.splitlines()
        if line.startswith("OK\t")
    ]


def test_recovery_exports_every_locale_and_platform_with_exact_payload(
    tmp_path: Path,
) -> None:
    payloads = (b"BLP1neutral", b"BLP1locale0409", b"BLP1platform01")
    source = _archive_bytes(
        [
            ("war3map.j", 0, 0, b'"asset.blp"', False),
            ("asset.blp", 0, 0, payloads[0], True),
            ("asset.blp", 0x0409, 0, payloads[1], True),
            ("asset.blp", 0, 1, payloads[2], True),
        ]
    )

    output = _export(tmp_path, source)

    assert (output / "asset.blp").read_bytes() == payloads[0]
    rows = _manifest(output)
    assert {(row["block"], row["locale"], row["platform"]) for row in rows} == {
        ("1", "0", "0"),
        ("2", "1033", "0"),
        ("3", "0", "1"),
    }
    assert len({row["path"] for row in rows}) == 3
    for row in rows:
        payload = (output / json.loads(row["path"])).read_bytes()
        assert payload == payloads[int(row["block"]) - 1]
        assert row["sha256"] == hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize("script_name", ["war3map.j", r"scripts\war3map.j"])
def test_named_encrypted_script_recovers_chained_models_portraits_and_textures(
    tmp_path: Path, script_name: str
) -> None:
    model = b'MDLX\0"Textures\\hidden.blp"\0'
    hidden = b"BLP1hidden"
    portrait = b"MDLXportrait"
    source = _archive_bytes(
        [
            (script_name, 0, 0, b'"Models\\Hero.mdl"', True),
            (r"Models\Hero.mdx", 0, 0, model, True),
            (r"Models\Hero_Portrait.mdx", 0, 0, portrait, True),
            (r"Textures\hidden.blp", 0, 0, hidden, True),
        ]
    )

    output = _export(tmp_path, source)

    assert (output / "Models" / "Hero.mdx").read_bytes() == model
    assert (output / "Models" / "Hero_Portrait.mdx").read_bytes() == portrait
    assert (output / "Textures" / "hidden.blp").read_bytes() == hidden
    assert not (output / "Models" / "Hero.mdl").exists()
    assert not (output / "UnknownRaw").exists()
    assert {row["block"] for row in _manifest(output)} == {"1", "2", "3"}


def test_modl_internal_name_is_only_a_hash_verified_import_hint(tmp_path: Path) -> None:
    model_name = b"HeroModel" + bytes(80 - len(b"HeroModel"))
    carrier = b"MDLX" + struct.pack("<4sI", b"MODL", 80) + model_name
    target = b"MDLXencrypted-model"
    source = _archive_bytes(
        [
            ("unknown-carrier.bin", 0, 0, carrier, False),
            (r"war3mapImported\HeroModel.mdx", 0, 0, target, True),
        ]
    )

    output = _export(tmp_path, source)

    assert (output / "war3mapImported" / "HeroModel.mdx").read_bytes() == target
    assert not (output / "HeroModel.mdx").exists()
    assert not (output / "war3mapImported" / "HeroModel_Portrait.mdx").exists()
    assert {row["block"] for row in _manifest(output)} == {"1"}
    assert any(path.read_bytes() == carrier for path in (output / "Unknown").iterdir())


def test_recovered_payload_and_manifest_do_not_overwrite_existing_output(
    tmp_path: Path,
) -> None:
    output = tmp_path / "out"
    (output / "RecoveredNames" / "blocks").mkdir(parents=True)
    (output / "asset.blp").write_bytes(b"existing-file")
    (output / "RecoveredNames" / "manifest.tsv").write_bytes(b"existing-report")
    collision = (
        output
        / "RecoveredNames"
        / "blocks"
        / "block_000001-locale_0000-platform_00.blp"
    )
    collision.write_bytes(b"existing-variant")
    payload = b"BLP1new-resource"
    source = _archive_bytes(
        [("war3map.j", 0, 0, b'"asset.blp"', False), ("asset.blp", 0, 0, payload, True)]
    )

    _export(tmp_path, source)

    assert (output / "asset.blp").read_bytes() == b"existing-file"
    assert (
        output / "RecoveredNames" / "manifest.tsv"
    ).read_bytes() == b"existing-report"
    assert collision.read_bytes() == b"existing-variant"
    assert collision.with_stem(collision.stem + "-2").read_bytes() == payload
    assert "block=1" in (output / "RecoveredNames" / "manifest-2.tsv").read_text(
        encoding="utf-8"
    )


def test_replicated_hash_rows_do_not_duplicate_recovered_payload(
    tmp_path: Path,
) -> None:
    source = _archive_bytes(
        [
            ("war3map.j", 0, 0, b'"asset.blp"', False),
            ("asset.blp", 0, 0, b"BLP1x", True),
        ],
        duplicate_hash_entry=True,
    )

    output = _export(tmp_path, source)

    assert len(_manifest(output)) == 1
    assert (output / "asset.blp").read_bytes() == b"BLP1x"


def test_entry_read_rejects_unproved_block_and_locale_identity(tmp_path: Path) -> None:
    source = tmp_path / "entry.w3x"
    source.write_bytes(_archive_bytes([("asset.blp", 0, 0, b"BLP1x", True)]))
    with MPQArchive(str(source)) as archive:
        entry = next(row for row in archive.hash_table if row.block_index == 0)
        assert archive.read_file_entry("asset.blp", entry) == b"BLP1x"
        for changed in (
            entry._replace(block_index=1),
            entry._replace(locale=0x0409),
            HashEntry(entry.name_a, entry.name_b, 0, 1, 0),
        ):
            with pytest.raises(KeyError):
                archive.read_file_entry("asset.blp", changed)


def test_matching_hash_outside_probe_chain_stays_unconfirmed(tmp_path: Path) -> None:
    data = bytearray(
        _archive_bytes(
            [
                ("war3map.j", 0, 0, b'"asset.blp"', False),
                ("asset.blp", 0, 0, b"BLP1hidden", True),
            ]
        )
    )
    key = hash_name_bytes(b"(hash table)", 3)
    rows = list(struct.iter_unpack("<IIHHI", _decrypt(bytes(data[32:160]), key)))
    index = next(i for i, entry in enumerate(rows) if entry[4] == 1)
    entry = rows[index]
    rows[index] = (0xFFFFFFFF, 0xFFFFFFFF, 0xFFFF, 0xFFFF, 0xFFFFFFFF)
    # An empty starting slot makes this otherwise matching row unreachable.
    moved = (index + 1) % len(rows)
    while rows[moved][4] != 0xFFFFFFFF:
        moved = (moved + 1) % len(rows)
    rows[moved] = entry
    data[32:160] = _encrypt(b"".join(struct.pack("<IIHHI", *row) for row in rows), key)

    output = _export(tmp_path, bytes(data))

    assert not (output / "asset.blp").exists()
    assert (output / "UnknownRaw" / "File000001.mpqraw").is_file()
    assert _manifest(output) == []


def test_same_locale_duplicate_name_keeps_both_block_payloads(tmp_path: Path) -> None:
    payloads = (b"BLP1first", b"BLP1last")
    source = _archive_bytes(
        [
            ("war3map.j", 0, 0, b'"asset.blp"', False),
            ("asset.blp", 0, 0, payloads[0], True),
            ("asset.blp", 0, 0, payloads[1], True),
        ]
    )

    output = _export(tmp_path, source)

    assert (output / "asset.blp").read_bytes() == payloads[1]
    rows = _manifest(output)
    assert {row["block"] for row in rows} == {"1", "2"}
    assert {(output / json.loads(row["path"])).read_bytes() for row in rows} == set(
        payloads
    )


@pytest.mark.parametrize("external_name", [False, True])
def test_utf8_resource_reference_keeps_exact_hash_bytes(
    tmp_path: Path, external_name: bool
) -> None:
    name = "Textures\\英雄.blp"
    source = _archive_bytes(
        [
            ("war3map.j", 0, 0, f'"{name}"'.encode(), False),
            (name, 0, 0, b"BLP1utf8", True),
        ]
    )

    output = _export(tmp_path, source, external_names=(name,) if external_name else ())

    assert (output / "Textures" / "英雄.blp").read_bytes() == b"BLP1utf8"
    alternative = name.encode("utf-8").decode("gbk")
    manifest = (output / "RecoveredNames" / "manifest.tsv").read_text(encoding="utf-8")
    assert any(
        line.startswith("ALIAS\t")
        and json.dumps(alternative, ensure_ascii=False) in line
        and "verified-alternative-name-for-same-block" in line
        for line in manifest.splitlines()
    )


@pytest.mark.parametrize("external_name", [False, True])
def test_shared_block_retains_every_verified_locale_and_platform_source(
    tmp_path: Path, external_name: bool
) -> None:
    payload = b"BLP1shared-block"
    data = bytearray(
        _archive_bytes(
            [
                ("war3map.j", 0, 0, b'"asset.blp"', False),
                ("asset.blp", 0, 0, payload, True),
            ]
        )
    )
    key = hash_name_bytes(b"(hash table)", 3)
    rows = list(struct.iter_unpack("<IIHHI", _decrypt(bytes(data[32:160]), key)))
    original_slot = next(i for i, entry in enumerate(rows) if entry[4] == 1)
    name_a, name_b, _, _, block = rows[original_slot]
    expected = {(0, 0): original_slot}
    for locale, platform in ((0x0409, 0), (0, 1)):
        slot = original_slot
        while rows[slot][4] != 0xFFFFFFFF:
            slot = (slot + 1) % len(rows)
        rows[slot] = (name_a, name_b, locale, platform, block)
        expected[locale, platform] = slot
    data[32:160] = _encrypt(b"".join(struct.pack("<IIHHI", *row) for row in rows), key)

    output = _export(
        tmp_path, bytes(data), external_names=("asset.blp",) if external_name else ()
    )

    assert (output / "asset.blp").read_bytes() == payload
    manifest = (output / "RecoveredNames" / "manifest.tsv").read_text(encoding="utf-8")
    records = [
        (
            line.split("\t", 1)[0],
            dict(cell.split("=", 1) for cell in line.split("\t")[1:]),
        )
        for line in manifest.splitlines()
    ]
    sources = [(status, row) for status, row in records if row["block"] == "1"]
    assert len(sources) == len(expected)
    assert sum(status == "OK" for status, _ in sources) == (0 if external_name else 1)
    for status, row in sources:
        assert status in {"OK", "ALIAS"}
        assert (
            int(row["hash_index"]) == expected[int(row["locale"]), int(row["platform"])]
        )
        assert json.loads(row["path"]) == "asset.blp"
        assert row["sha256"] == hashlib.sha256(payload).hexdigest()
    assert not (output / "RecoveredNames" / "blocks").exists()


def test_gbk_resource_reference_keeps_exact_hash_and_encryption_key(
    tmp_path: Path,
) -> None:
    name = "Textures\\英雄.blp"
    source = _archive_bytes(
        [
            ("war3map.j", 0, 0, f'"{name}"'.encode("gbk"), True),
            (name, 0, 0, b"BLP1gbk", True),
        ],
        name_codec="gbk",
    )

    output = _export(tmp_path, source)

    assert (output / "Textures" / "英雄.blp").read_bytes() == b"BLP1gbk"
    assert {row["block"] for row in _manifest(output)} == {"1"}


def test_external_name_recovers_other_locale_and_its_encrypted_references(
    tmp_path: Path,
) -> None:
    name = r"Private\source.mdx"
    localized = b'MDLX\0"Textures\\localized.blp"\0'
    source = _archive_bytes(
        [
            (name, 0, 0, b"MDLXneutral", True),
            (name, 0x0409, 0, localized, True),
            (r"Textures\localized.blp", 0, 0, b"BLP1localized", True),
        ]
    )

    output = _export(tmp_path, source, external_names=(name,))

    assert (output / "Private" / "source.mdx").read_bytes() == b"MDLXneutral"
    assert (output / "Textures" / "localized.blp").read_bytes() == b"BLP1localized"
    rows = _manifest(output)
    assert {row["block"] for row in rows} == {"1", "2"}
    row = next(row for row in rows if row["block"] == "1")
    assert (output / json.loads(row["path"])).read_bytes() == localized


def test_modl_chunks_follow_encoded_boundaries_without_a_chunk_count_limit() -> None:
    prefix = b"MDLX" + struct.pack("<4sI", b"TEST", 0) * 129
    payload = b"LastModel" + bytes(80 - len(b"LastModel"))
    data = prefix + struct.pack("<4sI", b"MODL", 80) + payload
    assert r"war3mapImported\LastModel.mdx" in _resource_name_candidates(data)
    # A truncated declared chunk is not treated as a confirmed MODL string.
    malformed = prefix + struct.pack("<4sI", b"MODL", 81) + payload
    assert _resource_name_candidates(malformed) == set()
