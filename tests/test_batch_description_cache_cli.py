"""CLI boundary for explicit trusted-description cache roots."""

from w3xtool.batch_cli import parse_batch_cli_options


def test_batch_cli_accepts_owned_description_cache_root() -> None:
    # Given / When
    options = parse_batch_cli_options(
        ("/maps", "--description-cache", "/trusted/descriptions")
    )

    # Then
    assert options.description_cache_path == "/trusted/descriptions"
    assert options.to_batch_options().description_cache_path == (
        "/trusted/descriptions"
    )
