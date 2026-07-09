"""知识包目录清单：把用户需求面映射到导出文件。"""

import os
import tempfile
import unittest

from w3xtool.api import MapData
from w3xtool.knowledge_pack import write_knowledge_pack


class KnowledgePackManifestTest(unittest.TestCase):
    def test_pack_writes_artifact_manifest_for_investigation_surfaces(self):
        # Given: a minimal parsed map.
        md = MapData(path="x.w3x", name="目录图")

        # When: the knowledge pack is exported.
        with tempfile.TemporaryDirectory() as out:
            write_knowledge_pack(md, out)

            # Then: users can see which file covers each investigation surface.
            with open(os.path.join(out, "资料包目录.tsv"), encoding="utf-8") as f:
                manifest = f.read()
            self.assertIn("主题\t文件\t用途", manifest)
            self.assertIn("UI文本\tUI文本_TRIGSTR.tsv\tTRIGSTR 字符串表", manifest)
            self.assertIn("资源/图标\t资源/资源资产索引.tsv\t图标、模型、音频、UI/文本资源清单", manifest)
            self.assertIn("配置格式\t配置格式索引.txt\t地图、对象、触发器、AI 和文本配置格式说明", manifest)
            self.assertIn("存档/ID\t存档读写线索.tsv\tGameCache、Hashtable、Preload、同步和平台存档线索", manifest)
            self.assertIn("地图/对象ID\t地图与对象ID索引.tsv\t地图身份、对象 ID、脚本引用和未知 4cc", manifest)
            self.assertIn("地图/对象ID\t对象ID使用摘要.tsv\t按 ID 汇总脚本、存档、对象字段和预放置引用次数", manifest)
            self.assertIn("脚本\t脚本函数索引.tsv\t函数范围、调用关系、机制和对象码", manifest)
            self.assertIn("脚本\t脚本调用参数索引.tsv\t脚本每次调用的参数、存档键、资源和对象码", manifest)
            self.assertIn("脚本\t脚本全局变量索引.tsv\t脚本 globals 变量、初值和对象码", manifest)
            self.assertIn("脚本\t脚本赋值索引.tsv\t脚本 set 赋值、状态变量和对象码", manifest)
            self.assertIn("脚本\t脚本变量使用索引.tsv\t脚本 udg_/gg_ 全局变量读写位置", manifest)
            self.assertIn("脚本\t脚本对象码出现索引.tsv\t脚本对象码逐次出现位置和上下文", manifest)
            self.assertIn("脚本\t脚本触发注册索引.tsv\t脚本事件、动作、条件和计时器入口", manifest)
            self.assertIn("脚本\t脚本条件分支索引.tsv\t脚本 if/elseif 条件里的存档、变量和对象码", manifest)
            self.assertIn("脚本\t脚本循环索引.tsv\t脚本 loop/exitwhen/for/while 循环和退出条件", manifest)
            self.assertIn("脚本\t脚本返回值索引.tsv\t脚本 return 返回的存档、变量和对象码", manifest)
            self.assertIn("脚本\t脚本局部变量索引.tsv\t脚本函数内 local 变量、初值和对象码", manifest)
            self.assertIn("脚本\t脚本字符串索引.tsv\t脚本字符串字面量、用途和函数上下文", manifest)
            self.assertIn("触发器\t触发器树.tsv\tWTG 分类、触发器头和启用状态", manifest)
            self.assertIn("提取完整性\t提取完整性.txt\t命名文件覆盖率和无名块提示", manifest)
            self.assertIn("总览\t需求覆盖.tsv\t用户原始需求到资料包产物的覆盖矩阵", manifest)
            self.assertIn("预放置\t预放置单位.tsv\twar3mapUnits.doo 单位、物品栏、技能和坐标", manifest)
            self.assertIn("预放置\t预放置装饰物.tsv\twar3map.doo 装饰物/可破坏物、缩放和掉落", manifest)

    def test_pack_writes_requirement_coverage_matrix(self):
        # Given: a minimal parsed map.
        md = MapData(path="x.w3x", name="需求图")

        # When: the knowledge pack is exported.
        with tempfile.TemporaryDirectory() as out:
            write_knowledge_pack(md, out)

            # Then: generic capabilities remain listed but empty-map rows are downgraded.
            with open(os.path.join(out, "需求覆盖.tsv"), encoding="utf-8") as f:
                coverage = f.read()
            self.assertIn("需求\t状态\t主要产物\t辅助产物\t说明", coverage)
            self.assertIn("提取/整理 UI 文本\t未发现数据\tUI文本_TRIGSTR.tsv; UI文本引用.tsv", coverage)
            self.assertIn("提取/整理图标和资源\t未发现数据\t资源/资源资产索引.tsv", coverage)
            self.assertIn("整理配置文件格式\t未发现数据\t配置格式索引.txt", coverage)
            self.assertIn("分析本地存档读写\t未发现数据\t存档读写线索.tsv", coverage)
            self.assertIn("分析地图 ID\t已覆盖（静态身份）\t地图与对象ID索引.tsv", coverage)
            self.assertIn(
                "分析物品/技能/单位 ID\t未发现数据\t地图与对象ID索引.tsv; 对象ID使用摘要.tsv; 对象ID/",
                coverage,
            )
            self.assertIn("分析脚本循环\t未发现数据\t脚本循环索引.tsv", coverage)
            self.assertIn("分析脚本返回值\t未发现数据\t脚本返回值索引.tsv", coverage)
            self.assertIn("分析脚本局部变量\t未发现数据\t脚本局部变量索引.tsv", coverage)
            self.assertIn("分析脚本调用参数\t未发现数据\t脚本调用参数索引.tsv", coverage)


if __name__ == "__main__":
    unittest.main()
