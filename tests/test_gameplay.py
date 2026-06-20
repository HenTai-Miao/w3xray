"""war3mapMisc.txt 游戏平衡常数解析。"""
from w3xtool.gameplay import GameplayConstant, parse_gameplay_constants


def test_parse_gameplay_constants_reads_sections_and_values():
    # Given: an INI-like gameplay constants file.
    text = """
    [Misc]
    HeroMaxLevel = 20
    // comment
    [Combat]
    DamageBonus = 1.25
    """

    # When: constants are parsed.
    constants = parse_gameplay_constants(text)

    # Then: section, key and value are retained.
    assert constants == (
        GameplayConstant(section="Misc", key="HeroMaxLevel", value="20"),
        GameplayConstant(section="Combat", key="DamageBonus", value="1.25"),
    )


def test_parse_gameplay_constants_ignores_comments_and_blank_lines():
    # Given: comments, blank lines and malformed lines.
    text = """
    # hash comment
    ; semicolon comment
    not-a-setting
    MaxUnitLevel= 10
    """

    # When: constants are parsed.
    constants = parse_gameplay_constants(text)

    # Then: only valid key/value settings are reported.
    assert constants == (
        GameplayConstant(section="", key="MaxUnitLevel", value="10"),
    )
