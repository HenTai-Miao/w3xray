"""资源资产清单：把 UI 文本、导入表、素材引用和缺失状态汇总。"""

import unittest

from w3xtool.api import GameObject, MapData
from w3xtool.imp import ImportEntry, ImportSummary
from w3xtool.resource_inventory import (
    build_resource_inventory,
    format_resource_inventory_tsv,
)


def _unit_with_resources() -> GameObject:
    return GameObject(
        category="单位",
        ext="w3u",
        obj_id="H001",
        base_id="Hpal",
        name="圣骑士",
        is_custom=True,
        fields=[("模型", "war3mapImported\\Hero.mdx")],
        icon="ReplaceableTextures\\CommandButtons\\BTNHero.blp",
    )


class ResourceInventoryTest(unittest.TestCase):
    def test_inventory_combines_archive_import_table_and_references(self):
        # Given: a map with internal config files, imported assets, and object refs.
        md = MapData(path="x.w3x", name="x")
        md.objects = {"单位": [_unit_with_resources()]}
        md.all_files = [
            "war3map.wts",
            "war3map.w3u",
            "war3mapImported\\Hero.mdx",
            "war3mapImported\\unused.blp",
        ]
        md.import_summary = ImportSummary(
            version=1,
            entries=(
                ImportEntry(path="Hero.mdx", flag=8),
                ImportEntry(path="ReplaceableTextures\\Missing.blp", flag=13),
            ),
            resolved_paths=("war3mapImported\\Hero.mdx",),
            missing_paths=("ReplaceableTextures\\Missing.blp",),
        )

        # When: the resource inventory is built.
        inventory = build_resource_inventory(md)

        # Then: each path has a practical kind, status, and source list.
        by_path = {item.path: item for item in inventory.items}
        self.assertEqual(by_path["war3map.wts"].kind, "UI/文本")
        self.assertEqual(by_path["war3map.wts"].status, "存在/未引用")
        self.assertEqual(by_path["war3mapimported\\hero.mdx"].kind, "模型")
        self.assertEqual(by_path["war3mapimported\\hero.mdx"].status, "存在/已引用")
        self.assertIn("导入表 标准路径", by_path["war3mapimported\\hero.mdx"].sources)
        self.assertIn("对象 H001", by_path["war3mapimported\\hero.mdx"].sources)
        self.assertEqual(
            by_path["replaceabletextures\\commandbuttons\\btnhero.blp"].kind,
            "图标",
        )
        self.assertEqual(
            by_path["replaceabletextures\\commandbuttons\\btnhero.blp"].status,
            "仅引用",
        )
        self.assertEqual(by_path["replaceabletextures\\missing.blp"].status, "导入缺失")

    def test_inventory_formats_tsv_for_knowledge_pack(self):
        # Given: an inventory with one UI file.
        md = MapData(path="x.w3x", name="x")
        md.all_files = ["war3map.wts"]

        # When: the inventory is formatted as TSV.
        text = format_resource_inventory_tsv(build_resource_inventory(md))

        # Then: the export is easy to diff and spreadsheet-friendly.
        self.assertIn("路径\t类型\t状态\t来源", text)
        self.assertIn("war3map.wts\tUI/文本\t存在/未引用\t内部文件", text)

    def test_inventory_treats_toc_as_existing_ui_text_resource(self):
        # Given: a map has a custom UI TOC file and script code that loads it.
        md = MapData(path="x.w3x", name="x")
        md.all_files = ["UI\\FrameDef\\Custom.toc"]
        md.scripts = {"war3map.j": 'call BlzLoadTOCFile("UI\\\\FrameDef\\\\Custom.toc")'}

        # When: the resource inventory is built.
        inventory = build_resource_inventory(md)

        # Then: the TOC is classified as a present UI text/config resource.
        by_path = {item.path: item for item in inventory.items}
        self.assertEqual(by_path["ui\\framedef\\custom.toc"].kind, "UI/文本")
        self.assertEqual(by_path["ui\\framedef\\custom.toc"].status, "存在/已引用")
        self.assertIn("内部文件", by_path["ui\\framedef\\custom.toc"].sources)

    def test_inventory_classifies_extra_config_and_ai_assets(self):
        # Given: a map includes text configuration, skin, plist, and AI script files.
        md = MapData(path="x.w3x", name="x")
        md.all_files = [
            "war3mapImported\\settings.json",
            "war3mapImported\\profile.plist",
            "UI\\Skin\\Anime.skin",
            "AI Scripts\\rush.ai",
        ]
        md.scripts = {
            "war3map.j": (
                'call Preload("war3mapImported\\\\settings.json")\n'
                'call StartMeleeAI(Player(1), "AI Scripts\\\\rush.ai")\n'
            )
        }

        # When: the inventory is built.
        inventory = build_resource_inventory(md)

        # Then: configuration and AI bodies are visible to the knowledge pack.
        by_path = {item.path: item for item in inventory.items}
        self.assertEqual(by_path["war3mapimported\\settings.json"].kind, "配置")
        self.assertEqual(by_path["war3mapimported\\settings.json"].status, "存在/已引用")
        self.assertEqual(by_path["war3mapimported\\profile.plist"].kind, "配置")
        self.assertEqual(by_path["ui\\skin\\anime.skin"].kind, "配置")
        self.assertEqual(by_path["ai scripts\\rush.ai"].kind, "AI脚本")
        self.assertEqual(by_path["ai scripts\\rush.ai"].status, "存在/已引用")


if __name__ == "__main__":
    unittest.main()
