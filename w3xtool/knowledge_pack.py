"""Consolidated read-only export for map investigation data."""

from __future__ import annotations

from collections.abc import Sequence
import logging
import os

from .api import MapData
from .extraction_completeness import (
    build_extraction_completeness_report,
    format_extraction_completeness_report,
)
from .investigation_exports import format_config_format_index, format_map_object_id_index
from .knowledge_audit import format_knowledge_audit
from .knowledge_io import format_lines, write_text
from .knowledge_manifest import format_knowledge_manifest
from .knowledge_object_exports import (
    format_box_id_text,
    format_object_text_icons,
    write_box_ids,
    write_object_ids,
)
from .knowledge_preplaced_exports import format_preplaced_doodads_tsv, format_preplaced_units_tsv
from .knowledge_requirements import ExtractionCapabilities, format_requirement_coverage
from .map_info import format_map_info
from .knowledge_resource_exports import write_resources
from .knowledge_terrain_exports import write_terrain_exports
from .knowledge_unknown_exports import write_unknown_files
from .object_id_summary import format_object_id_usage_summary
from .save_analysis import build_save_report, format_save_report_tsv
from .knowledge_script_exports import all_script_text, format_script_index, write_readable_scripts
from .script_assignment_index import build_script_assignment_index, format_script_assignment_index_tsv
from .script_call_argument_index import build_script_call_argument_index, format_script_call_argument_index_tsv
from .script_call_catalog import build_script_call_catalog, format_script_call_catalog_tsv
from .script_condition_branch_index import (
    build_script_condition_branch_index,
    format_script_condition_branch_index_tsv,
)
from .script_function_index import build_script_function_index, format_script_function_index_tsv
from .script_global_index import build_script_global_index, format_script_global_index_tsv
from .script_local_index import build_script_local_index, format_script_local_index_tsv
from .script_loop_index import build_script_loop_index, format_script_loop_index_tsv
from .script_mechanics import format_script_mechanism_report
from .script_object_code_occurrence_index import (
    build_script_object_code_occurrence_index,
    format_script_object_code_occurrence_index_tsv,
)
from .script_return_index import build_script_return_index, format_script_return_index_tsv
from .script_string_index import build_script_string_index, format_script_string_index_tsv
from .script_trigger_registration_index import (
    build_script_trigger_registration_index,
    format_script_trigger_registration_index_tsv,
)
from .script_variable_usage_index import build_script_variable_usage_index, format_script_variable_usage_index_tsv
from .trigger_exports import format_trigger_eca_tsv, format_trigger_tree_tsv, format_trigger_variables_tsv
from .triggerdata import TriggerDataTable, load_trigger_data_from_source
from .game_data_source import open_game_data_source, probe_game_data_path
from .ui_texts import (
    build_ui_text_report,
    format_ui_text_references_tsv,
    format_ui_text_strings_tsv,
)
from .world_exports import format_cameras_tsv, format_regions_tsv, format_sounds_tsv


def write_knowledge_pack(
    md: MapData,
    out_dir: str,
    external_names: Sequence[str] = (),
    game_data_path: str | None = None,
) -> int:
    """Write a map knowledge pack and return the number of files written."""
    os.makedirs(out_dir, exist_ok=True)
    _ = external_names
    trigger_data = _load_trigger_data(game_data_path)
    probe = probe_game_data_path(game_data_path)
    completeness = build_extraction_completeness_report(md)
    capabilities = ExtractionCapabilities(
        game_data_kind=probe.kind if probe.is_readable else "missing",
        has_trigger_schema=trigger_data is not None,
        has_trigger_strings=bool(trigger_data and trigger_data.has_trigger_strings),
        external_listfile=md.external_listfile,
        archive_diagnosis_kind=completeness.archive_diagnosis_kind,
    )
    count = 0
    count += write_text(out_dir, "资料包目录.tsv", format_knowledge_manifest())
    count += write_text(out_dir, "需求覆盖.tsv", format_requirement_coverage(md, capabilities))
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
    count += write_object_ids(md, os.path.join(out_dir, "对象ID"))
    count += write_box_ids(md, os.path.join(out_dir, "盒子兼容ID"))
    count += write_text(out_dir, "对象文本与图标.tsv", format_object_text_icons(md))
    ui_report = build_ui_text_report(md)
    eca_wts = {int(item.trigstr[8:]): item.text for item in ui_report.strings}
    eca_object_names = {code: obj.name for code, obj in md.obj_index.items() if obj.name}
    count += write_text(out_dir, "UI文本_TRIGSTR.tsv", format_ui_text_strings_tsv(ui_report))
    count += write_text(out_dir, "UI文本引用.tsv", format_ui_text_references_tsv(ui_report))
    count += write_resources(md, os.path.join(out_dir, "资源"))
    count += write_terrain_exports(md, out_dir)
    count += write_unknown_files(md, os.path.join(out_dir, "未知文件"))
    count += write_text(out_dir, "存档读写线索.tsv", format_save_report_tsv(build_save_report(md)))
    count += write_text(
        out_dir,
        "脚本调用清单.tsv",
        format_script_call_catalog_tsv(build_script_call_catalog(md)),
    )
    count += write_text(
        out_dir,
        "脚本函数索引.tsv",
        format_script_function_index_tsv(build_script_function_index(md)),
    )
    count += write_text(
        out_dir,
        "脚本调用参数索引.tsv",
        format_script_call_argument_index_tsv(build_script_call_argument_index(md)),
    )
    count += write_text(
        out_dir,
        "脚本全局变量索引.tsv",
        format_script_global_index_tsv(build_script_global_index(md)),
    )
    count += write_text(
        out_dir,
        "脚本赋值索引.tsv",
        format_script_assignment_index_tsv(build_script_assignment_index(md)),
    )
    count += write_text(
        out_dir,
        "脚本变量使用索引.tsv",
        format_script_variable_usage_index_tsv(build_script_variable_usage_index(md)),
    )
    count += write_text(
        out_dir,
        "脚本对象码出现索引.tsv",
        format_script_object_code_occurrence_index_tsv(build_script_object_code_occurrence_index(md)),
    )
    count += write_text(
        out_dir,
        "脚本触发注册索引.tsv",
        format_script_trigger_registration_index_tsv(build_script_trigger_registration_index(md)),
    )
    count += write_text(
        out_dir,
        "脚本条件分支索引.tsv",
        format_script_condition_branch_index_tsv(build_script_condition_branch_index(md)),
    )
    count += write_text(
        out_dir,
        "脚本循环索引.tsv",
        format_script_loop_index_tsv(build_script_loop_index(md)),
    )
    count += write_text(
        out_dir,
        "脚本返回值索引.tsv",
        format_script_return_index_tsv(build_script_return_index(md)),
    )
    count += write_text(
        out_dir,
        "脚本局部变量索引.tsv",
        format_script_local_index_tsv(build_script_local_index(md)),
    )
    count += write_text(
        out_dir,
        "脚本字符串索引.tsv",
        format_script_string_index_tsv(build_script_string_index(md)),
    )
    count += write_text(out_dir, "配置格式索引.txt", format_config_format_index(md))
    count += write_text(out_dir, "地图与对象ID索引.tsv", format_map_object_id_index(md))
    count += write_text(out_dir, "对象ID使用摘要.tsv", format_object_id_usage_summary(md))
    count += write_text(out_dir, "脚本机制线索.txt", format_script_mechanism_report(all_script_text(md)))
    count += write_text(out_dir, "触发器树.tsv", format_trigger_tree_tsv(md.trigger_summary))
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
    count += write_text(out_dir, "触发变量.tsv", format_trigger_variables_tsv(md.trigger_summary))
    count += write_text(out_dir, "世界区域.tsv", format_regions_tsv(md.regions))
    count += write_text(out_dir, "世界镜头.tsv", format_cameras_tsv(md.cameras))
    count += write_text(out_dir, "世界声音.tsv", format_sounds_tsv(md.sounds))
    count += write_text(out_dir, "预放置单位.tsv", format_preplaced_units_tsv(md))
    count += write_text(out_dir, "预放置装饰物.tsv", format_preplaced_doodads_tsv(md))
    count += write_readable_scripts(md, os.path.join(out_dir, "脚本可读文本"))
    return count


def _load_trigger_data(game_data_path: str | None) -> TriggerDataTable | None:
    source = open_game_data_source(game_data_path)
    try:
        return load_trigger_data_from_source(source)
    finally:
        close = getattr(source, "close", None)
        if callable(close):
            try:
                close()
            except OSError:
                logging.getLogger(__name__).debug(
                    "failed to close game-data source",
                    exc_info=True,
                )
