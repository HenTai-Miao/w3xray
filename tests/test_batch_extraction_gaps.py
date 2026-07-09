"""Batch coverage for high-impact extraction gaps."""

from __future__ import annotations

import os
import struct
import tempfile
import unittest
from dataclasses import dataclass

from w3xtool.api import MapData
from w3xtool.knowledge_resource_exports import write_resources
from w3xtool.knowledge_terrain_exports import write_terrain_exports
from w3xtool.knowledge_unknown_exports import write_unknown_files_from_archive
from w3xtool.mpq import FLAG_ENCRYPTED, FLAG_EXISTS
from w3xtool.mpq_files import list_archive_files
from w3xtool.resource_content_refs import build_resource_content_references


@dataclass(frozen=True, slots=True)
class FakeBlock:
    file_pos: int
    comp_size: int
    file_size: int
    flags: int


class BatchExtractionGapsTest(unittest.TestCase):
    def test_external_listfile_names_merge_into_archive_listing(self) -> None:
        # Given: an archive whose MPQ hash table contains a file absent from internal listfile.
        class Archive:
            def has_file(self, name: str) -> bool:
                return name.lower() in {"custom\\hero.mdx", "war3map.j"}

            def read_file(self, name: str) -> bytes:
                if name == "(listfile)":
                    return b"war3map.j\r\n"
                raise KeyError(name)

        # When: a user-provided listfile supplies the missing path.
        names = list_archive_files(
            Archive(),
            external_names=("Custom\\Hero.mdx", "custom\\hero.mdx", "missing.blp"),
        )

        # Then: only existing external names are added and case duplicates collapse.
        self.assertIn("Custom\\Hero.mdx", names)
        self.assertEqual([name.lower() for name in names].count("custom\\hero.mdx"), 1)
        self.assertNotIn("missing.blp", names)

    def test_unknown_blocks_are_written_to_knowledge_pack_shape(self) -> None:
        # Given: one named block, one recoverable anonymous block, and one raw fallback block.
        named = FakeBlock(0, 4, 4, FLAG_EXISTS)
        unknown = FakeBlock(4, 11, 11, FLAG_EXISTS)
        raw = FakeBlock(15, 5, 99, FLAG_EXISTS | FLAG_ENCRYPTED)

        class Archive:
            path = "fake.w3x"
            archive_offset = 0
            _data = b"JASSBLP1textureRAW!!"

            def list_files(self) -> list[str]:
                return ["war3map.j"]

            def block_index_of(self, name: str) -> int | None:
                return 0 if name == "war3map.j" else None

            def iter_blocks(self) -> tuple[tuple[int, FakeBlock], ...]:
                return ((0, named), (1, unknown), (2, raw))

            def read_block_anon(self, block: FakeBlock) -> bytes | None:
                if block is unknown:
                    return b"BLP1texture"
                if block is raw:
                    return None
                return b"JASS"

        # When: anonymous blocks are exported for the knowledge pack.
        with tempfile.TemporaryDirectory() as out:
            count = write_unknown_files_from_archive(Archive(), out)

            # Then: recoverable data and raw payloads are both preserved with one manifest.
            self.assertEqual(count, 3)
            with open(os.path.join(out, "Unknown", "block_000001.blp"), "rb") as handle:
                self.assertEqual(handle.read(), b"BLP1texture")
            with open(os.path.join(out, "UnknownRaw", "block_000002.raw"), "rb") as handle:
                self.assertEqual(handle.read(), b"RAW!!")
            with open(os.path.join(out, "Unknown_manifest.tsv"), encoding="utf-8") as handle:
                manifest = handle.read()
            self.assertIn("block_index\tkind\trelative_path\tbytes\tflags\tfile_size\tcomp_size\tstatus", manifest)
            self.assertIn("1\tUnknown\tUnknown/block_000001.blp\t11", manifest)
            self.assertIn("2\tUnknownRaw\tUnknownRaw/block_000002.raw\t5", manifest)

    def test_resource_body_contents_add_second_level_references(self) -> None:
        # Given: a readable UI config file references a texture not present in object fields/scripts.
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as out:
            os.makedirs(os.path.join(source, "UI", "FrameDef"), exist_ok=True)
            os.makedirs(os.path.join(source, "war3mapImported"), exist_ok=True)
            with open(os.path.join(source, "UI", "FrameDef", "Main.fdf"), "wb") as handle:
                handle.write(b'Backdrop "war3mapImported\\\\Panel.blp"\n')
            with open(os.path.join(source, "war3mapImported", "Panel.blp"), "wb") as handle:
                handle.write(b"BLP1panel")
            md = MapData(path=source, name="二级资源图")
            md.all_files = ["UI\\FrameDef\\Main.fdf", "war3mapImported\\Panel.blp"]

            # When: resource content references are scanned and resources are written.
            report = build_resource_content_references(md)
            write_resources(md, out)

            # Then: the texture is linked to the FDF body and treated as referenced.
            self.assertEqual(report.items[0].source_path, "ui\\framedef\\main.fdf")
            self.assertEqual(report.items[0].target_path, "war3mapimported\\panel.blp")
            with open(os.path.join(out, "资源内容引用.tsv"), encoding="utf-8") as handle:
                content_refs = handle.read()
            self.assertIn("ui\\framedef\\main.fdf\twar3mapimported\\panel.blp", content_refs)
            with open(os.path.join(out, "资源资产索引.tsv"), encoding="utf-8") as handle:
                inventory = handle.read()
            self.assertIn("war3mapimported\\panel.blp\t图像\t存在/已引用", inventory)

    def test_terrain_and_pathing_exports_are_written_for_knowledge_pack(self) -> None:
        # Given: a readable source folder with W3E terrain and WPM pathing files.
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as out:
            with open(os.path.join(source, "war3map.w3e"), "wb") as handle:
                handle.write(_w3e_with_tiles())
            with open(os.path.join(source, "war3map.wpm"), "wb") as handle:
                handle.write(b"MP3W" + struct.pack("<iii", 0, 2, 2) + bytes((0x02, 0x04, 0x08, 0x40)))
            md = MapData(path=source, name="地形图")

            # When: terrain exports are written.
            count = write_terrain_exports(md, out)

            # Then: terrain grid, texture usage, and pathing flags are visible as TSV.
            self.assertEqual(count, 3)
            with open(os.path.join(out, "地形摘要.tsv"), encoding="utf-8") as handle:
                summary = handle.read()
            self.assertIn("网格\t2×2", summary)
            self.assertIn("基础地形集\tL", summary)
            with open(os.path.join(out, "地形纹理.tsv"), encoding="utf-8") as handle:
                textures = handle.read()
            self.assertIn("地表\t0\tLdrt", textures)
            self.assertIn("LordaeronSummer", textures)
            with open(os.path.join(out, "路径网格.tsv"), encoding="utf-8") as handle:
                pathing = handle.read()
            self.assertIn("宽度\t2", pathing)
            self.assertIn("禁止行走\t1", pathing)


def _w3e_with_tiles() -> bytes:
    return (
        b"W3E!"
        + struct.pack("<i", 11)
        + b"L"
        + struct.pack("<i", 0)
        + struct.pack("<i", 1)
        + b"Ldrt"
        + struct.pack("<i", 0)
        + struct.pack("<ii", 2, 2)
        + struct.pack("<ff", -128.0, -128.0)
        + _tile(8192, 8192 | 0x4000, 0x01, texture=0)
        + _tile(8704, 8704, 0x04)
        + _tile(7680, 8192, 0x02)
        + _tile(9216, 9216, 0x08, texture=0)
    )


def _tile(
    height: int,
    water: int,
    flags: int,
    *,
    texture: int = 1,
    cliff_texture: int = 0,
    cliff_level: int = 0,
) -> bytes:
    texture_and_flags = (flags << 4) | texture
    cliff_data = (cliff_texture << 4) | cliff_level
    return struct.pack("<HHBBB", height, water, texture_and_flags, 0, cliff_data)
