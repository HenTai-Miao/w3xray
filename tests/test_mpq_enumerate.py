"""list_files 三层并集枚举：(listfile) + 内置固定名单 + war3map.imp。

保护图常删 (listfile)，靠内置固定名单 + imp 仍能枚举出实际存在的文件。
用 __new__ 造一个绕过 __init__ 的 MPQArchive，实例属性遮蔽 has_file/read_file 来隔离测逻辑。
"""
import struct
import unittest

from w3xtool.mpq import MPQArchive


def _make(present, listfile=None, imp=None):
    obj = MPQArchive.__new__(MPQArchive)
    obj._names = None
    files = dict(present)             # {name: bytes}
    if listfile is not None:
        files["(listfile)"] = listfile
    if imp is not None:
        files["war3map.imp"] = imp
    obj.has_file = lambda n: n in files
    obj.read_file = lambda n: files[n]
    return obj


def _imp_bytes(names):
    out = struct.pack("<ii", 1, len(names))
    for n in names:
        out += b"\x05" + n.encode("utf-8") + b"\x00"
    return out


class TestListFilesUnion(unittest.TestCase):
    def test_static_names_recovered_without_listfile(self):
        # 没有 (listfile)，但 war3map.j / w3i 实际存在 → 应被内置名单枚举出来
        arch = _make({"war3map.j": b"//", "war3map.w3i": b"\x00",
                      "war3map.w3u": b""})
        names = arch.list_files()
        self.assertIn("war3map.j", names)
        self.assertIn("war3map.w3i", names)
        self.assertIn("war3map.w3u", names)

    def test_absent_static_names_skipped(self):
        arch = _make({"war3map.j": b"//"})
        names = arch.list_files()
        self.assertIn("war3map.j", names)
        self.assertNotIn("war3map.w3e", names)   # 不存在的固定名不应混进来

    def test_listfile_names_preserved_even_if_unverified(self):
        # (listfile) 里的名原样保留（导出侧再校验），即使 has_file 查不到
        arch = _make({"war3map.j": b"//", "(listfile)": b""},
                     listfile=b"war3map.j\r\ncustom\\ghost.mdx\r\n")
        names = arch.list_files()
        self.assertIn("custom\\ghost.mdx", names)

    def test_imp_names_added_when_present(self):
        arch = _make({"war3mapImported\\model.mdx": b"MDX"},
                     imp=_imp_bytes(["model.mdx"]))   # imp 是相对名，补前缀后存在
        names = arch.list_files()
        self.assertIn("war3mapImported\\model.mdx", names)

    def test_dedup_case_insensitive(self):
        arch = _make({"war3map.j": b"//"},
                     listfile=b"War3Map.J\r\nwar3map.j\r\n")
        names = arch.list_files()
        lowered = [n.lower() for n in names]
        self.assertEqual(lowered.count("war3map.j"), 1)


if __name__ == "__main__":
    unittest.main()
