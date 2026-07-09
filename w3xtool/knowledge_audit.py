"""Compact audit summary for knowledge-pack investigation surfaces."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .extraction_completeness import build_extraction_completeness_report
from .investigation_exports import config_format_entries
from .map_identity import MapIdentity, build_map_identity
from .resource_inventory import build_resource_inventory
from .save_analysis import build_save_report
from .ui_texts import build_ui_text_report

if TYPE_CHECKING:
    from .api import MapData


def format_knowledge_audit(md: MapData) -> str:
    """Return a one-page checklist of the pack's extracted investigation data."""
    ui_report = build_ui_text_report(md)
    inventory = build_resource_inventory(md)
    save_report = build_save_report(md)
    extraction = build_extraction_completeness_report(md)
    identity = build_map_identity(md.path)
    object_count = sum(len(objects) for objects in md.objects.values())
    category_count = sum(1 for objects in md.objects.values() if objects)
    lines = [
        "资料包审计",
        f"地图\t{_tsv(md.name)}",
        (
            f"UI文本\t字符串 {ui_report.string_count}\t引用 {ui_report.reference_count}"
            f"\t未解析 {ui_report.unresolved_count}"
        ),
        (
            f"资源资产\t总数 {len(inventory.items)}"
            f"\t类型 {len(inventory.kind_counts)}\t状态 {len(inventory.status_counts)}"
        ),
        f"配置格式\t已知文件 {len(config_format_entries(md))}",
        (
            f"存档/ID\t线索 {save_report.total}\t对象码 {len(save_report.object_codes)}"
            f"\t本地文件 {len(save_report.local_files)}"
        ),
        (
            f"地图/对象ID\t对象 {object_count}\t分类 {category_count}"
            f"\t内部文件 {len({name.lower() for name in md.all_files})}"
        ),
        _identity_line(identity),
        (
            "提取完整性\t"
            f"{'源可读' if extraction.source_readable else '源文件不可读'}"
            f"\t命名文件 {extraction.named_file_count}"
        ),
    ]
    return "\n".join(lines) + "\n"


def _tsv(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _identity_line(identity: MapIdentity) -> str:
    if not identity.readable:
        return "地图身份\t源文件不可读"
    return f"地图身份\t文件可读\t字节 {identity.size}\tCRC32 {identity.crc32}"
