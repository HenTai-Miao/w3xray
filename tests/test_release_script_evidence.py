"""Script exports retain complete strings and authoritative source identities."""

from pathlib import Path
import sys

import pytest

from gametool.knowledge_pack import write_knowledge_pack, write_knowledge_pack_report
from gametool.extraction_diagnostics import ComponentParseError
from gametool.map_data import MapData
from gametool.script_call_catalog import build_script_call_catalog
from gametool.script_string_index import build_script_string_index
from gametool.script_text_export import build_readable_script_exports
from gametool.w3i import W3iInfo
from gametool.wts import parse_wts_component


@pytest.mark.parametrize(
    ("source", "text", "script_type"),
    [
        ("war3map.lua", 'Message(8//2,"真实任务文本")', ""),
        ("war3map.j", 'call Message(8--2,"真实任务文本")', ""),
        (
            "war3map.wct(自定义代码).txt",
            '// ===== 全局自定义脚本 =====\nMessage(8//2,"真实任务文本")',
            "Lua",
        ),
    ],
)
def test_call_catalog_keeps_strings_after_language_specific_arithmetic(
    source: str, text: str, script_type: str
) -> None:
    md = MapData(path="synthetic.w3x", name="调用文本", scripts={source: text})
    md.w3i = W3iInfo(script_type=script_type)
    catalog = build_script_call_catalog(md)
    assert catalog.calls[0].string_args == ("真实任务文本",)
    assert catalog.rows[0].string_args == ("真实任务文本",)


@pytest.mark.parametrize(
    ("digits", "resolved"),
    [
        ("0" * 5000 + "1", "真实文本"),
        ("٠" * 5000 + "١", "真实文本"),
        ("9" * 5001, ""),
    ],
    ids=["long-leading-zero", "unicode-leading-zero", "unknown-long-id"],
)
def test_trigstr_references_do_not_depend_on_interpreter_integer_digit_quota(
    digits: str, resolved: str
) -> None:
    literal = "TRIGSTR_" + digits
    text = f'call BJDebugMsg("{literal}")'
    md = MapData(
        path="synthetic.w3x",
        name="完整文本",
        scripts={"war3map.j": text},
        ui_strings={1: "真实文本"},
    )
    quota = sys.get_int_max_str_digits()
    index = build_script_string_index(md)
    assert index.entries[0].value == literal
    assert index.entries[0].resolved == resolved
    (export,) = build_readable_script_exports(md)
    expected = f'call BJDebugMsg("{resolved}")' if resolved else text
    assert export.text == expected
    assert md.scripts["war3map.j"] == text
    assert sys.get_int_max_str_digits() == quota


def test_knowledge_pack_keeps_original_scripts_beside_localized_reading_copy(
    tmp_path: Path,
) -> None:
    text = (
        'function Id(s)\r\nreturn FourCC("I001")\r\nend\r\n'
        'CreateItem(Id("TRIGSTR_1"),1,2)'
    )
    md = MapData(
        path="synthetic.w3x",
        name="脚本来源",
        scripts={"war3map.lua": text},
        ui_strings={1: "已解析的任务文本"},
    )
    write_knowledge_pack(md, str(tmp_path))
    original = tmp_path / "脚本原始文本" / "war3map.lua"
    assert original.is_file()
    assert original.read_bytes() == text.encode("utf-8")
    readable = tmp_path / "脚本可读文本" / "war3map.lua"
    assert 'Id("已解析的任务文本")' in readable.read_text(encoding="utf-8")
    assert md.scripts["war3map.lua"] == text


def test_trigstr_lookup_uses_the_complete_existing_numeric_identity() -> None:
    digits = "1" + "0" * 4999 + "7"
    md = MapData(
        path="synthetic.w3x",
        name="完整索引",
        scripts={"war3map.j": f'call BJDebugMsg("TRIGSTR_{digits}")'},
        ui_strings={10**5000 + 7: "大索引文本"},
    )
    assert build_script_string_index(md).entries[0].resolved == "大索引文本"
    assert build_readable_script_exports(md)[0].text == 'call BJDebugMsg("大索引文本")'


def test_wts_header_and_script_reference_share_exact_numeric_identity() -> None:
    digits = "0" * 5000 + "1"
    wts = f"STRING {digits}\n{{\n真实文本\n}}\n"
    assert parse_wts_component(wts.encode("utf-8")) == {1: "真实文本"}
    md = MapData(
        path="synthetic.w3x",
        name="原始字符串表",
        scripts={
            "war3map.wts": wts,
            "war3map.j": 'call BJDebugMsg("TRIGSTR_1")',
        },
    )
    assert build_script_string_index(md).entries[0].resolved == "真实文本"
    assert build_readable_script_exports(md)[0].text == 'call BJDebugMsg("真实文本")'


def test_missing_wts_body_keeps_the_complete_large_reference_diagnostic() -> None:
    digits = "1" + "0" * 5000
    with pytest.raises(ComponentParseError) as failure:
        parse_wts_component(f"STRING {digits}\n{{\nmissing close".encode("ascii"))
    assert str(failure.value) == "incomplete WTS block: STRING " + digits


@pytest.mark.parametrize("large_id", [False, True], ids=["leading-zero", "large-id"])
def test_complete_pack_exports_long_trigstr_references_without_losing_raw_evidence(
    tmp_path: Path, large_id: bool
) -> None:
    digits = "1" + "0" * 4999 + "7" if large_id else "0" * 5000 + "1"
    sid = 10**5000 + 7 if large_id else 1
    text = f'call BJDebugMsg("TRIGSTR_{digits}")'
    md = MapData(
        path="synthetic.w3x",
        name="完整文本包",
        scripts={"war3map.j": text},
        ui_strings={sid: "真实文本"},
    )
    result = write_knowledge_pack_report(md, str(tmp_path))
    assert result.failed_count == 0 and result.written_count > 0
    assert (tmp_path / "脚本原始文本" / "war3map.j").read_bytes() == text.encode(
        "utf-8"
    )
    assert (tmp_path / "脚本可读文本" / "war3map.j").read_text(
        encoding="utf-8"
    ) == 'call BJDebugMsg("真实文本")'
    references = (tmp_path / "UI文本引用.tsv").read_text(encoding="utf-8")
    reference = "TRIGSTR_" + digits if large_id else "TRIGSTR_001"
    assert reference + "\t真实文本" in references
    assert "TRIGSTR_" + digits in references
