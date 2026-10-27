"""Windows acceptance platform helpers stay portable and executable."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from gametool.test_scope import (
    StrictScopePolicy,
    load_scope_manifest,
    verify_retired_contracts,
)


_ROOT = Path(__file__).resolve().parents[1]


def test_windows_scope_preserves_original_portable_contracts() -> None:
    manifest = load_scope_manifest()
    required = {
        (row["module"], row["function"])
        for row in manifest["required_windows_functions"]
    }
    assert (
        "tests/test_integrity_cli.py",
        "test_integrity_cli_returns_two_for_inexact_requests",
    ) in required
    assert (
        "tests/test_description_cache_retained_generations.py",
        "test_stage_io_unsupported_fails_before_any_publication_effect",
    ) in required
    assert (
        "tests/test_batch_map_retirement.py",
        "test_windows_retirement_without_directory_anchor_preserves_all_names",
    ) in required
    assert all(
        row["old_module"] != "tests/test_gui_export_safety.py"
        for row in manifest["retired_functions"]
    )
    verify_retired_contracts()


def test_windows_scope_never_invents_a_skip_for_new_functions(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typing import cast

    monkeypatch.setenv("GAMEXRAY_TEST_SCOPE", "windows")
    module = pytest.Module.from_parent(
        request.session, path=_ROOT / "tests" / "test_integrity_cli.py"
    )
    item = pytest.Function.from_parent(
        module, name="test_future_portable_contract", callobj=lambda: None
    )
    session = cast(
        pytest.Session,
        cast(object, SimpleNamespace(config=SimpleNamespace(args=[str(item.path)]))),
    )
    StrictScopePolicy().pytest_collection_modifyitems(session, [item])
    assert not tuple(item.iter_markers("skip"))


def test_windows_scope_rejects_a_retired_body_moved_back_into_product_tests(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typing import cast

    monkeypatch.setenv("GAMEXRAY_TEST_SCOPE", "windows")
    module = pytest.Module.from_parent(
        request.session, path=_ROOT / "tests" / "test_integrity_cli.py"
    )
    item = pytest.Function.from_parent(
        module,
        name="test_integrity_cli_snapshots_then_verifies_exact_roots",
        callobj=lambda: None,
    )
    session = cast(
        pytest.Session,
        cast(object, SimpleNamespace(config=SimpleNamespace(args=[str(item.path)]))),
    )
    with pytest.raises(pytest.UsageError, match="退役 native"):
        StrictScopePolicy().pytest_collection_modifyitems(session, [item])
    assert not tuple(item.iter_markers("skip"))


def test_windows_process_helper_quotes_powershell_51_argument_lists() -> None:
    # Given: Start-Process on Windows PowerShell 5.1 joins ArgumentList values itself.
    helper_path = _ROOT / "tools" / "windows_process.ps1"
    assert helper_path.is_file(), "shared Windows command-line encoder is missing"
    helper = helper_path.read_text(encoding="utf-8")

    # When/Then: quotes and trailing backslashes are escaped before one command line is joined.
    required = (
        "[AllowEmptyString()]",
        "$Argument -notmatch '[\\s\"]'",
        "[regex]::Replace($Argument, '(\\\\*)\"', '$1$1\\\"')",
        "[regex]::Replace($escaped, '(\\\\+)$', '$1$1')",
        "return '\"' + $escaped + '\"'",
        '$encodedArguments -join " "',
    )
    missing = [value for value in required if value not in helper]
    assert not missing, f"unsafe Windows argument encoder: {missing}"
    assert helper.isascii()


def test_real_machine_powershell_51_script_has_no_utf8_source_tokens() -> None:
    # Windows PowerShell 5.1 reads BOM-less scripts through the legacy code page.
    script = (_ROOT / "tools" / "run_windows_acceptance.ps1").read_text(
        encoding="utf-8"
    )

    assert script.isascii()


def test_hosted_powershell_51_acceptance_step_has_no_utf8_source_tokens() -> None:
    workflow = (_ROOT / ".github" / "workflows" / "windows-package.yml").read_text(
        encoding="utf-8",
    )
    acceptance_step = workflow.split(
        "- name: Execute packaged onedir acceptance", maxsplit=1
    )[1]
    acceptance_step = acceptance_step.split(
        "- name: Upload release assets", maxsplit=1
    )[0]

    assert acceptance_step.isascii()


def test_casclib_build_preserves_dotted_cmake_policy_version() -> None:
    # Given: Windows PowerShell forwards native CMake arguments itself.
    script = (_ROOT / "tools" / "build_casclib.ps1").read_text(encoding="utf-8")

    # When/Then: the dotted policy value is one quoted native argument.
    assert '"-DCMAKE_POLICY_VERSION_MINIMUM=3.5"' in script
