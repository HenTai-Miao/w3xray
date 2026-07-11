"""Resource-reference and asset-body exports for knowledge packs."""

from __future__ import annotations

import logging

from .game_data_source import GameDataSource, open_game_data_source
from .knowledge_assets import export_resource_bodies, format_asset_body_manifest
from .knowledge_io import format_lines, tsv, write_text
from .map_data import MapData
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


def write_resources(
    md: MapData,
    out_dir: str,
    game_data_path: str | None = None,
) -> int:
    """Write resource references, inventory and readable asset bodies."""
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
    game_data_source = open_game_data_source(game_data_path)
    try:
        body_report = export_resource_bodies(
            md,
            out_dir,
            inventory,
            game_data_source=game_data_source,
        )
    finally:
        _close_game_data_source(game_data_source)
    count += write_text(out_dir, "素材文件_manifest.tsv", format_asset_body_manifest(body_report))
    count += body_report.exported_count
    return count


def _close_game_data_source(source: GameDataSource | None) -> None:
    if source is None:
        return
    try:
        source.close()
    except OSError:
        logging.getLogger(__name__).debug(
            "failed to close resource game-data source",
            exc_info=True,
        )
