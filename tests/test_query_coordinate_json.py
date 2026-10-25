"""Coordinate handoffs validate complete JSON evidence and refuse conflicting points."""

import json

import pytest

from gametool.query_coordinates import coordinates_from_text, radius_from_text


@pytest.mark.parametrize(
    "text",
    [
        '{"x":1,"y":2}\n{"x":3,"y":4}',
        '[{"x":1,"y":2},{"x":3,"y":4}]',
        '{"x":1,"y":2,"x":3,"y":4}',
        '{"selected":{"x":1,"y":2,"x":3}}',
        '{"selected":{"x":1,"y":2},"selected_unit":{"x":3,"y":4}}',
        '{"selected":null,"selected_unit":{"x":1,"y":2}}',
        '{"x":1,"y":2}\n@(3,4)',
        "near 1 2\n@(3,4)",
        '{"x":1,"y":2}\n{"x":3}',
        '{"x":true,"y":2}',
        '{"x":"1","y":2}',
        r'{"x":1,"y":2,"\u0078":3}',
        'near 1 "ignored" 2',
        'near 1 {"note":0} 2',
        '"near 1 2"',
        '{"note":"near 1 2 @(3,4)"}',
        '{"all_units":[{"selected":{"x":1,"y":2}}]}',
    ],
)
def test_distinct_incomplete_or_quoted_coordinates_are_never_chosen(text: str) -> None:
    assert coordinates_from_text(text) is None


@pytest.mark.parametrize(
    "text",
    [
        '{"x":1,"y":2}\n{"x":1.0,"y":2e0}',
        '{"x":1,"y":2,"x":1e0,"y":2.0}',
        '{"selected":{"x":1,"y":2},"selected_unit":{"x":1.0,"y":2e0}}',
        '"selected":{"x":1,"y":2},"all_units":[{"x":3,"y":4}]',
        r'{"select\u0065d":{"x":1,"y":2}}',
        'probe output\n{"selected":{"x":1,"y":2}}\nother units: [{"x":3,"y":4}]',
        '{"x":1,"y":2,"meta":{"selected":{"x":3,"y":4}}}',
        '{"selected":{"x":1,"y":2,"items":[{"selected":{"x":3,"y":10}}]}}',
        "near 1 2\n@(1.0,2e0)",
        '{"x":1,"y":2}\nnear 1 2',
        '单位 "near 3 4" @(1,2)',
        "单位 [n123] ×500 @(1,2)",
    ],
)
def test_matching_coordinates_and_structural_selected_objects_remain_usable(
    text: str,
) -> None:
    point = coordinates_from_text(text)
    assert point is not None and tuple(map(float, point)) == (1.0, 2.0)


@pytest.mark.parametrize(
    "bad",
    [
        '{"x":1,"y":2,}',
        '{"x":+1,"y":2}',
        '{"x":01,"y":2}',
        '{"x":.1,"y":2}',
        '{"x":1e,"y":2}',
        '{"x":NaN,"y":2}',
        '{"x":1,"y":Infinity}',
        '{"x":1,"y":2',
        '{"x":1 "y":2}',
        '{"x":1,"y":2,"items":[0,]}',
        '"selected":{"x":1,"y":2},',
    ],
)
def test_malformed_json_is_not_salvaged_by_regexes(bad: str) -> None:
    assert coordinates_from_text(bad) is None
    assert radius_from_text(bad) is None


@pytest.mark.parametrize("depth", [12000, 20000])
def test_deep_irrelevant_inventory_is_validated_without_recursion_limits(
    depth: int,
) -> None:
    body = "[" * depth + "0" + "]" * depth
    text = '{"selected":{"x":1e-7,"y":-2.123456789012345,"items":' + body + "}}"
    point = coordinates_from_text(text)
    assert point == ("1e-7", "-2.123456789012345")
    assert coordinates_from_text(text[:-1]) is None


def test_all_documents_are_checked_instead_of_a_sample_or_first_root() -> None:
    text = "\n".join('{"x":1,"y":2}' for _ in range(10000))
    assert coordinates_from_text(text) == ("1", "2")
    assert coordinates_from_text(text + '\n{"x":9,"y":10}') is None


def test_selected_point_survives_a_large_inventory_with_same_named_metadata() -> None:
    payload = {
        "all_units": [
            {"x": i, "y": i + 1, "selected": {"x": 9, "y": 10}} for i in range(5000)
        ],
        "selected": {"x": 1, "y": 2},
    }
    assert coordinates_from_text(json.dumps(payload)) == ("1", "2")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("near 1 2 500", "500"),
        ("near 1 2 1e-7", "1e-7"),
        ("near 1 2\n500", None),
        ('near 1 2 "ignored" 500', None),
        ('{"note":"半径 900 near 1 2 700","radius":100}', "100"),
        ('{"meta":{"radius":900},"radius":100}', "100"),
        ('{"selected":{"x":1,"y":2,"radius":100}}', "100"),
        ('{"radius":100,"radius":100.0}', "100"),
        ('{"radius":100,"radius":200}', None),
        ('{"radius":100}\n半径 200', None),
        ('{"radius":true}', None),
        ("半径 -1", None),
        ("near 1 2 1e309", None),
        ("near 1 2 -500", None),
        ('{"note":"半径 900"}', None),
        ('半径 "ignored" 900', None),
        ("1 2 0", "0"),
    ],
)
def test_radius_uses_explicit_numeric_evidence_without_quoted_values(
    text: str, expected: str | None
) -> None:
    assert radius_from_text(text) == expected


def test_extremely_large_encoded_number_is_a_finite_boundary_not_an_exception() -> None:
    text = '{"x":' + "9" * 10000 + ',"y":2}'
    assert coordinates_from_text(text) is None


def test_prose_label_does_not_disable_an_explicit_annotated_position() -> None:
    assert coordinates_from_text("商店 {攻击,防御:一层} @(1,2)") == ("1", "2")


@pytest.mark.parametrize(
    "text",
    [
        '[NaN,{"x":1,"y":2}]',
        'prefix [bad,{"x":1,"y":2}]',
        'prefix {bad,{"x":1,"y":2}}',
        "1-2",
        "1.2.3",
        "[1,2",
        "[[1,2]]",
    ],
)
def test_malformed_wrappers_do_not_expose_inner_points(text: str) -> None:
    assert coordinates_from_text(text) is None


@pytest.mark.parametrize("text", ["[n123] ×500 @(1,2)", "[1,2]", "[1 2]", "(1;2)"])
def test_complete_plain_coordinate_pairs_and_annotated_codes_remain_supported(
    text: str,
) -> None:
    point = coordinates_from_text(text)
    assert point is not None and tuple(map(float, point)) == (1.0, 2.0)


@pytest.mark.parametrize(
    "line,expected",
    [
        ('- 商店 "near 9 10" [n123] @(1,2)', "- 坐标反查模板：near 1 2"),
        ("- 商店 near 1 2 @(3,4)", None),
    ],
)
def test_guide_template_uses_the_same_unambiguous_coordinate_evidence(
    line: str,
    expected: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gametool import guide_report
    from gametool.map_data import MapData

    monkeypatch.setattr(guide_report, "iter_guide_lines", lambda *_args: iter([line]))
    text = guide_report.format_guide_report(
        MapData(path="synthetic.w3x", name="handoff"), "shops"
    )
    assert (expected in text) if expected else "坐标反查模板" not in text
