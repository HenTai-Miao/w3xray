"""平台加密脚本签名检测：KKWE 存根地图的证据落地与审计告警。"""

from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import dataclass

from gametool.api import MapData
from gametool.audit import AuditSeverity, build_audit_report
from gametool.knowledge_unknown_exports import write_unknown_files_from_archive
from gametool.mpq import FLAG_EXISTS
from gametool.script_protection import detect_encrypted_script_label


@dataclass(frozen=True, slots=True)
class FakeBlock:
    file_pos: int
    comp_size: int
    file_size: int
    flags: int


class ScriptProtectionTest(unittest.TestCase):
    def test_detects_kkwe_signature_head(self) -> None:
        # Given: a KKWE-encrypted payload head plus ordinary script/texture heads.
        payload = b"KKWE PLUG-IN ENCRYPT JASS!" + b"\x1a\x00" + b"rest" * 8

        # Then: only the encrypted marker yields a label.
        self.assertEqual(detect_encrypted_script_label(payload), "KKWE 加密 JASS")
        self.assertIsNone(
            detect_encrypted_script_label(b"function main takes nothing returns")
        )
        self.assertIsNone(detect_encrypted_script_label(b"BLP1texture"))

    def test_unknown_export_reports_encrypted_script_block(self) -> None:
        # Given: one named script block and one anonymous KKWE-encrypted block.
        payload = b"KKWE PLUG-IN ENCRYPT JASS!" + b"\x00" * 8
        encrypted = FakeBlock(0, len(payload), len(payload), FLAG_EXISTS)

        class Archive:
            path = "fake.w3x"
            archive_offset = 0
            _data = payload

            def list_files(self) -> list[str]:
                return ["war3map.j"]

            def block_index_of(self, name: str) -> int | None:
                return 0 if name == "war3map.j" else None

            def iter_blocks(self) -> tuple[tuple[int, FakeBlock], ...]:
                return ((1, encrypted),)

            def read_block_anon(self, block: FakeBlock) -> bytes:
                return payload

        # When: anonymous blocks are exported into a knowledge pack dir.
        with tempfile.TemporaryDirectory() as out:
            write_unknown_files_from_archive(Archive(), out)  # pyright: ignore[reportArgumentType]

            # Then: an encrypted-script evidence report lands next to the manifest.
            report_path = os.path.join(out, "加密脚本检测.txt")
            self.assertTrue(os.path.exists(report_path))
            with open(report_path, encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("KKWE 加密 JASS", content)
            self.assertIn("000001", content)
            self.assertIn("静态解析读不到触发逻辑", content)

    def test_plain_archives_do_not_emit_encrypted_report(self) -> None:
        # Given: an anonymous block without any known encryption signature.
        payload = b"BLP1texturedata"
        plain = FakeBlock(0, len(payload), len(payload), FLAG_EXISTS)

        class Archive:
            path = "fake.w3x"
            archive_offset = 0
            _data = payload

            def list_files(self) -> list[str]:
                return []

            def block_index_of(self, name: str) -> int | None:
                return None

            def iter_blocks(self) -> tuple[tuple[int, FakeBlock], ...]:
                return ((0, plain),)

            def read_block_anon(self, block: FakeBlock) -> bytes:
                return payload

        # Then: no encrypted-script report is written.
        with tempfile.TemporaryDirectory() as out:
            write_unknown_files_from_archive(Archive(), out)  # pyright: ignore[reportArgumentType]
            self.assertFalse(os.path.exists(os.path.join(out, "加密脚本检测.txt")))

    def test_audit_warns_on_stub_primary_script(self) -> None:
        # Given: a stub war3map.j with function shells only (KKWE-protected maps).
        md = MapData(path="x.w3x", name="x")
        md.scripts = {
            "war3map.j": (
                "function config takes nothing returns nothing\n"
                "endfunction\n"
                "function main takes nothing returns nothing\n"
                "endfunction\n"
            )
        }

        # When: the audit report is built.
        report = build_audit_report(md)

        # Then: the stub condition is warned next to the primary-script info.
        item = report.by_code["script.stub"]
        self.assertEqual(item.severity, AuditSeverity.WARNING)
        self.assertIn("存根", item.title)
        self.assertIn("KKWE", item.detail)

    def test_audit_keeps_live_script_free_of_stub_warning(self) -> None:
        # Given: a real script carrying executable statements.
        md = MapData(path="y.w3x", name="y")
        md.scripts = {"war3map.j": "call InitGlobals()\nset udg_x = 1\n"}

        # Then: no stub warning appears.
        self.assertNotIn("script.stub", build_audit_report(md).by_code)


if __name__ == "__main__":
    unittest.main()
