"""Source-bearing, comment-safe recipe evidence."""

from w3xtool.api import recipes_from_map
from w3xtool.map_data import MapData
from w3xtool.script_scan import scan_recipes


def test_recipe_keeps_source_function_result_line_and_duplicate_materials() -> None:
    # Given: one function consumes two copies of one item plus another material.
    script = "\n".join((
        "function Forge takes nothing returns nothing",
        "    call RemoveItem(GetItemOfTypeFromUnitBJ(u, 'I001'))",
        "    call RemoveItem(GetItemOfTypeFromUnitBJ(u, 'I001'))",
        "    call RemoveItem(GetItemOfTypeFromUnitBJ(u, 'I002'))",
        "    call UnitAddItemById(u, 'I999')",
        "endfunction",
    ))

    # When: the source is scanned.
    (recipe,) = scan_recipes(script, source="war3map.j")

    # Then: quantities and the exact result evidence location survive.
    assert recipe.ingredients == ["I001", "I001", "I002"]
    assert (recipe.result, recipe.func, recipe.source, recipe.line) == (
        "I999",
        "Forge",
        "war3map.j",
        5,
    )
    assert recipe.confidence == "已确认"
    assert "UnitAddItemById" in recipe.evidence


def test_recipe_scanner_ignores_calls_inside_comments_and_strings() -> None:
    # Given: every apparent recipe operation is non-code text.
    script = "\n".join((
        "// call RemoveItem(GetItemOfTypeFromUnitBJ(u, 'I001'))",
        "// call RemoveItem(GetItemOfTypeFromUnitBJ(u, 'I002'))",
        'call BJDebugMsg("call UnitAddItemById(u, \'I999\')")',
    ))

    # When/Then: no synthetic recipe is emitted.
    assert scan_recipes(script, source="war3map.j") == []


def test_same_recipe_from_two_sources_retains_both_evidence_rows() -> None:
    # Given: identical recipe code exists in two independently named sources.
    script = "\n".join((
        "function Forge takes nothing returns nothing",
        "call RemoveItem(GetItemOfTypeFromUnitBJ(u, 'I001'))",
        "call RemoveItem(GetItemOfTypeFromUnitBJ(u, 'I002'))",
        "call UnitAddItemById(u, 'I999')",
        "endfunction",
    ))
    md = MapData(
        path="x.w3x",
        name="配方图",
        scripts={"war3map.j": script, "war3map.wct(自定义代码).txt": script},
    )

    # When: map-level recipe reuse scans every readable source.
    recipes = recipes_from_map(md)

    # Then: evidence is not collapsed merely because materials and result match.
    assert len(recipes) == 2
    assert {recipe.source for recipe in recipes} == {
        "war3map.j",
        "war3map.wct(自定义代码).txt",
    }
