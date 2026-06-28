"""Load-option normalization tests."""

import unittest

from w3xtool.load_options import (
    COMMANDS_KEY,
    OBJECT_BROWSER_KEY,
    RECIPES_KEY,
    default_load_options,
    load_options_from_config,
    object_only_load_options,
)


class TestLoadOptions(unittest.TestCase):
    def test_load_options_from_config_restores_saved_values(self):
        # Given: a persisted config from a previous run.
        config = {"load_options": {COMMANDS_KEY: False, RECIPES_KEY: False}}

        # When: load options are restored.
        options = load_options_from_config(config)

        # Then: saved categories are preserved and missing ones keep safe defaults.
        self.assertFalse(options[COMMANDS_KEY])
        self.assertFalse(options[RECIPES_KEY])
        self.assertTrue(options[OBJECT_BROWSER_KEY])

    def test_object_only_profile_disables_everything_else(self):
        # Given/When: the object-only quick profile is built.
        options = object_only_load_options()

        # Then: only object browsing remains enabled.
        self.assertTrue(options[OBJECT_BROWSER_KEY])
        self.assertTrue(any(default_load_options().values()))
        self.assertFalse(any(value for key, value in options.items() if key != OBJECT_BROWSER_KEY))


if __name__ == "__main__":
    unittest.main()
