"""Resource-reference and asset-body exports for knowledge packs."""

from __future__ import annotations

import os

from .api import MapData
from .knowledge_assets import export_resource_bodies, format_asset_body_manifest
from .knowledge_io import format_lines, tsv, write_text
from .resource_content_refs import (
    build_resource_content_references,
    format_resource_content_references_tsv,
)
from .resource_inventory import (
    build_resource_inventory,
    format_resource_inventory_summary,
    format_resource_inventory_tsv,
)
from .resources import build_resource_report


def write_resources(md: MapData, out_dir: str) -> int:
    """Write resource references, inventory and readable asset bodies."""
    os.makedirs(out_dir, exist_ok=True)
    content_refs = build_resource_content_references(md)
    report = build_resource_report(md)
    inventory = build_resource_inventory(md, content_refs.items)
    rows = ["路径\t类型\t引用来源\t引用字段"]
    for node in report.nodes:
        for ref in node.refs:
            rows.append("\t".join((
                tsv(node.path),
                tsv(node.kind),
                tsv(ref.source),
                tsv(ref.detail),
            )))
    count = write_text(out_dir, "资源引用.tsv", "\n".join(rows) + "\n")
    count += write_text(out_dir, "内部素材.txt", format_lines(report.archive_assets))
    count += write_text(out_dir, "未引用素材.txt", format_lines(report.unreferenced_assets))
    count += write_text(out_dir, "资源内容引用.tsv", format_resource_content_references_tsv(content_refs))
    count += write_text(out_dir, "资源资产索引.tsv", format_resource_inventory_tsv(inventory))
    count += write_text(out_dir, "资源分类摘要.txt", format_resource_inventory_summary(inventory))
    body_report = export_resource_bodies(md, out_dir, inventory)
    count += write_text(out_dir, "素材文件_manifest.tsv", format_asset_body_manifest(body_report))
    count += body_report.exported_count
    return count
