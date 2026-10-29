"""Parallel/elevated test sessions never share pytest's user-wide cleanup link."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from gametool import dev_test


def test_concurrent_runner_sessions_allocate_independent_pytest_roots(
    tmp_path: Path,
) -> None:
    suite = tmp_path / "suite"
    suite.mkdir()
    configuration = suite / "pytest.ini"
    configuration.write_text("[pytest]\n", encoding="utf-8")
    test = suite / "test_private.py"
    test.write_text(
        "import json, os\n"
        "from pathlib import Path\n"
        "def test_private(tmp_path_factory):\n"
        "    root = tmp_path_factory.getbasetemp()\n"
        "    assert root.name == 'pytest'\n"
        "    assert root.parent.name.startswith('gamexray-test-cache-')\n"
        "    Path(os.environ['GAMEXRAY_TEMP_PROBE']).write_text(\n"
        "        json.dumps({'root': str(root)}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    caller_environment = dict(os.environ)
    processes: list[tuple[subprocess.Popen[str], Path]] = []
    try:
        for index in range(2):
            output = tmp_path / f"session-{index}.json"
            env = dev_test.create_test_environment()
            env["GAMEXRAY_TEMP_PROBE"] = str(output)
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    "-m",
                    "gametool.dev_test",
                    "--noconftest",
                    "-q",
                    "-c",
                    str(configuration),
                    str(test),
                ],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
            )
            processes.append((process, output))
        roots: list[Path] = []
        for process, output in processes:
            stdout, _ = process.communicate(timeout=60)
            assert process.returncode == 0, stdout
            roots.append(Path(json.loads(output.read_text("utf-8"))["root"]))
        assert len(set(roots)) == 2
        assert all(root.is_dir() for root in roots)
        assert dict(os.environ) == caller_environment
    finally:
        for process, _ in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


@pytest.mark.parametrize("joined", [False, True])
def test_explicit_pytest_root_is_forwarded_without_rewriting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, joined: bool
) -> None:
    root = str(tmp_path / "explicit")
    arguments = (f"--basetemp={root}",) if joined else ("--basetemp", root)
    captured: list[tuple[str, ...]] = []

    def run(command: tuple[str, ...], **_kwargs: object):
        captured.append(command)
        return subprocess.CompletedProcess(command, 17)

    monkeypatch.setattr(dev_test.subprocess, "run", run)
    assert dev_test.main([*arguments, "--version"]) == 17
    command = captured[0]
    assert command[-len(arguments) - 1 : -1] == arguments
    assert sum(token.startswith("--basetemp") for token in command) == 1
    assert not Path(root).exists()
