"""导出文件名路径穿越防护测试。

地图内部文件名（来自不可信的 (listfile)）若是绝对路径或含 ..\\，
拼接输出路径时可能写到 out_dir 之外，造成任意文件写入。
_safe_export_path 必须把这类名字拒绝（返回 None），普通名字正常拼接。
"""
import os
import tempfile
import unittest
from pathlib import Path

from w3xtool.api import (
    GameObject,
    MapData,
    _export_all_impl,
    _export_recovered_named_files,
    _safe_export_path,
)
from w3xtool.knowledge_assets import export_resource_bodies
from w3xtool.knowledge_object_exports import write_object_ids
from w3xtool.knowledge_script_exports import write_readable_scripts
from w3xtool.knowledge_unknown_exports import write_unknown_files_from_archive
from w3xtool.mpq import FLAG_ENCRYPTED, FLAG_EXISTS, HASH_NAME_A, HASH_NAME_B, _Block, _hash


class TestSafeExportPath(unittest.TestCase):
    def setUp(self):
        self.out = os.path.realpath(os.environ.get("TEMP", "."))

    def test_normal_name_joins_under_out_dir(self):
        dest = _safe_export_path(self.out, "war3map.j")
        self.assertEqual(dest, os.path.join(self.out, "war3map.j"))

    def test_subdir_name_allowed(self):
        dest = _safe_export_path(self.out, "scripts\\war3map.j")
        self.assertEqual(dest, os.path.join(self.out, "scripts", "war3map.j"))

    def test_windows_absolute_path_rejected(self):
        self.assertIsNone(
            _safe_export_path(self.out, "C:\\Windows\\System32\\evil.dll"))

    def test_parent_traversal_rejected(self):
        self.assertIsNone(
            _safe_export_path(self.out, "..\\..\\..\\evil.bat"))

    def test_embedded_traversal_rejected(self):
        self.assertIsNone(
            _safe_export_path(self.out, "scripts\\..\\..\\evil"))

    def test_empty_name_rejected(self):
        self.assertIsNone(_safe_export_path(self.out, ""))
        self.assertIsNone(_safe_export_path(self.out, "\\"))


class TestExportUnrecoverableBlocks(unittest.TestCase):
    def test_unrecoverable_anonymous_block_is_exported_raw(self):
        block = _Block(
            file_pos=2,
            comp_size=4,
            file_size=99,
            flags=FLAG_EXISTS | FLAG_ENCRYPTED,
        )

        class Archive:
            path = "fake.w3x"
            archive_offset = 0
            _data = b"0123456789"

            def list_files(self):
                return []

            def has_file(self, _name):
                return False

            def iter_blocks(self):
                yield 7, block

            def read_block_anon(self, _block):
                return None

        with tempfile.TemporaryDirectory() as out:
            _export_all_impl(Archive(), out, 1)
            raw_path = os.path.join(out, "UnknownRaw", "File000007.mpqraw")
            manifest_path = os.path.join(out, "UnknownRaw", "manifest.tsv")

            with open(raw_path, "rb") as f:
                self.assertEqual(f.read(), b"2345")
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = f.read()
            self.assertIn("File000007.mpqraw", manifest)
            self.assertIn("file_size=99", manifest)


class TestKnownWorldMetadataExport(unittest.TestCase):
    def test_world_metadata_files_export_without_listfile(self):
        class Archive:
            def __init__(self):
                self._files = {
                    "war3map.w3r": b"regions",
                    "war3map.w3c": b"cameras",
                    "war3map.w3s": b"sounds",
                }

            def list_files(self):
                return []

            def has_file(self, name):
                return name in self._files

            def read_file(self, name):
                return self._files[name]

            def block_index_of(self, _name):
                return None

            def iter_blocks(self):
                return iter(())

            def read_block_anon(self, _block):
                return None

        with tempfile.TemporaryDirectory() as out:
            _export_all_impl(Archive(), out, 1)
            with open(os.path.join(out, "war3map.w3r"), "rb") as f:
                self.assertEqual(f.read(), b"regions")
            with open(os.path.join(out, "war3map.w3c"), "rb") as f:
                self.assertEqual(f.read(), b"cameras")
            with open(os.path.join(out, "war3map.w3s"), "rb") as f:
                self.assertEqual(f.read(), b"sounds")


class TestRecoveredNamedExport(unittest.TestCase):
    def test_exports_hash_matched_name_from_model_reference(self):
        model = _Block(file_pos=0, comp_size=1, file_size=1, flags=FLAG_EXISTS)
        texture = _Block(file_pos=1, comp_size=1, file_size=1, flags=FLAG_EXISTS)
        name = "Textures\\foo.blp"

        class Archive:
            block_table = [model, texture]
            hash_table = [(_hash(name, HASH_NAME_A), _hash(name, HASH_NAME_B), 0, 0, 1)]

            def list_files(self):
                return []

            def iter_blocks(self):
                yield 0, model
                yield 1, texture

            def read_block_anon(self, block):
                if block is model:
                    return b"MDLX\x00Textures\\foo.blp\x00"
                if block is texture:
                    return b"BLP1texture"
                return None

            def read_file(self, file_name):
                if file_name == name:
                    return b"BLP1texture"
                raise KeyError(file_name)

        with tempfile.TemporaryDirectory() as out:
            exported_blocks = set()
            count = _export_recovered_named_files(Archive(), out, exported_blocks)

            self.assertEqual(count, 1)
            self.assertIn(1, exported_blocks)
            with open(os.path.join(out, "Textures", "foo.blp"), "rb") as f:
                self.assertEqual(f.read(), b"BLP1texture")
            self.assertTrue(os.path.exists(os.path.join(out, "RecoveredNames", "manifest.tsv")))


class TestUnifiedSinkSafety(unittest.TestCase):
    def test_resource_body_does_not_follow_body_directory_symlink(self):
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as root:
            source_path = Path(source)
            (source_path / "Assets").mkdir()
            (source_path / "Assets" / "Panel.blp").write_bytes(b"BLP1panel")
            output = Path(root) / "resources"
            output.mkdir()
            outside = Path(root) / "outside"
            outside.mkdir()
            self._symlink(output / "素材文件", outside, directory=True)
            md = MapData(path=source, name="资源目录安全图")
            md.all_files = [r"Assets\Panel.blp"]

            report = export_resource_bodies(md, str(output))

            self.assertEqual(report.exported_count, 0)
            self.assertFalse((outside / "assets" / "panel.blp").exists())

    def test_resource_body_does_not_follow_nested_directory_symlink(self):
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as root:
            source_path = Path(source)
            (source_path / "Assets").mkdir()
            (source_path / "Assets" / "Panel.blp").write_bytes(b"BLP1panel")
            output = Path(root) / "resources"
            body = output / "素材文件"
            body.mkdir(parents=True)
            outside = Path(root) / "outside"
            outside.mkdir()
            self._symlink(body / "assets", outside, directory=True)
            md = MapData(path=source, name="资源安全图")
            md.all_files = [r"Assets\Panel.blp"]

            report = export_resource_bodies(md, str(output))

            self.assertEqual(report.exported_count, 0)
            self.assertFalse((outside / "panel.blp").exists())

    def test_unknown_block_does_not_follow_output_directory_symlink(self):
        class Block:
            file_pos = 0
            comp_size = 4
            file_size = 4
            flags = FLAG_EXISTS

        class Archive:
            path = "fake.w3x"
            archive_offset = 0
            _data = b"BLP1"

            def list_files(self):
                return []

            def block_index_of(self, _name):
                return None

            def iter_blocks(self):
                return ((0, Block()),)

            def read_block_anon(self, _block):
                return b"BLP1"

        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "unknown"
            output.mkdir()
            outside = Path(root) / "outside"
            outside.mkdir()
            self._symlink(output / "Unknown", outside, directory=True)

            write_unknown_files_from_archive(Archive(), str(output))

            self.assertFalse((outside / "block_000000.blp").exists())

    def test_object_category_file_does_not_follow_destination_symlink(self):
        md = MapData(path="x.w3x", name="对象安全图")
        md.objects = {
            "单位": [GameObject("单位", "w3u", "H001", "Hpal", "单位", True)],
        }
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "objects"
            output.mkdir()
            outside = Path(root) / "outside.tsv"
            outside.write_text("before", encoding="utf-8")
            self._symlink(output / "单位.tsv", outside)

            write_object_ids(md, str(output))

            self.assertEqual(outside.read_text(encoding="utf-8"), "before")

    def test_script_file_does_not_follow_destination_symlink(self):
        md = MapData(path="x.w3x", name="脚本安全图")
        md.scripts = {"war3map.j": "function main takes nothing returns nothing\nendfunction\n"}
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "scripts"
            output.mkdir()
            outside = Path(root) / "outside.j"
            outside.write_text("before", encoding="utf-8")
            self._symlink(output / "war3map.j", outside)

            write_readable_scripts(md, str(output))

            self.assertEqual(outside.read_text(encoding="utf-8"), "before")

    def test_script_parent_traversal_is_rejected_before_flattening(self):
        md = MapData(path="x.w3x", name="脚本路径安全图")
        md.scripts = {"../escape.j": "function escape takes nothing returns nothing\nendfunction\n"}
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "scripts"

            count = write_readable_scripts(md, str(output))

            self.assertEqual(count, 0)
            self.assertFalse((output / "escape.j").exists())

    def _symlink(self, link: Path, target: Path, *, directory: bool = False) -> None:
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError as exc:
            self.skipTest(f"symlink unavailable: {exc}")


if __name__ == "__main__":
    unittest.main()
