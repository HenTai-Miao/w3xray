"""Strict outcomes for the physically separated Windows product suite."""

from __future__ import annotations

import pytest

from gametool.test_scope import install_scope_policy


def pytest_configure(config: pytest.Config) -> None:
    install_scope_policy(config)
