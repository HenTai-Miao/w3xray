"""Real Windows installation workflow security and routing contracts."""

from pathlib import Path


_WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "windows-real-war3.yml"
)


def test_real_install_workflow_requires_dedicated_self_hosted_machine() -> None:
    # Given: a manually triggered workflow that can access a real installed client.
    workflow = _WORKFLOW.read_text(encoding="utf-8")

    # When/Then: it cannot accidentally claim hosted synthetic coverage as real-install evidence.
    assert "workflow_dispatch" in workflow
    assert "self-hosted" in workflow
    assert "w3xray-war3" in workflow
    assert "run_windows_acceptance.ps1" in workflow
    assert "war3_dir" in workflow


def test_real_install_input_reaches_powershell_through_environment() -> None:
    # Given: a manually supplied path that may contain PowerShell metacharacters.
    workflow = _WORKFLOW.read_text(encoding="utf-8")

    # When/Then: the expression is data in env, never source text in the run block.
    assert "W3XRAY_ACCEPTANCE_WAR3_DIR: ${{ inputs.war3_dir }}" in workflow
    assert "-War3Dir $env:W3XRAY_ACCEPTANCE_WAR3_DIR" in workflow
    assert "-War3Dir '${{ inputs.war3_dir }}'" not in workflow


def test_real_install_runner_executes_exact_reviewed_sha_in_protected_environment() -> (
    None
):
    # Given: a persistent runner with access to a real Warcraft installation.
    workflow = _WORKFLOW.read_text(encoding="utf-8")

    # When/Then: the reviewed commit is immutable, verified, and environment-gated.
    assert "permissions:\n  contents: read" in workflow
    assert "environment: w3xray-real-war3" in workflow
    assert "source_sha:" in workflow
    assert "ref: ${{ inputs.source_sha }}" in workflow
    assert "SOURCE_SHA_INPUT: ${{ inputs.source_sha }}" in workflow
    assert "^[0-9a-fA-F]{40}$" in workflow
    assert "$actualSha = (git rev-parse HEAD).Trim().ToLowerInvariant()" in workflow
    assert "if ($actualSha -ne $expectedSha)" in workflow
    assert "source_ref" not in workflow
    assert "default: local" not in workflow
    assert "ref: local" not in workflow
    assert "persist-credentials: false" in workflow
