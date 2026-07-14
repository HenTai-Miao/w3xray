"""Publish the family of script-analysis indexes in a knowledge pack."""

from __future__ import annotations

from .knowledge_io import write_text
from .map_data import MapData
from .script_assignment_index import (
    build_script_assignment_index,
    format_script_assignment_index_tsv,
)
from .script_call_argument_index import (
    build_script_call_argument_index,
    format_script_call_argument_index_tsv,
)
from .script_call_catalog import (
    build_script_call_catalog,
    format_script_call_catalog_tsv,
)
from .script_condition_branch_index import (
    build_script_condition_branch_index,
    format_script_condition_branch_index_tsv,
)
from .script_function_index import (
    build_script_function_index,
    format_script_function_index_tsv,
)
from .script_global_index import (
    build_script_global_index,
    format_script_global_index_tsv,
)
from .script_local_index import build_script_local_index, format_script_local_index_tsv
from .script_loop_index import build_script_loop_index, format_script_loop_index_tsv
from .script_object_code_occurrence_index import (
    build_script_object_code_occurrence_index,
    format_script_object_code_occurrence_index_tsv,
)
from .script_return_index import (
    build_script_return_index,
    format_script_return_index_tsv,
)
from .script_string_index import (
    build_script_string_index,
    format_script_string_index_tsv,
)
from .script_trigger_registration_index import (
    build_script_trigger_registration_index,
    format_script_trigger_registration_index_tsv,
)
from .script_variable_usage_index import (
    build_script_variable_usage_index,
    format_script_variable_usage_index_tsv,
)


def write_script_index_exports(md: MapData, out_dir: str) -> int:
    """Write every deterministic script index and return the written count."""
    count = 0
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
        format_script_object_code_occurrence_index_tsv(
            build_script_object_code_occurrence_index(md)
        ),
    )
    count += write_text(
        out_dir,
        "脚本触发注册索引.tsv",
        format_script_trigger_registration_index_tsv(
            build_script_trigger_registration_index(md)
        ),
    )
    count += write_text(
        out_dir,
        "脚本条件分支索引.tsv",
        format_script_condition_branch_index_tsv(
            build_script_condition_branch_index(md)
        ),
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
    return count
