"""资源依赖图：从对象字段、脚本和内部文件清单分析素材引用。"""

import unittest

from gametool.api import GameObject, MapData
from gametool.resources import build_resource_report


def _obj(obj_id, fields=None, icon=""):
    return GameObject(
        category="单位",
        ext="w3u",
        obj_id=obj_id,
        base_id=obj_id,
        name=obj_id,
        is_custom=True,
        fields=fields or [],
        icon=icon,
    )


class ResourceReportTest(unittest.TestCase):
    def test_context_text_matches_complete_inventory_path(self):
        for path, text in (
            (r"war3mapimported\hero.mdx", r"模型 war3mapImported\Hero.mdx"),
            (r"素材\巨龙 第二版.mdx", r"模型 素材\巨龙 第二版.mdx"),
            (r"模型 素材\巨龙 第二版.mdx", r"模型 素材\巨龙 第二版.mdx"),
        ):
            with self.subTest(path=path):
                md = MapData(path="x.w3x", name="x")
                md.objects = {"单位": [_obj("H001", fields=[("说明", text)])]}
                md.all_files = [path]
                report = build_resource_report(md)
                self.assertEqual(tuple(report.by_path), (path,))
                self.assertEqual(report.unreferenced_assets, ())

    def test_known_path_does_not_hide_unlisted_resource_list_members(self):
        md = MapData(path="x.w3x", name="x")
        md.objects = {
            "单位": [_obj("H001", fields=[("特效", "known.mdx,素材\\missing.mdx")])]
        }
        md.all_files = ["known.mdx"]
        self.assertEqual(
            tuple(build_resource_report(md).by_path),
            ("known.mdx", "素材\\missing.mdx"),
        )

    def test_inventory_basename_does_not_steal_a_full_directory_path(self):
        md = MapData(path="x.w3x", name="x")
        md.objects = {"单位": [_obj("H001", fields=[("模型", "folder\\hero.mdx")])]}
        md.all_files = ["hero.mdx", "folder\\hero.mdx"]
        report = build_resource_report(md)
        self.assertEqual(tuple(report.by_path), ("folder\\hero.mdx",))
        self.assertEqual(report.unreferenced_assets, ("hero.mdx",))

    def test_inventory_basename_does_not_replace_complete_resource_values(self):
        for label, path in (
            ("模型", "missing hero.mdx"),
            ("模型", "(new)hero.mdx"),
            ("模型", "new;hero.mdx"),
            ("UnknownAssetField", "missing hero.mdx"),
        ):
            with self.subTest(label=label, path=path):
                md = MapData(path="x.w3x", name="x")
                md.objects = {"单位": [_obj("H001", fields=[(label, path)])]}
                md.all_files = ["hero.mdx"]
                report = build_resource_report(md)
                self.assertEqual(tuple(report.by_path), (path,))
                self.assertEqual(report.unreferenced_assets, ("hero.mdx",))

    def test_complete_unicode_object_path_is_not_reduced_to_ascii_suffix(self):
        path = "素材\\巨龙(二);完整模型.mdx"
        md = MapData(path="x.w3x", name="x")
        md.objects = {"单位": [_obj("H001", fields=[("模型", path)])]}
        md.all_files = [path]
        report = build_resource_report(md)
        self.assertEqual(tuple(report.by_path), (path,))
        self.assertEqual(report.unreferenced_assets, ())

    def test_object_resource_lists_keep_independent_paths(self):
        for paths in (
            ("first.mdx", "second.mdx"),
            ("first.mdx", "素材\\二.mdx"),
            ("素材\\火焰.mdx", "素材\\冰霜.mdx"),
        ):
            with self.subTest(paths=paths):
                md = MapData(path="x.w3x", name="x")
                md.objects = {
                    "单位": [_obj("H001", fields=[("特效", ",".join(paths))])]
                }
                md.all_files = list(paths)
                report = build_resource_report(md)
                self.assertEqual(tuple(report.by_path), tuple(sorted(paths)))
                self.assertEqual(report.unreferenced_assets, ())

    def test_comma_inside_one_complete_unicode_path_is_retained(self):
        path = "素材\\模型,第二版.MDX"
        md = MapData(path="x.w3x", name="x")
        md.objects = {"单位": [_obj("H001", fields=[("模型", path)])]}
        md.all_files = [path]
        report = build_resource_report(md)
        self.assertEqual(tuple(report.by_path), (path.lower(),))
        self.assertEqual(report.unreferenced_assets, ())

    def test_object_icon_and_model_fields_become_references(self):
        # Given: an object with icon and model paths.
        md = MapData(path="x.w3x", name="x")
        md.objects = {
            "单位": [
                _obj(
                    "H001",
                    fields=[("模型", "war3mapImported\\Hero.mdx")],
                    icon="ReplaceableTextures\\CommandButtons\\BTNHero.blp",
                )
            ]
        }

        # When: the resource report is built.
        report = build_resource_report(md)

        # Then: both resource paths are normalized and linked to the object.
        self.assertIn("war3mapimported\\hero.mdx", report.by_path)
        self.assertIn(
            "replaceabletextures\\commandbuttons\\btnhero.blp", report.by_path
        )
        node = report.by_path["war3mapimported\\hero.mdx"]
        self.assertEqual(node.refs[0].source, "对象 H001")

    def test_script_literals_become_references(self):
        # Given: a script that mentions an imported sound.
        md = MapData(path="x.w3x", name="x")
        md.scripts = {"war3map.j": r'call PlaySound("war3mapImported\\boss.mp3")'}

        # When: the resource report is built.
        report = build_resource_report(md)

        # Then: the sound literal is indexed as a script resource.
        node = report.by_path["war3mapimported\\boss.mp3"]
        self.assertEqual(node.kind, "音频")
        self.assertEqual(node.refs[0].source, "脚本 war3map.j")

    def test_unreferenced_archive_assets_are_reported(self):
        # Given: one internal asset is referenced and another is not.
        md = MapData(path="x.w3x", name="x")
        md.objects = {
            "单位": [_obj("H001", fields=[("模型", "war3mapImported\\used.mdx")])]
        }
        md.all_files = [
            "war3mapImported\\used.mdx",
            "war3mapImported\\unused.blp",
            "war3map.w3i",
        ]

        # When: the resource report is built.
        report = build_resource_report(md)

        # Then: only the unused asset is reported as unreferenced.
        self.assertEqual(report.unreferenced_assets, ("war3mapimported\\unused.blp",))

    def test_ui_image_font_and_table_paths_become_references(self):
        # Given: maps can reference UI frames, loading images, fonts, tables, and text configs.
        md = MapData(path="x.w3x", name="x")
        md.objects = {
            "单位": [
                _obj(
                    "H001",
                    fields=[
                        ("UI", "UI\\FrameDef\\AnimePanel.fdf"),
                        ("载入图", "war3mapImported\\loading.png"),
                        ("字体", "Fonts\\Title.otf"),
                    ],
                )
            ]
        }
        md.scripts = {
            "war3map.j": (
                'call Preload("war3mapImported\\\\SaveLayout.txt")\n'
                'call BlzLoadTOCFile("UI\\\\FrameDef\\\\Custom.toc")\n'
            )
        }
        md.all_files = ["war3mapImported\\ObjectData.slk"]

        # When: the resource report is built.
        report = build_resource_report(md)

        # Then: investigation resources beyond classic BLP/MDX/MP3 are indexed too.
        self.assertEqual(report.by_path["ui\\framedef\\animepanel.fdf"].kind, "UI/文本")
        self.assertEqual(report.by_path["war3mapimported\\loading.png"].kind, "图像")
        self.assertEqual(report.by_path["fonts\\title.otf"].kind, "字体")
        self.assertEqual(
            report.by_path["war3mapimported\\savelayout.txt"].kind, "UI/文本"
        )
        self.assertEqual(report.by_path["ui\\framedef\\custom.toc"].kind, "UI/文本")
        self.assertEqual(report.archive_assets, ("war3mapimported\\objectdata.slk",))

    def test_json_plist_skin_and_ai_paths_become_config_references(self):
        # Given: optimized maps may keep tool settings, UI skins, and AI scripts as text files.
        md = MapData(path="x.w3x", name="x")
        md.objects = {
            "单位": [
                _obj(
                    "H001",
                    fields=[
                        ("配置", "war3mapImported\\settings.json"),
                        ("皮肤", "UI\\Skin\\Anime.skin"),
                    ],
                )
            ]
        }
        md.scripts = {
            "war3map.j": (
                'call Preload("war3mapImported\\\\profile.plist")\n'
                'call StartMeleeAI(Player(1), "AI Scripts\\\\rush.ai")\n'
            )
        }
        md.all_files = ["war3mapImported\\settings.json", "AI Scripts\\rush.ai"]

        # When: the resource report is built.
        report = build_resource_report(md)

        # Then: these configuration-oriented paths are indexed instead of ignored.
        self.assertEqual(report.by_path["war3mapimported\\settings.json"].kind, "配置")
        self.assertEqual(report.by_path["war3mapimported\\profile.plist"].kind, "配置")
        self.assertEqual(report.by_path["ui\\skin\\anime.skin"].kind, "配置")
        self.assertEqual(report.by_path["ai scripts\\rush.ai"].kind, "AI脚本")
        self.assertEqual(
            report.archive_assets,
            ("ai scripts\\rush.ai", "war3mapimported\\settings.json"),
        )


if __name__ == "__main__":
    unittest.main()
