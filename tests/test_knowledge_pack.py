"""地图资料包导出：集中整理 ID、文本、图标、资源与配置摘要。"""

import hashlib
import os
import tempfile
import unittest
import zlib

from w3xtool.api import GameObject, MapData
from w3xtool.imp import ImportEntry, ImportSummary
from w3xtool.knowledge_pack import write_knowledge_pack
from w3xtool.wtg import TriggerCategory, TriggerHeader, TriggerTreeSummary, TriggerVariable


class KnowledgePackTest(unittest.TestCase):
    def test_pack_exports_resource_file_bodies_when_source_is_readable(self):
        # Given: a readable source folder mirroring map-internal file paths.
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as out:
            os.makedirs(os.path.join(source, "war3mapImported"), exist_ok=True)
            with open(os.path.join(source, "war3mapImported", "Hero.mdx"), "wb") as f:
                f.write(b"MDLXhero")
            with open(os.path.join(source, "war3map.wts"), "wb") as f:
                f.write("STRING 1\n{\n测试\n}\n".encode("utf-8"))

            md = MapData(path=source, name="资源本体图")
            md.all_files = [
                "war3mapImported\\Hero.mdx",
                "war3map.wts",
                "..\\escape.blp",
            ]

            # When: the user exports the consolidated knowledge pack.
            write_knowledge_pack(md, out)

            # Then: resource/config bodies are copied with a manifest and safe paths.
            with open(
                os.path.join(out, "资源", "素材文件", "war3mapimported", "hero.mdx"),
                "rb",
            ) as f:
                self.assertEqual(f.read(), b"MDLXhero")
            with open(os.path.join(out, "资源", "素材文件", "war3map.wts"), "rb") as f:
                self.assertIn("测试".encode("utf-8"), f.read())
            with open(os.path.join(out, "资源", "素材文件_manifest.tsv"), encoding="utf-8") as f:
                manifest = f.read()
            self.assertIn(
                "war3mapimported\\hero.mdx\t素材文件/war3mapimported/hero.mdx\t8\t已导出",
                manifest,
            )
            self.assertIn("..\\escape.blp\t\t0\t路径不安全", manifest)
            self.assertFalse(os.path.exists(os.path.join(out, "escape.blp")))

    def test_pack_exports_readable_map_file_identity_hashes(self):
        # Given: the original map file is readable from disk.
        raw = b"HM3W-map-identity"
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as out:
            map_path = os.path.join(source, "identity.w3x")
            with open(map_path, "wb") as f:
                f.write(raw)
            expected_crc = f"{zlib.crc32(raw) & 0xFFFFFFFF:08x}"
            expected_sha1 = hashlib.sha1(raw).hexdigest()
            md = MapData(path=map_path, name="身份图")

            # When: the knowledge pack is exported.
            write_knowledge_pack(md, out)

            # Then: map identity rows include stable file hashes for map-ID checks.
            with open(os.path.join(out, "地图与对象ID索引.tsv"), encoding="utf-8") as f:
                id_index = f.read()
            self.assertIn(f"地图\t文件字节\t{len(raw)}", id_index)
            self.assertIn(f"地图\tCRC32\t{expected_crc}", id_index)
            self.assertIn(f"地图\tSHA1\t{expected_sha1}", id_index)
            with open(os.path.join(out, "资料包审计.txt"), encoding="utf-8") as f:
                audit = f.read()
            self.assertIn(
                f"地图身份\t文件可读\t字节 {len(raw)}\tCRC32 {expected_crc}",
                audit,
            )

    def test_pack_exports_trigger_tree_and_variable_tables(self):
        # Given: the map has parsed WTG trigger metadata.
        md = MapData(path="x.w3x", name="触发图")
        md.trigger_summary = TriggerTreeSummary(
            version=7,
            is_reforged=False,
            category_count=1,
            variable_count=2,
            trigger_count=2,
            comment_count=1,
            script_count=1,
            categories=(TriggerCategory(42, "系统", False),),
            variables=(
                TriggerVariable("Count", "integer", 42, False, 1, True, "5"),
                TriggerVariable("Players", "player", 42, True, 12, False, ""),
            ),
            triggers=(
                TriggerHeader("初始化", "开局", False, True, False, False, True, 42, 0),
                TriggerHeader("脚本块", "", False, False, True, True, False, 42, 0),
            ),
            has_unexpanded_functions=True,
        )

        # When: the knowledge pack is exported.
        with tempfile.TemporaryDirectory() as out:
            write_knowledge_pack(md, out)

            # Then: trigger folder/name/state and global variables are exported as TSV.
            with open(os.path.join(out, "触发器树.tsv"), encoding="utf-8") as f:
                triggers = f.read()
            self.assertIn("类型\tID\t父ID\t名称\t分类\t启用\t自定义脚本\t初始关闭\t初始化运行\t说明", triggers)
            self.assertIn("分类\t42\t0\t系统", triggers)
            self.assertIn("触发器\t\t42\t初始化\t系统\t是\t否\t否\t是\t开局", triggers)
            self.assertIn("触发器\t\t42\t脚本块\t系统\t否\t是\t是\t否", triggers)
            self.assertIn("ECA 函数体未展开", triggers)
            with open(os.path.join(out, "触发变量.tsv"), encoding="utf-8") as f:
                variables = f.read()
            self.assertIn("名称\t类型\t分类\t数组\t数组大小\t初始化\t初始值", variables)
            self.assertIn("Count\tinteger\t系统\t否\t1\t是\t5", variables)
            self.assertIn("Players\tplayer\t系统\t是\t12\t否", variables)

    def test_pack_writes_map_info_ids_text_icons_and_resources(self):
        # Given: a parsed map with object text, icons, scripts, and internal assets.
        md = MapData(path="x.w3x", name="测试图")
        md.objects = {
            "单位": [
                GameObject(
                    category="单位",
                    ext="w3u",
                    obj_id="H001",
                    base_id="Hpal",
                    name="圣骑士",
                    is_custom=True,
                    fields=[
                        ("提示", "召唤圣骑士"),
                        ("说明", "模型 war3mapImported\\Hero.mdx"),
                    ],
                    icon="ReplaceableTextures\\CommandButtons\\BTNHero.blp",
                )
            ],
            "技能": [
                GameObject(
                    category="技能",
                    ext="w3a",
                    obj_id="A001",
                    base_id="AHhb",
                    name="治疗术",
                    is_custom=True,
                    fields=[
                        ("提示", "短提示"),
                        ("扩展提示", "长说明"),
                    ],
                )
            ],
        }
        md.scripts = {"war3map.j": 'call PlaySound("war3mapImported\\\\voice.mp3")'}
        md.scripts["war3map.j"] += "\ncall ChooseRandomItemBJ(3)"
        md.scripts["save.j"] = "\n".join((
            'set udg_cache = InitGameCache("AnimeSave.w3v")',
            'call StoreInteger(udg_cache, "hero", "level", 1)',
            'call PreloadGenEnd("save\\hero.txt")',
            "call UnitAddAbility(u, 'A001')",
        ))
        md.scripts["war3map.wts"] = "STRING 7\n{\n界面提示\n}\n"
        md.scripts["trigger.j"] = 'call BJDebugMsg("TRIGSTR_007")'
        md.all_files = [
            "war3mapImported\\Hero.mdx",
            "war3mapImported\\unused.blp",
            "war3map.w3i",
            "war3map.w3u",
            "war3map.wts",
            "testconfig.wgc",
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

        # When: the user exports the consolidated knowledge pack.
        with tempfile.TemporaryDirectory() as out:
            written = write_knowledge_pack(md, out)

            # Then: each high-value investigation surface is available in one folder.
            self.assertGreaterEqual(written, 5)
            with open(os.path.join(out, "地图信息.txt"), encoding="utf-8") as f:
                self.assertIn("测试图", f.read())
            with open(os.path.join(out, "对象ID", "单位.tsv"), encoding="utf-8") as f:
                ids = f.read()
            self.assertIn("H001", ids)
            self.assertIn("圣骑士", ids)
            with open(os.path.join(out, "对象文本与图标.tsv"), encoding="utf-8") as f:
                text_icons = f.read()
            self.assertIn("BTNHero.blp", text_icons)
            self.assertIn("召唤圣骑士", text_icons)
            with open(os.path.join(out, "UI文本_TRIGSTR.tsv"), encoding="utf-8") as f:
                ui_strings = f.read()
            self.assertIn("TRIGSTR_007\t界面提示", ui_strings)
            with open(os.path.join(out, "UI文本引用.tsv"), encoding="utf-8") as f:
                ui_refs = f.read()
            self.assertIn("trigger.j\t1\tTRIGSTR_007\t界面提示", ui_refs)
            with open(os.path.join(out, "脚本可读文本", "trigger.j"), encoding="utf-8") as f:
                readable_script = f.read()
            self.assertIn('call BJDebugMsg("界面提示")', readable_script)
            with open(os.path.join(out, "资源", "资源引用.tsv"), encoding="utf-8") as f:
                resources = f.read()
            self.assertIn("war3mapimported\\hero.mdx", resources)
            self.assertIn("对象 H001", resources)
            with open(os.path.join(out, "资源", "未引用素材.txt"), encoding="utf-8") as f:
                self.assertIn("war3mapimported\\unused.blp", f.read())
            with open(os.path.join(out, "资源", "资源资产索引.tsv"), encoding="utf-8") as f:
                asset_index = f.read()
            self.assertIn("war3map.wts\tUI/文本\t存在/未引用", asset_index)
            self.assertIn("war3mapimported\\hero.mdx\t模型\t存在/已引用", asset_index)
            self.assertIn("replaceabletextures\\missing.blp\t图像\t导入缺失", asset_index)
            with open(os.path.join(out, "盒子兼容ID", "技能ID.txt"), encoding="utf-8") as f:
                box_ids = f.read()
            self.assertIn("ID：A001\n名字：治疗术\n描述：长说明", box_ids)
            with open(os.path.join(out, "存档读写线索.tsv"), encoding="utf-8") as f:
                save_rows = f.read()
            self.assertIn("AnimeSave.w3v", save_rows)
            self.assertIn("save\\hero.txt", save_rows)
            with open(os.path.join(out, "配置格式索引.txt"), encoding="utf-8") as f:
                config_index = f.read()
            self.assertIn("war3map.w3i", config_index)
            self.assertIn("testconfig.wgc", config_index)
            with open(os.path.join(out, "地图与对象ID索引.tsv"), encoding="utf-8") as f:
                id_index = f.read()
            self.assertIn("地图\t测试图\tx.w3x", id_index)
            self.assertIn("地图\t内部文件数\t6", id_index)
            self.assertIn("地图\t对象总数\t2", id_index)
            self.assertIn("对象\t技能\tA001", id_index)
            with open(os.path.join(out, "资料包审计.txt"), encoding="utf-8") as f:
                audit = f.read()
            self.assertIn("资料包审计", audit)
            self.assertIn("UI文本\t字符串 1\t引用 1\t未解析 0", audit)
            self.assertIn("资源资产\t总数", audit)
            self.assertIn("配置格式\t已知文件 4", audit)
            self.assertIn("存档/ID\t线索 4", audit)
            self.assertIn("地图/对象ID\t对象 2\t分类 2", audit)
            with open(os.path.join(out, "提取完整性.txt"), encoding="utf-8") as f:
                completeness = f.read()
            self.assertIn("命名文件：6", completeness)
            self.assertIn("源文件不可读", completeness)
            with open(os.path.join(out, "脚本机制线索.txt"), encoding="utf-8") as f:
                mechanics = f.read()
            self.assertIn("随机物品池", mechanics)
            self.assertIn("不直接给出固定 4cc", mechanics)


if __name__ == "__main__":
    unittest.main()
