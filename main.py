"""Source-checkout compatibility entrypoint for the installed GameXRay app."""

from __future__ import annotations

# Keep the legacy module-level imports used by API callers and integration tests.
import multiprocessing as multiprocessing

from gametool.app import main
from gametool.cli_summary import iter_cli_summary_lines
from gametool.game_config_summary import iter_game_config_summary_lines

__all__ = ("iter_cli_summary_lines", "iter_game_config_summary_lines", "main")


if __name__ == "__main__":
    main()
