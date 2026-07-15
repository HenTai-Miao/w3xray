"""Knowledge-pack artifact composition without publication orchestration."""

from __future__ import annotations

from collections.abc import Sequence
import logging
import os

from .map_data import MapData
from .extraction_completeness import (
    build_extraction_completeness_report,
    format_extraction_completeness_report,
)
from .investigation_exports import (
    format_config_format_index,
    format_map_object_id_index,
)
from .item_relation_exports import (
    format_equipment_skills_tsv,
    format_item_acquisition_tsv,
    format_relation_completeness,
)
from .knowledge_audit import format_knowledge_audit
from .knowledge_diagnostics import format_component_diagnostics_tsv
from .knowledge_io import format_lines, write_text
from .knowledge_manifest import format_knowledge_manifest
from .knowledge_object_exports import (
    format_box_id_text as format_box_id_text,
    format_object_fields,
    format_object_text_icons,
    write_box_ids,
    write_object_ids,
)
from .knowledge_preplaced_exports import (
    format_preplaced_doodads_tsv,
    format_preplaced_units_tsv,
)
from .knowledge_requirement_models import ExtractionCapabilities
from .knowledge_requirements import format_requirement_coverage
from .map_info import format_map_info
from .knowledge_resource_exports import write_resources
from .knowledge_terrain_exports import write_terrain_exports
from .knowledge_unknown_exports import write_unknown_files
from .object_id_summary import format_object_id_usage_summary
from .object_text_exports import format_object_text_tsv
from .save_analysis import build_save_report, format_save_report_tsv
from .knowledge_script_exports import (
    all_script_text,
    format_script_index,
    write_readable_scripts,
)
from .knowledge_script_index_exports import write_script_index_exports
from .script_mechanics import format_script_mechanism_report
from .trigger_exports import (
    format_trigger_eca_tsv,
    format_trigger_tree_tsv,
    format_trigger_variables_tsv,
)
from .triggerdata import TriggerDataTable, load_trigger_data_from_source
from .game_data_source import (
    discover_game_data_path,
    open_game_data_source,
    probe_game_data_path,
)
from .game_data_inventory import supports_inventory
from .ui_texts import (
    build_ui_text_report,
    format_ui_text_references_tsv,
    format_ui_text_strings_tsv,
)
from .world_exports import format_cameras_tsv, format_regions_tsv, format_sounds_tsv


def write_knowledge_pack_contents(
    md: MapData,
    out_dir: str,
    external_names: Sequence[str],
    game_data_path: str | None,
) -> tuple[int, ExtractionCapabilities]:
    _ = external_names
    effective_game_data_path = game_data_path or discover_game_data_path()
    trigger_data, inventory_view = _load_trigger_data(effective_game_data_path)
    probe = probe_game_data_path(effective_game_data_path)
    completeness = build_extraction_completeness_report(md)
    capabilities = ExtractionCapabilities(
        game_data_kind=probe.kind if probe.is_readable else "missing",
        has_trigger_schema=trigger_data is not None,
        has_trigger_strings=bool(trigger_data and trigger_data.has_trigger_strings),
        external_listfile=md.external_listfile,
        archive_diagnosis_kind=completeness.archive_diagnosis_kind,
        game_data_inventory_view=inventory_view,
    )
    count = 0
    count += write_text(out_dir, "资料包目录.tsv", format_knowledge_manifest())
    count += write_text(
        out_dir, "需求覆盖.tsv", format_requirement_coverage(md, capabilities)
    )
    count += write_text(
        out_dir,
        "地图信息.txt",
        f"地图：{md.name}\n路径：{md.path}\n\n{format_map_info(md)}\n",
    )
    count += write_text(out_dir, "资料包审计.txt", format_knowledge_audit(md))
    count += write_text(out_dir, "脚本清单.txt", format_script_index(md))
    count += write_text(out_dir, "内部文件清单.txt", format_lines(sorted(md.all_files)))
    count += write_text(
        out_dir,
        "提取完整性.txt",
        format_extraction_completeness_report(completeness),
    )
    count += write_text(out_dir, "组件诊断.tsv", format_component_diagnostics_tsv(md))
    count += write_object_ids(md, os.path.join(out_dir, "对象ID"))
    count += write_box_ids(md, os.path.join(out_dir, "盒子兼容ID"))
    count += write_text(out_dir, "对象字段.tsv", format_object_fields(md))
    count += write_text(out_dir, "对象文本与图标.tsv", format_object_text_icons(md))
    count += write_text(
        out_dir, "对象完整描述.tsv", format_object_text_tsv(md.object_texts)
    )
    count += write_text(
        out_dir,
        "掉落与获取关系.tsv",
        format_item_acquisition_tsv(md.item_relations),
    )
    count += write_text(
        out_dir,
        "装备技能关系.tsv",
        format_equipment_skills_tsv(md.item_relations),
    )
    count += write_text(
        out_dir,
        "关系完整性.txt",
        format_relation_completeness(md.item_relations),
    )
    ui_report = build_ui_text_report(md)
    eca_wts = {int(item.trigstr[8:]): item.text for item in ui_report.strings}
    eca_object_names = {
        code: obj.name for code, obj in md.obj_index.items() if obj.name
    }
    count += write_text(
        out_dir, "UI文本_TRIGSTR.tsv", format_ui_text_strings_tsv(ui_report)
    )
    count += write_text(
        out_dir, "UI文本引用.tsv", format_ui_text_references_tsv(ui_report)
    )
    count += write_resources(
        md, os.path.join(out_dir, "资源"), effective_game_data_path
    )
    count += write_terrain_exports(md, out_dir)
    count += write_unknown_files(md, os.path.join(out_dir, "未知文件"))
    count += write_text(
        out_dir, "存档读写线索.tsv", format_save_report_tsv(build_save_report(md))
    )
    count += write_script_index_exports(md, out_dir)
    count += write_text(out_dir, "配置格式索引.txt", format_config_format_index(md))
    count += write_text(out_dir, "地图与对象ID索引.tsv", format_map_object_id_index(md))
    count += write_text(
        out_dir, "对象ID使用摘要.tsv", format_object_id_usage_summary(md)
    )
    count += write_text(
        out_dir, "脚本机制线索.txt", format_script_mechanism_report(all_script_text(md))
    )
    count += write_text(
        out_dir, "触发器树.tsv", format_trigger_tree_tsv(md.trigger_summary)
    )
    count += write_text(
        out_dir,
        "触发器ECA.tsv",
        format_trigger_eca_tsv(
            md.trigger_summary,
            trigger_data=trigger_data,
            wts=eca_wts,
            object_names=eca_object_names,
        ),
    )
    count += write_text(
        out_dir, "触发变量.tsv", format_trigger_variables_tsv(md.trigger_summary)
    )
    count += write_text(out_dir, "世界区域.tsv", format_regions_tsv(md.regions))
    count += write_text(out_dir, "世界镜头.tsv", format_cameras_tsv(md.cameras))
    count += write_text(out_dir, "世界声音.tsv", format_sounds_tsv(md.sounds))
    count += write_text(out_dir, "预放置单位.tsv", format_preplaced_units_tsv(md))
    count += write_text(out_dir, "预放置装饰物.tsv", format_preplaced_doodads_tsv(md))
    count += write_readable_scripts(md, os.path.join(out_dir, "脚本可读文本"))
    return count, capabilities


def _load_trigger_data(
    game_data_path: str | None,
) -> tuple[TriggerDataTable | None, str]:
    source = open_game_data_source(game_data_path)
    try:
        inventory_view = (
            source.inventory_view.value if supports_inventory(source) else "unavailable"
        )
        return load_trigger_data_from_source(source), inventory_view
    finally:
        if source is not None:
            try:
                source.close()
            except OSError:
                logging.getLogger(__name__).debug(
                    "failed to close game-data source",
                    exc_info=True,
                )
