"""地图提取完整性诊断。"""

import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from w3xtool.api import MapData
from w3xtool.archive_diagnostics import ArchiveDiagnosisKind
from w3xtool.extraction_completeness import (
    build_extraction_completeness_from_archive,
    build_extraction_completeness_report,
    format_extraction_completeness_report,
)
from w3xtool.mpq import FLAG_COMPRESS, FLAG_ENCRYPTED, FLAG_EXISTS


@dataclass(frozen=True, slots=True)
class FakeBlock:
    flags: int


class FakeArchive:
    path = "x.w3x"

    def __init__(self) -> None:
        self._blocks = (
            FakeBlock(FLAG_EXISTS),
            FakeBlock(FLAG_EXISTS | FLAG_ENCRYPTED | FLAG_COMPRESS),
            FakeBlock(FLAG_EXISTS),
            FakeBlock(FLAG_EXISTS | FLAG_ENCRYPTED | FLAG_COMPRESS),
        )

    def list_files(self) -> list[str]:
        return ["war3map.j", "war3mapImported\\Hero.mdx"]

    def has_file(self, name: str) -> bool:
        return name in {"(listfile)", "war3map.imp"}

    def iter_blocks(self) -> tuple[tuple[int, FakeBlock], ...]:
        return tuple(enumerate(self._blocks))

    def block_index_of(self, name: str) -> int | None:
        return {"war3map.j": 0, "war3mapImported\\Hero.mdx": 2}.get(name)

    def recover_block_key(self, block: FakeBlock) -> int | None:
        if block is self._blocks[1]:
            return 123
        return None


class ProtectedArchive:
    path = "protected.w3x"

    def __init__(self) -> None:
        self._blocks = tuple(
            FakeBlock(FLAG_EXISTS | FLAG_ENCRYPTED | FLAG_COMPRESS)
            for _index in range(12)
        )

    def list_files(self) -> list[str]:
        return ["war3map.j"]

    def has_file(self, name: str) -> bool:
        return False

    def iter_blocks(self) -> tuple[tuple[int, FakeBlock], ...]:
        return tuple(enumerate(self._blocks))

    def block_index_of(self, name: str) -> int | None:
        if name == "war3map.j":
            return 0
        return None

    def recover_block_key(self, block: FakeBlock) -> int | None:
        return None


class ExtractionCompletenessTest(unittest.TestCase):
    def test_report_counts_named_unknown_and_raw_blocks(self) -> None:
        # Given: an archive with two named blocks, one recoverable anonymous block, and one raw fallback.
        md = MapData(path="x.w3x", name="完整性图")
        archive = FakeArchive()

        # When: extraction completeness is summarized from the archive tables.
        report = build_extraction_completeness_from_archive(md, archive)
        text = format_extraction_completeness_report(report)

        # Then: the report explains the real extraction surface instead of only listing filenames.
        self.assertEqual(report.named_file_count, 2)
        self.assertEqual(report.block_count, 4)
        self.assertEqual(report.named_block_count, 2)
        self.assertEqual(report.anonymous_block_count, 2)
        self.assertEqual(report.recoverable_anonymous_count, 1)
        self.assertEqual(report.raw_fallback_count, 1)
        self.assertIn("命名覆盖：2/4 (50.0%)", text)
        self.assertIn("Unknown 可解包：1", text)
        self.assertIn("UnknownRaw 兜底：1", text)
        self.assertIn("(listfile)：存在", text)
        self.assertIn("war3map.imp/war3campaign.imp：存在", text)

    def test_report_falls_back_to_loaded_file_list_when_source_is_unreadable(self) -> None:
        # Given: parsed map data whose original archive is not available.
        md = MapData(path="/missing/map.w3x", name="离线图")
        md.all_files = ["war3map.j", "war3map.w3i"]

        # When: the completeness report is built without a readable MPQ source.
        report = build_extraction_completeness_report(md)
        text = format_extraction_completeness_report(report)

        # Then: users still see what was identified and why block coverage cannot be calculated.
        self.assertFalse(report.source_readable)
        self.assertEqual(report.named_file_count, 2)
        self.assertIsNone(report.block_count)
        self.assertIn("命名文件：2", text)
        self.assertIn("源文件不可读", text)

    def test_missing_source_is_diagnosed_without_constructing_archive(self) -> None:
        # Given: map data retaining a non-existent original source path.
        md = MapData(path="/missing/map.w3x", name="离线图")

        # When: completeness diagnoses the unavailable source.
        with patch(
            "w3xtool.extraction_completeness.MPQArchive",
            side_effect=AssertionError("must not construct MPQArchive"),
        ) as archive_type:
            report = build_extraction_completeness_report(md)

        # Then: the bounded helper classifies it before MPQArchive fallback can copy it.
        archive_type.assert_not_called()
        self.assertEqual(report.archive_diagnosis_kind, ArchiveDiagnosisKind.MISSING.value)

    def test_report_reuses_typed_archive_diagnosis_for_unopened_source(self) -> None:
        # Given: an existing source file that has no MPQ header.
        with self.subTest("no-header"):
            from tempfile import TemporaryDirectory

            with TemporaryDirectory() as tmp:
                path = Path(tmp) / "not-mpq.w3x"
                path.write_bytes(b"plain data")
                md = MapData(path=str(path), name="损坏图")

                # When: completeness cannot open the source archive.
                report = build_extraction_completeness_report(md)

        # Then: the existing diagnosis-kind data flow carries the typed result.
        self.assertEqual(report.archive_diagnosis_kind, ArchiveDiagnosisKind.NO_HEADER.value)
        self.assertTrue(any("MPQ 头" in warning for warning in report.warnings))

    def test_report_flags_probable_data_level_protection_without_bypassing(self) -> None:
        # Given: a map whose anonymous encrypted blocks cannot be recovered statically.
        md = MapData(path="protected.w3x", name="保护图")
        archive = ProtectedArchive()

        # When: extraction completeness is summarized.
        report = build_extraction_completeness_from_archive(md, archive)
        text = format_extraction_completeness_report(report)

        # Then: the report explains the protection boundary instead of implying a parser bug.
        self.assertEqual(report.raw_fallback_count, 11)
        self.assertTrue(any("数据级加密" in warning for warning in report.warnings))
        self.assertIn("不执行运行时内存 dump", text)


if __name__ == "__main__":
    unittest.main()
