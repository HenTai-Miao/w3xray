"""资源依赖图：从对象字段、脚本和内部文件清单分析素材引用。"""
import unittest

from w3xtool.api import GameObject, MapData
from w3xtool.resources import build_resource_report


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
        self.assertIn("replaceabletextures\\commandbuttons\\btnhero.blp", report.by_path)
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
        md.objects = {"单位": [_obj("H001", fields=[("模型", "war3mapImported\\used.mdx")])]}
        md.all_files = [
            "war3mapImported\\used.mdx",
            "war3mapImported\\unused.blp",
            "war3map.w3i",
        ]

        # When: the resource report is built.
        report = build_resource_report(md)

        # Then: only the unused asset is reported as unreferenced.
        self.assertEqual(report.unreferenced_assets, ("war3mapimported\\unused.blp",))


if __name__ == "__main__":
    unittest.main()
