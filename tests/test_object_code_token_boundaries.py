"""Object-field token boundaries preserve complete encoded identities."""

import pytest

from gametool.item_relation_field_variants import split_relation_codes
from gametool.item_relation_fields import object_field_relations
from gametool.map_data import GameObject, MapData
from gametool.object_codes import field_object_codes, valid_object_code


@pytest.mark.parametrize("space", [" ", "\t", "\r", "\n", "\xa0"])
@pytest.mark.parametrize("leading", [False, True])
def test_raw_four_byte_identity_keeps_its_boundary_whitespace(
    space: str, leading: bool
) -> None:
    code = space + "a01" if leading else "a01" + space
    assert valid_object_code(code)
    assert field_object_codes(code) == (code,)
    assert split_relation_codes(code) == (code,)
    assert field_object_codes("名称(" + code + ")") == (code,)
    assert field_object_codes("I001," + code + "|I002") == ("I001", code, "I002")


@pytest.mark.parametrize("code", [")|ab", "),ab", ")|a,", "),a|"])
@pytest.mark.parametrize("separator", [",", "|"])
def test_terminal_code_protects_its_delimiters_before_any_prefix_is_adopted(
    code: str, separator: str
) -> None:
    reference = "x(abc(" + code + ")"
    assert field_object_codes(reference) == (code,)
    value = separator.join(("I001", reference, "i001", reference))
    assert field_object_codes(value) == ("I001", code, "i001", code)
    assert split_relation_codes(value) == ("I001", code, "i001")


def _shop(value: str, target: str) -> MapData:
    md = MapData("read-only-input.w3x", "token-boundary regression")
    items = [
        GameObject("物品", "w3t", code, code, "目标物品", True)
        for code in (target, "abc(")
    ]
    shop = GameObject("单位", "w3u", "n001", "n001", "商店", True)
    shop.field_values = {"Sellitems": value}
    md.objects = {"物品": items, "单位": [shop]}
    md.obj_identity_index = {(obj.category, obj.obj_id): obj for obj in (*items, shop)}
    md.obj_index = {obj.obj_id: obj for obj in (*items, shop)}
    return md


@pytest.mark.parametrize("code", [" a01", "a01 ", ")|ab", "),ab"])
def test_shop_relations_keep_the_target_and_never_confirm_the_prefix(code: str) -> None:
    value = "x(abc(" + code + ")" if code.startswith(")") else code
    records = tuple(object_field_relations(_shop(value, code)))
    assert len(records) == 1
    assert records[0].item.object_id == code
    assert records[0].evidence.raw == value


@pytest.mark.parametrize("code", [",I01", "|I01", ",a|b", "|a,b"])
def test_ambiguous_suffix_and_complete_raw_list_do_not_confirm_either_reading(
    code: str,
) -> None:
    # This can encode the raw pair ``abc(``, ``I01)`` or one named reference.
    ambiguous = "abc(" + code + ")"
    for prefix in ("", "bad,", "无效名|"):
        assert field_object_codes(prefix + ambiguous) == ()
    assert field_object_codes("I001," + ambiguous + ",I002") == ("I001", "I002")


@pytest.mark.parametrize(
    "value, expected",
    [
        ("", ()),
        ("  ", ()),
        ("    ", ("    ",)),
        ("  I001  ,\tI002\t", ("I001", "I002")),
        ("i,01|i|!?", ("i,01", "i|!?")),
    ],
)
def test_empty_values_formatting_and_complete_literal_delimiters(
    value: str, expected: tuple[str, ...]
) -> None:
    assert field_object_codes(value) == expected


def test_long_names_with_many_delimiters_keep_every_surrounding_list_record() -> None:
    reference = " " * 10000 + "名称," * 10000 + "x(abc()|ab)"
    assert field_object_codes("I001," + reference + ",I002") == (
        "I001",
        ")|ab",
        "I002",
    )
