"""导出文件名路径穿越防护测试。

地图内部文件名（来自不可信的 (listfile)）若是绝对路径或含 ..\\，
拼接输出路径时可能写到 out_dir 之外，造成任意文件写入。
_safe_export_path 必须把这类名字拒绝（返回 None），普通名字正常拼接。
"""
import os
import tempfile
import unittest

from w3xtool.api import (
    _export_all_impl,
    _export_recovered_named_files,
    _safe_export_path,
)
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


if __name__ == "__main__":
    unittest.main()
