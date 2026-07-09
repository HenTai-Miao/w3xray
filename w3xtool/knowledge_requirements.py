"""User-request coverage matrix for knowledge-pack artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, TYPE_CHECKING

from .external_listfile import ExternalListfileReport
from .knowledge_requirement_dynamic import build_dynamic_rows, evaluate_requirement_rows

if TYPE_CHECKING:
    from .api import MapData


@dataclass(frozen=True, slots=True)
class RequirementCoverage:
    request: str
    status: str
    primary: tuple[str, ...]
    secondary: tuple[str, ...]
    note: str


@dataclass(frozen=True, slots=True)
class ExtractionCapabilities:
    game_data_kind: str = "missing"
    has_trigger_schema: bool = False
    has_trigger_strings: bool = False
    external_listfile: ExternalListfileReport | None = None
    archive_diagnosis_kind: str = ""


_ROWS: Final[tuple[RequirementCoverage, ...]] = (
    RequirementCoverage(
        "提取/整理 UI 文本",
        "已覆盖（静态）",
        ("UI文本_TRIGSTR.tsv", "UI文本引用.tsv"),
        ("脚本字符串索引.tsv", "脚本可读文本/", "对象文本与图标.tsv"),
        "还原 WTS/TRIGSTR，并列出脚本和对象字段引用。",
    ),
    RequirementCoverage(
        "提取/整理图标和资源",
        "已覆盖（静态）",
        ("资源/资源资产索引.tsv",),
        ("脚本字符串索引.tsv", "资源/资源引用.tsv", "资源/资源内容引用.tsv", "资源/素材文件_manifest.tsv", "对象文本与图标.tsv"),
        "按图像、模型、音频、UI/文本和配置分类，能复制可读本体，并从文本配置本体继续扫描二级资源路径。",
    ),
    RequirementCoverage(
        "整理配置文件格式",
        "已覆盖（静态）",
        ("配置格式索引.txt",),
        ("内部文件清单.txt", "资源/素材文件_manifest.tsv"),
        "列出地图、对象、触发器、AI、文本和扩展配置文件。",
    ),
    RequirementCoverage(
        "分析本地存档读写",
        "已覆盖（静态线索）",
        ("存档读写线索.tsv",),
        (
            "脚本调用清单.tsv",
            "脚本函数索引.tsv",
            "脚本全局变量索引.tsv",
            "脚本赋值索引.tsv",
            "脚本变量使用索引.tsv",
            "脚本对象码出现索引.tsv",
            "脚本触发注册索引.tsv",
            "脚本条件分支索引.tsv",
            "脚本循环索引.tsv",
            "脚本返回值索引.tsv",
            "脚本局部变量索引.tsv",
            "脚本调用参数索引.tsv",
            "脚本字符串索引.tsv",
            "脚本可读文本/",
            "地图与对象ID索引.tsv",
        ),
        "识别 GameCache、Hashtable、Preload、同步和常见平台存档 API 调用。",
    ),
    RequirementCoverage(
        "分析地图 ID",
        "已覆盖（静态身份）",
        ("地图与对象ID索引.tsv",),
        ("地图信息.txt", "资料包审计.txt"),
        "汇总地图名、路径、内部文件数、对象总数以及可读文件的 CRC32/SHA1。",
    ),
    RequirementCoverage(
        "分析物品/技能/单位 ID",
        "已覆盖（静态引用）",
        ("地图与对象ID索引.tsv", "对象ID使用摘要.tsv", "对象ID/"),
        (
            "脚本调用清单.tsv",
            "脚本函数索引.tsv",
            "脚本全局变量索引.tsv",
            "脚本赋值索引.tsv",
            "脚本变量使用索引.tsv",
            "脚本对象码出现索引.tsv",
            "脚本循环索引.tsv",
            "脚本返回值索引.tsv",
            "脚本局部变量索引.tsv",
            "脚本调用参数索引.tsv",
            "盒子兼容ID/",
            "对象文本与图标.tsv",
            "预放置单位.tsv",
            "预放置装饰物.tsv",
            "存档读写线索.tsv",
        ),
        "列对象表 ID、十进制值、名称、基础 ID、脚本行号和未知 4cc。",
    ),
    RequirementCoverage(
        "分析脚本对象码出现位置",
        "已覆盖（静态）",
        ("脚本对象码出现索引.tsv",),
        ("脚本函数索引.tsv", "脚本调用清单.tsv", "对象ID使用摘要.tsv"),
        "逐次列出脚本 rawcode 的来源行、函数、调用/赋值上下文、分类和对象名。",
    ),
    RequirementCoverage(
        "分析脚本触发/事件入口",
        "已覆盖（静态）",
        ("脚本触发注册索引.tsv",),
        ("触发器树.tsv", "脚本函数索引.tsv", "脚本调用清单.tsv"),
        "列出 TriggerRegister、TriggerAddAction/Condition 和 TimerStart 的事件入口与处理函数。",
    ),
    RequirementCoverage(
        "分析脚本条件分支",
        "已覆盖（静态）",
        ("脚本条件分支索引.tsv",),
        ("脚本变量使用索引.tsv", "脚本对象码出现索引.tsv", "存档读写线索.tsv"),
        "列出 if/elseif 条件里的存档调用、状态变量、字符串和对象码。",
    ),
    RequirementCoverage(
        "分析脚本循环",
        "已覆盖（静态）",
        ("脚本循环索引.tsv",),
        ("脚本函数索引.tsv", "脚本条件分支索引.tsv", "脚本变量使用索引.tsv", "脚本对象码出现索引.tsv"),
        "列出 loop/exitwhen/for/while/repeat/until 循环和退出条件里的存档、变量与对象码。",
    ),
    RequirementCoverage(
        "分析脚本返回值",
        "已覆盖（静态）",
        ("脚本返回值索引.tsv",),
        ("脚本函数索引.tsv", "脚本调用清单.tsv", "脚本变量使用索引.tsv", "脚本对象码出现索引.tsv"),
        "列出 return 表达式里的存档调用、状态变量、字符串和对象码。",
    ),
    RequirementCoverage(
        "分析脚本局部变量",
        "已覆盖（静态）",
        ("脚本局部变量索引.tsv",),
        ("脚本函数索引.tsv", "脚本赋值索引.tsv", "脚本对象码出现索引.tsv"),
        "列出函数内 local 变量、初值、字符串、对象码和资源/存档键用途。",
    ),
    RequirementCoverage(
        "分析脚本调用参数",
        "已覆盖（静态）",
        ("脚本调用参数索引.tsv",),
        ("脚本调用清单.tsv", "脚本函数索引.tsv", "存档读写线索.tsv", "脚本对象码出现索引.tsv"),
        "逐次列出函数调用每个参数里的存档键、资源路径、字符串和对象码。",
    ),
    RequirementCoverage(
        "分析预放置单位/装饰物",
        "已覆盖（静态）",
        ("预放置单位.tsv", "预放置装饰物.tsv"),
        ("地图与对象ID索引.tsv",),
        "导出 war3mapUnits.doo 和 war3map.doo 的坐标、玩家、物品栏、技能和掉落。",
    ),
    RequirementCoverage(
        "分析触发器和全局变量",
        "已覆盖（静态）",
        ("触发器树.tsv", "触发器ECA.tsv", "触发变量.tsv", "脚本触发注册索引.tsv", "脚本全局变量索引.tsv"),
        ("脚本赋值索引.tsv", "脚本变量使用索引.tsv", "脚本可读文本/", "脚本清单.txt"),
        "导出 WTG 目录、ECA 函数/参数原始值、变量清单、JASS globals、脚本变量读写和事件/动作注册入口。",
    ),
    RequirementCoverage(
        "分析脚本全局变量读写",
        "已覆盖（静态）",
        ("脚本变量使用索引.tsv", "脚本赋值索引.tsv", "脚本全局变量索引.tsv"),
        ("脚本条件分支索引.tsv", "脚本循环索引.tsv", "脚本返回值索引.tsv", "脚本可读文本/", "脚本清单.txt"),
        "按函数和行号列出 udg_/gg_/bj_ 全局变量读取、写入、分支条件、返回值和类别。",
    ),
    RequirementCoverage(
        "分析区域/镜头/声音",
        "已覆盖（静态）",
        ("世界区域.tsv", "世界镜头.tsv", "世界声音.tsv"),
        ("地图信息.txt",),
        "导出 W3R/W3C/W3S 明细。",
    ),
    RequirementCoverage(
        "分析地形和路径网格",
        "已覆盖（静态）",
        ("地形摘要.tsv", "地形纹理.tsv", "路径网格.tsv"),
        ("内部文件清单.txt", "资源/资源资产索引.tsv"),
        "导出 W3E 网格/纹理/高度/水位/标志统计与 WPM pathing flag 统计。",
    ),
    RequirementCoverage(
        "核对提取是否完整",
        "已覆盖（诊断+兜底导出）",
        ("提取完整性.txt", "未知文件/Unknown_manifest.tsv"),
        ("内部文件清单.txt", "资料包审计.txt"),
        "显示命名文件覆盖、无名块和源文件可读状态；不可恢复加密块保留 UnknownRaw/ 并提示数据级保护边界。",
    ),
)


def format_requirement_coverage(
    md: MapData | None = None,
    capabilities: ExtractionCapabilities | None = None,
) -> str:
    """Return a TSV matrix that maps user requirements to pack artifacts."""
    resolved = capabilities or ExtractionCapabilities()
    rows = ["需求\t状态\t主要产物\t辅助产物\t说明"]
    rows.extend(_format_row(row) for row in build_dynamic_rows(md, resolved))
    rows.extend(
        _format_row(row)
        for row in evaluate_requirement_rows(_ROWS, md)
    )
    return "\n".join(rows) + "\n"


def _format_row(row: RequirementCoverage) -> str:
    return "\t".join((
        _tsv(row.request),
        _tsv(row.status),
        _tsv("; ".join(row.primary)),
        _tsv("; ".join(row.secondary)),
        _tsv(row.note),
    ))


def _tsv(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")
