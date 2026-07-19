"""Windows acceptance platform helpers stay portable and executable."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import requires_posix_provenance


_ROOT = Path(__file__).resolve().parents[1]


def test_windows_capability_filter_is_limited_to_posix_provenance_suites() -> None:
    # Given / When / Then: extraction and packaged acceptance remain mandatory.
    for path in (
        Path("tests/test_batch_e2e.py"),
        Path("tests/test_acceptance_runner.py"),
        Path("tests/test_gui_description_cache.py"),
        Path("tests/test_trusted_description_cache.py"),
    ):
        assert not requires_posix_provenance(path)
    for path in (
        Path("tests/test_batch_map_retirement.py"),
        Path("tests/test_description_cache_publication.py"),
        Path("tests/test_integrity_snapshot.py"),
        Path("tests/test_safe_output_publication_atomicity.py"),
    ):
        assert requires_posix_provenance(path)


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
