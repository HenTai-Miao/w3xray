"""TSV exports for parsed WTG trigger tree metadata."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from .presentation_safety import tsv_cell as _tsv

if TYPE_CHECKING:
    from .wtg import TriggerCategory, TriggerTreeSummary
    from .wtg_eca import TriggerEcaFunction, TriggerEcaParameter

from .triggerdata import TriggerDataTable, render_eca_semantic
from .wtg_eca import function_type_label, parameter_type_label


def format_trigger_tree_tsv(summary: TriggerTreeSummary | None) -> str:
    """Return trigger folders and headers as a TSV table."""
    rows = ["类型\tID\t父ID\t名称\t分类\t启用\t自定义脚本\t初始关闭\t初始化运行\t说明"]
    if summary is None:
        return "\n".join(rows) + "\n"
    categories = _category_names(summary.categories)
    for category in summary.categories:
        rows.append("\t".join((
            "分类",
            _object_id(category.category_id),
            _parent_id(category.parent_id),
            _tsv(category.name),
            "",
            "",
            "",
            "",
            "",
            "注释" if category.is_comment else "",
        )))
    for trigger in summary.triggers:
        rows.append("\t".join((
            "触发器",
            _object_id(trigger.object_id),
            _parent_id(trigger.category_id),
            _tsv(trigger.name or "(未命名触发器)"),
            _tsv(categories.get(trigger.category_id, "")),
            _yes_no(trigger.is_enabled),
            _yes_no(trigger.is_custom_text),
            _yes_no(trigger.is_initially_off),
            _yes_no(trigger.run_on_init),
            _tsv(_trigger_description(trigger.description, trigger.is_comment)),
        )))
    _append_diagnostics(rows, summary, 10)
    return "\n".join(rows) + "\n"


def format_trigger_eca_tsv(
    summary: TriggerTreeSummary | None,
    *,
    trigger_data: TriggerDataTable | None = None,
    wts: Mapping[int, str] | None = None,
    object_names: Mapping[str, str] | None = None,
) -> str:
    """Return raw WTG ECA functions and parameters as a TSV table."""
    rows = [
        "触发器\t深度\t行类型\t函数类型\t函数名\t启用\t参数序号\t参数类型\t参数值\t语义文本"
        "\t序号\t分支\t父参数序号"
    ]
    if summary is None:
        return "\n".join(rows) + "\n"
    for function in summary.eca_functions:
        _append_eca_function(
            rows,
            function,
            trigger_data,
            wts,
            object_names,
            depth=function.depth,
            row_type="顶层函数",
            parent_parameter=None,
        )
    _append_diagnostics(rows, summary, 13)
    return "\n".join(rows) + "\n"


def format_trigger_variables_tsv(summary: TriggerTreeSummary | None) -> str:
    """Return trigger global variables as a TSV table."""
    rows = ["名称\t类型\t分类\t数组\t数组大小\t初始化\t初始值\t对象ID\t父ID"]
    if summary is None:
        return "\n".join(rows) + "\n"
    categories = _category_names(summary.categories)
    for variable in summary.variables:
        rows.append("\t".join((
            _tsv(variable.name),
            _tsv(variable.type_name),
            _tsv(categories.get(variable.category, "")),
            _yes_no(variable.is_array),
            str(variable.array_size),
            _yes_no(variable.is_initialized),
            _tsv(variable.initial_value),
            _object_id(variable.object_id),
            _object_id(variable.parent_id),
        )))
    return "\n".join(rows) + "\n"


def _category_names(categories: tuple[TriggerCategory, ...]) -> dict[int, str]:
    return {category.category_id: category.name for category in categories if category.name}


def _append_eca_function(
    rows: list[str],
    function: TriggerEcaFunction,
    trigger_data: TriggerDataTable | None,
    wts: Mapping[int, str] | None,
    object_names: Mapping[str, str] | None,
    *,
    depth: int,
    row_type: str,
    parent_parameter: int | None,
) -> None:
    function_type = function_type_label(function.function_type)
    rows.append("\t".join((
        _tsv(function.trigger_name),
        str(depth),
        row_type,
        _tsv(function_type),
        _tsv(function.name),
        _yes_no(function.is_enabled),
        "",
        "",
        "",
        _tsv(
            render_eca_semantic(
                function,
                trigger_data,
                wts=wts,
                object_names=object_names,
            )
        ),
        str(function.ordinal),
        str(function.branch),
        "" if parent_parameter is None else str(parent_parameter),
    )))
    for index, parameter in enumerate(function.parameters):
        _append_eca_parameter(
            rows,
            function,
            index,
            parameter,
            trigger_data,
            wts,
            object_names,
            row_type="参数",
            depth=depth,
            parent_parameter=None,
        )
    for child in function.children:
        _append_eca_function(
            rows,
            child,
            trigger_data,
            wts,
            object_names,
            depth=depth + 1,
            row_type="子ECA",
            parent_parameter=None,
        )


def _append_eca_parameter(
    rows: list[str],
    function: TriggerEcaFunction,
    index: int,
    parameter: TriggerEcaParameter,
    trigger_data: TriggerDataTable | None,
    wts: Mapping[int, str] | None,
    object_names: Mapping[str, str] | None,
    *,
    row_type: str,
    depth: int,
    parent_parameter: int | None,
) -> None:
    function_type = function_type_label(function.function_type)
    rows.append("\t".join((
        _tsv(function.trigger_name),
        str(depth),
        row_type,
        _tsv(function_type),
        _tsv(function.name),
        _yes_no(function.is_enabled),
        str(index),
        _tsv(parameter_type_label(parameter.parameter_type)),
        _tsv(parameter.value),
        "",
        str(function.ordinal),
        str(function.branch),
        "" if parent_parameter is None else str(parent_parameter),
    )))
    if parameter.nested_function is not None:
        _append_eca_function(
            rows,
            parameter.nested_function,
            trigger_data,
            wts,
            object_names,
            depth=depth + 1,
            row_type="嵌套函数",
            parent_parameter=index,
        )
    if parameter.array_indexer is not None:
        _append_eca_parameter(
            rows,
            function,
            index,
            parameter.array_indexer,
            trigger_data,
            wts,
            object_names,
            row_type="数组索引",
            depth=depth + 1,
            parent_parameter=index,
        )


def _append_diagnostics(
    rows: list[str],
    summary: TriggerTreeSummary,
    column_count: int,
) -> None:
    missing_schema_functions = getattr(summary, "missing_schema_functions", ())
    parse_failures = getattr(summary, "parse_failures", ())
    for item in missing_schema_functions:
        rows.append(_pad_tsv_row(
            "说明\t\t\t缺少 TriggerData/TriggerStrings：只读取触发器头"
            f"\t{_tsv(item.trigger_name)}\t{_tsv(item.function_name)}\t0x{item.offset:x}\t\t\t",
            column_count,
        ))
    for failure in parse_failures:
        rows.append(_pad_tsv_row(
            "说明\t\t\t"
            f"WTG 解析失败：{_tsv(failure.trigger_name)}/{_tsv(failure.function_name)} "
            f"@ 0x{failure.offset:x}：{_tsv(failure.reason)}\t\t\t\t\t\t",
            column_count,
        ))
    if summary.has_unexpanded_functions and not missing_schema_functions and not parse_failures:
        rows.append(_pad_tsv_row(
            "说明\t\t\tWTG ECA 未完整展开：缺少结构化诊断\t\t\t\t\t\t",
            column_count,
        ))


def _pad_tsv_row(row: str, column_count: int) -> str:
    return row + "\t" * max(0, column_count - row.count("\t") - 1)


def _trigger_description(description: str, is_comment: bool) -> str:
    if is_comment and description:
        return f"注释：{description}"
    if is_comment:
        return "注释"
    return description


def _object_id(value: int) -> str:
    return "" if value == 0 else str(value)


def _parent_id(value: int) -> str:
    return str(value)


def _yes_no(value: bool) -> str:
    return "是" if value else "否"
