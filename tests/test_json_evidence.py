"""Generic JSON evidence survives deep input and preserves every declaration."""

from dataclasses import asdict
import json

import pytest

from gametool.json_evidence import parse_json_evidence


def test_duplicate_members_and_nested_extensions_keep_tokens_and_source_spans():
    text = (
        ' \r\n{"key":1,"k\\u0065y":-0,"nested":{"same":true,"same":false},'
        '"list":[null,"行\\n\\t\\ufeff",{},[]],"number":1.000e+03}\t'
    )
    nodes, root = parse_json_evidence(text)
    members = nodes[root].members
    assert [member.key for member in members] == [
        "key",
        "key",
        "nested",
        "list",
        "number",
    ]
    assert [nodes[member.node].value for member in members[:2]] == ["1", "-0"]
    nested = nodes[members[2].node]
    assert [member.key for member in nested.members] == ["same", "same"]
    assert [nodes[member.node].value for member in nested.members] == [True, False]
    array = nodes[members[3].node]
    assert [nodes[index].kind for index in array.elements] == [
        "null",
        "string",
        "object",
        "array",
    ]
    assert nodes[array.elements[1]].value == "行\n\t\ufeff"
    assert text[nodes[root].start : nodes[root].end] == text.strip()
    for node in nodes:
        token = text[node.start : node.end]
        assert token
        if node.kind == "number":
            assert token == node.value
        elif node.kind in {"string", "boolean", "null"}:
            assert json.loads(token) == node.value
    number = nodes[members[4].node]
    assert text[number.start : number.end] == number.value == "1.000e+03"


def test_flat_parser_keeps_very_deep_extensions_and_large_integer_tokens():
    depth = 1600
    huge = "7" * 6000
    text = '{"extension":' + "[" * depth + huge + "]" * depth + "}"
    nodes, root = parse_json_evidence(text)
    assert nodes[root].kind == "object"
    assert len(nodes) == depth + 2
    assert sum(node.kind == "array" for node in nodes) == depth
    assert nodes[0].kind == "number" and nodes[0].value == huge
    assert text[nodes[0].start : nodes[0].end] == huge
    serialized = json.dumps([asdict(node) for node in nodes])
    assert huge in serialized
    assert len(json.loads(serialized)) == len(nodes)


@pytest.mark.parametrize(
    "text",
    [
        "[1,]",
        '{"x":}',
        "01",
        "1e",
        "true false",
        '{"x" 1}',
        "",
        "[",
        '{"x":1,}',
        "NaN",
        "Infinity",
        '"unterminated',
    ],
)
def test_flat_json_parser_rejects_incomplete_or_non_json_input(text):
    with pytest.raises(ValueError, match="JSON 字符偏移"):
        parse_json_evidence(text)


@pytest.mark.parametrize(
    ("text", "kind", "value"),
    [
        ("null", "null", None),
        ("true", "boolean", True),
        ("false", "boolean", False),
        ("-0", "number", "-0"),
        ("1e100000", "number", "1e100000"),
        ('"text"', "string", "text"),
        ("{}", "object", None),
        ("[]", "array", None),
    ],
)
def test_root_values_have_exact_whitespace_independent_spans(text, kind, value):
    nodes, root = parse_json_evidence(" \t" + text + "\r\n")
    assert len(nodes) == 1 and root == 0
    assert nodes[root].kind == kind
    assert nodes[root].value == value
    assert (nodes[root].start, nodes[root].end) == (2, len(text) + 2)
