"""Native CASC data-source smoke tests."""

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest

from w3xtool.casc_source import CascDataSource
from w3xtool.game_data_source import open_game_data_source, probe_game_data_path


def _blte(payload: bytes) -> bytes:
    return b"BLTE" + (0).to_bytes(4, "big") + b"N" + payload


def _idx_row(encoding_key: bytes, archive_index: int, offset: int, size: int) -> bytes:
    high = archive_index >> 2
    low = offset | ((archive_index & 0x03) << 30)
    return (
        encoding_key[:9]
        + bytes([high])
        + low.to_bytes(4, "big")
        + size.to_bytes(4, "little")
    )


def test_casc_exact_lookup_does_not_use_path_map_suffix(tmp_path) -> None:
    # Given
    data_dir = tmp_path / "Data" / "data"
    data_dir.mkdir(parents=True)
    payload = b"BLP1hero"
    blte = _blte(payload)
    block = (
        hashlib.md5(blte).digest()
        + (len(blte) + 30).to_bytes(4, "little")
        + (b"\0" * 10)
        + blte
    )
    offset = 32
    (data_dir / "data.000").write_bytes((b"\0" * offset) + block)
    key = bytes.fromhex("00112233445566778899aabbccddeeff")
    (data_dir / "0000000000000000.idx").write_bytes(_idx_row(key, 0, offset, len(blte)))
    (tmp_path / "w3xray-casc-paths.tsv").write_text(
        "war3.w3mod\\Icons\\BTNHero.blp\t00112233445566778899aabbccddeeff\n",
        encoding="utf-8",
    )
    source = CascDataSource(str(tmp_path))

    # When / Then
    assert source.has_file(r"Icons\BTNHero.blp")
    assert not source.has_exact_file(r"Icons\BTNHero.blp")
    assert source.has_exact_file(r"war3.w3mod\Icons\BTNHero.blp")
    assert source.read_exact_file(r"war3.w3mod\Icons\BTNHero.blp") == payload


class CascSourceTest(unittest.TestCase):
    def test_native_casc_source_reads_unencrypted_blte_from_idx_and_data_archive(
        self,
    ) -> None:
        # Given: a minimal native CASC directory with a path map, idx row and data archive block.
        with tempfile.TemporaryDirectory() as root:
            data_dir = os.path.join(root, "Data", "data")
            os.makedirs(data_dir)
            with open(
                os.path.join(root, ".build.info"), "w", encoding="utf-8"
            ) as handle:
                handle.write("Build Key|Version\n")
            payload = b"ID;name\nhfoo;Footman\n"
            blte = _blte(payload)
            block = (
                hashlib.md5(blte).digest()
                + (len(blte) + 30).to_bytes(4, "little")
                + (b"\0" * 10)
                + blte
            )
            offset = 32
            with open(os.path.join(data_dir, "data.000"), "wb") as handle:
                handle.write(b"\0" * offset + block)
            key = bytes.fromhex("00112233445566778899aabbccddeeff")
            with open(os.path.join(data_dir, "0000000000000000.idx"), "wb") as handle:
                handle.write(_idx_row(key, 0, offset, len(blte)))
            with open(
                os.path.join(root, "w3xray-casc-paths.tsv"), "w", encoding="utf-8"
            ) as handle:
                handle.write(
                    "war3.w3mod\\units\\HumanUnitStrings.txt\t00112233445566778899aabbccddeeff\n"
                )

            # When: the game-data path is probed and opened.
            probe = probe_game_data_path(root)
            source = open_game_data_source(root)

            # Then: the source ignores the namespace prefix and reads data.000.
            self.assertEqual(probe.kind, "native_casc")
            self.assertTrue(probe.is_readable)
            self.assertIsInstance(source, CascDataSource)
            assert source is not None
            self.assertTrue(source.has_file("units/HumanUnitStrings.txt"))
            self.assertEqual(source.read_file("Units\\HumanUnitStrings.txt"), payload)


if __name__ == "__main__":
    unittest.main()
