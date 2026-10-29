"""Real Windows GUI acceptance for the adopted Trainer 2.1.22 read paths.

Only explicitly authored inputs and current GameXRay code are used. No Trainer
binary, extracted foreign module, map script, or script checker is executed.
"""

from __future__ import annotations

import json
import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .gui import App
    from .gui_offline_acceptance_support import _Fixtures


UPGRADE_FIELDS = (
    "gar1",
    "gba1",
    "gba2",
    "gba3",
    "gba4",
    "gbpx",
    "gbpy",
    "gcls",
    "gco1",
    "gco2",
    "gco3",
    "gco4",
    "gef1",
    "gef2",
    "gef3",
    "gef4",
    "gglb",
    "gglm",
    "ghk1",
    "ginh",
    "glmb",
    "glmm",
    "glob",
    "glvl",
    "gmo1",
    "gmo2",
    "gmo3",
    "gmo4",
    "gnam",
    "gnsf",
    "grac",
    "greq",
    "grqc",
    "gtib",
    "gtim",
    "gtp1",
    "gub1",
)


def adoption_fixture_payloads() -> dict[str, bytes]:
    from .gui_offline_acceptance_mpq import archive_fixture_payloads

    from .gui_offline_acceptance_diagnostics import diagnostic_fixture_payloads

    return {**archive_fixture_payloads(), **diagnostic_fixture_payloads()}


def exercise_upgrade_metadata(
    app: App, fixtures: _Fixtures, owned: list[tk.Toplevel], errors: list[str]
) -> None:
    """Use actual reference filters, rendered details and both GUI export buttons."""
    from . import field_meta, fields, gui_reference_catalog as reference
    from .gui_offline_acceptance_support import (
        _dialog_response,
        _read_json,
        _read_selection_export,
        _require,
        _set_entry,
        _wait_for,
    )
    from .reference_cli import reference_result_to_dict

    window = reference.ReferenceCatalogWindow(app, id_tables=())
    owned.append(window)
    for entry in (
        window._map_entry,
        window._pack_entry,
        window._profile_entry,
        window._query_entry,
        window._build_entry,
        window._source_entry,
    ):
        _set_entry(entry, "")
    window._kind.set("fields")
    window._category.set("科技")
    _wait_for(
        app,
        lambda: window._result is not None and not window._busy,
        "科技字段显式类别筛选",
        errors,
    )
    result = window._result
    _require(result is not None, "科技字段没有交付实际查询结果")
    assert result is not None
    expected_ids = set(UPGRADE_FIELDS)
    _require(
        result.catalog_complete
        and result.omitted == 0
        and result.matched == len(expected_ids)
        and len(result.records) == len(expected_ids)
        and {record.id for record in result.records} == expected_ids,
        "科技字段类别筛选必须完整保留所有已声明字段",
    )
    _require(window._list.size() == len(expected_ids), "科技字段列表漏记录")
    for index, record in enumerate(result.records):
        _require(
            record.kind == "fields"
            and "科技" in record.categories
            and record.label == fields.label_for(record.id)
            and dict(record.details)["字段类型"] == field_meta.FIELD_TYPES[record.id],
            f"科技字段标签、类型或类别不正确: {record.id}",
        )
        _require(
            "upgrade" in field_meta.GENERATED_FIELD_CATEGORIES[record.id],
            f"科技字段缺少显式生成类别: {record.id}",
        )
        source_ids = field_meta.GENERATED_FIELD_CATEGORY_PROVENANCE[record.id][
            "upgrade"
        ]
        _require(
            source_ids and all(source in str(record.details) for source in source_ids),
            f"科技字段详情未保留类别来源: {record.id}",
        )
        window._list.selection_clear(0, "end")
        window._list.selection_set(index)
        window._list.event_generate("<<ListboxSelect>>", when="tail")
        _wait_for(
            app,
            lambda: (
                window._render_id is None
                and record.id in window._output.get("1.0", "end-1c")
            ),
            "科技字段完整详情",
            errors,
        )
        rendered = window._output.get("1.0", "end-1c")
        _require(
            rendered == window._detail_content
            and record.label in rendered
            and all(source in rendered for source in source_ids),
            f"科技字段渲染丢失完整来源: {record.id}",
        )
    expected = json.loads(
        json.dumps(reference_result_to_dict(result), ensure_ascii=False)
    )
    destination = fixtures.root / "exports" / "upgrade-fields.json"
    with _dialog_response(reference.filedialog, "asksaveasfilename", str(destination)):
        window._export_button.invoke()
    _wait_for(
        app,
        lambda: (
            destination.is_file()
            and not window._exporting
            and "已导出" in str(window._status.cget("text"))
        ),
        "科技字段全部匹配导出",
        errors,
    )
    _require(_read_json(destination) == expected, "科技字段完整 JSON 导出内容改变")
    window._list.selection_clear(0, "end")
    window._list.selection_set(0, "end")
    window._list.event_generate("<<ListboxSelect>>", when="tail")
    _wait_for(
        app,
        lambda: (
            len(window._list.curselection()) == len(expected_ids)
            and window._render_id is None
        ),
        "科技字段实际全选",
        errors,
    )
    selected = fixtures.root / "exports" / "upgrade-fields-selected.tsv"
    with _dialog_response(reference.filedialog, "asksaveasfilename", str(selected)):
        window._export_selected_button.invoke()
    _wait_for(
        app,
        lambda: (
            selected.is_file()
            and not window._exporting
            and "已导出" in str(window._status.cget("text"))
        ),
        "科技字段全选 TSV 导出",
        errors,
    )
    exported = _read_selection_export(selected)
    _require(
        exported.pop("selection")
        == {
            "indices": list(range(len(expected_ids))),
            "selected": len(expected_ids),
            "displayed": len(expected_ids),
            "matched": len(expected_ids),
            "omitted_by_query": 0,
        }
        and exported == expected,
        "科技字段 TSV 重解析后不等于完整选中记录",
    )
