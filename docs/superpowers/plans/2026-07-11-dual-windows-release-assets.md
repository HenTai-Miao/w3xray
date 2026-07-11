# Dual Windows Release Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish `v0.1.1` with both the existing fast onedir ZIP and a directly downloadable, separately accepted PyInstaller onefile EXE.

**Architecture:** Keep one PyInstaller spec and one dependency inventory, but select the final PyInstaller topology through a typed `DistFormat` passed by the project build command. The Windows workflow builds and executes onedir first, then onefile, creates release-ready assets on Windows, and preserves separate acceptance evidence for both formats.

**Tech Stack:** Python 3.14, uv, pytest, PyInstaller 6.20, PowerShell 5.1, GitHub Actions `windows-2022`, CascLib 3.0, GitHub CLI.

## Global Constraints

- Default `uv run w3xray-dist` behavior remains onedir.
- `uv run w3xray-dist --onefile` is the only new build selector.
- Both formats use the same Analysis, hidden imports, CustomTkinter resources, CascLib DLL, license, and pinned source identity.
- UPX remains disabled for both formats.
- Both packaged executables must run the full acceptance command before publication.
- A packaged Windows acceptance must prove the bundled CascLib DLL and required exports load even when no real Warcraft installation is available.
- The real Warcraft CASC lane remains restricted to the existing protected self-hosted workflow.
- Existing `v0.1.0` is immutable; dual assets ship as `v0.1.1`.
- Implementation commits land on `local`, then `local` is fast-forwarded into `main` after local gates pass.
- The release workflow runs from the exact merged `main` HEAD; neither `local` nor an earlier tag is a publication source.
- Build intermediates and downloaded artifacts remain outside git and under the platform temp/build directories.

---

## File Map

- Modify `w3xtool/dist_build.py`: typed format selection, spec environment, artifact paths, CLI help.
- Modify `tests/test_dist_build.py`: red/green contracts for onedir and onefile build selection.
- Modify `魔兽地图提取器.spec`: conditional EXE/COLLECT topology while keeping one Analysis.
- Modify `w3xtool/acceptance_runner.py`: packaged CascLib load lane.
- Modify `tests/test_acceptance_runner.py`: portable skip and Windows DLL-load behavior.
- Modify `.github/workflows/windows-package.yml`: build, accept, and upload both formats.
- Modify `tools/run_windows_acceptance.ps1`: real-machine acceptance of both formats.
- Modify `tests/test_windows_acceptance_assets.py`: exact dual-build workflow/script gates.
- Modify `pyproject.toml` and `uv.lock`: bump package version to `0.1.1`.
- Modify `README.md`: explain ZIP versus single EXE and SmartScreen/startup trade-offs.

---

### Task 1: Add Typed Build Format Selection

**Files:**
- Modify: `tests/test_dist_build.py`
- Modify: `w3xtool/dist_build.py`

**Interfaces:**
- Produces: `DistFormat(StrEnum)` with `ONEDIR = "onedir"` and `ONEFILE = "onefile"`.
- Produces: `BUILD_MODE_ENV: Final = "W3XRAY_PYINSTALLER_MODE"`.
- Produces: `DistBuildConfig.format: DistFormat` and `DistCliOptions.format: DistFormat`.
- Preserves: `build_pyinstaller_command(config) -> tuple[str, ...]` and default onedir behavior.

- [ ] **Step 1: Add failing onefile option and artifact-path tests**

Add imports and tests to `tests/test_dist_build.py`:

```python
from collections.abc import Sequence
from dataclasses import replace

from w3xtool.dist_build import (
    APP_NAME,
    BUILD_MODE_ENV,
    DistBuildConfig,
    DistFormat,
    build_pyinstaller_command,
    default_dist_config,
    expected_artifact_path,
    parse_cli_options,
    run_dist_build,
)


def test_onefile_option_selects_direct_executable(tmp_path: Path) -> None:
    options = parse_cli_options(("--onefile",))
    config = replace(default_dist_config(tmp_path), format=options.format)

    assert options.format is DistFormat.ONEFILE
    assert expected_artifact_path(config, system="Windows") == (
        tmp_path / "dist" / f"{APP_NAME}.exe"
    )


def test_default_format_remains_onedir(tmp_path: Path) -> None:
    options = parse_cli_options(())
    config = replace(default_dist_config(tmp_path), format=options.format)

    assert options.format is DistFormat.ONEDIR
    assert expected_artifact_path(config, system="Windows") == (
        tmp_path / "dist" / APP_NAME / f"{APP_NAME}.exe"
    )
```

- [ ] **Step 2: Run the focused tests and confirm the missing API failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest \
  tests/test_dist_build.py::test_onefile_option_selects_direct_executable \
  tests/test_dist_build.py::test_default_format_remains_onedir \
  -q -p no:cacheprovider
```

Expected: collection fails because `DistFormat` and `BUILD_MODE_ENV` do not exist.

- [ ] **Step 3: Implement the typed build format and CLI selector**

Update `w3xtool/dist_build.py` with:

```python
import os
from enum import StrEnum

BUILD_MODE_ENV: Final = "W3XRAY_PYINSTALLER_MODE"


class DistFormat(StrEnum):
    ONEDIR = "onedir"
    ONEFILE = "onefile"


@dataclass(frozen=True, slots=True)
class DistBuildConfig:
    project_root: Path
    spec_path: Path
    dist_path: Path
    work_path: Path
    clean: bool
    format: DistFormat = DistFormat.ONEDIR


@dataclass(frozen=True, slots=True)
class DistCliOptions:
    dry_run: bool = False
    clean: bool = True
    format: DistFormat = DistFormat.ONEDIR
```

Add the selector to `parse_cli_options()`:

```python
case "--onefile":
    options = replace(options, format=DistFormat.ONEFILE)
```

Select the artifact path before the existing platform match:

```python
if config.format is DistFormat.ONEFILE:
    return config.dist_path / (f"{APP_NAME}.exe" if current_system == "Windows" else APP_NAME)
```

Pass the format to the spec in `run_dist_build()`:

```python
result = subprocess.run(
    command,
    cwd=config.project_root,
    check=False,
    env={**os.environ, BUILD_MODE_ENV: config.format.value},
)
```

Propagate the parsed format in `main()`:

```python
config = replace(
    default_dist_config(),
    clean=options.clean,
    format=options.format,
)
```

Update `help_text()` so the usage includes `[--onefile]` and explains that the default is onedir.

- [ ] **Step 4: Add a failing environment propagation test, then make it green**

Add to `tests/test_dist_build.py`:

```python
def test_run_dist_build_passes_onefile_mode_to_spec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec_path = tmp_path / f"{APP_NAME}.spec"
    spec_path.write_text("", encoding="utf-8")
    config = replace(default_dist_config(tmp_path), format=DistFormat.ONEFILE)
    captured: dict[str, str] = {}

    def run(
        command: Sequence[str],
        *,
        cwd: Path,
        check: bool,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        _ = cwd, check
        captured.update(env)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("w3xtool.dist_build.subprocess.run", run)

    assert run_dist_build(config) == 0
    assert captured[BUILD_MODE_ENV] == "onefile"
```

Run before and after implementation:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_dist_build.py -q -p no:cacheprovider
```

Expected before: FAIL because the environment is absent. Expected after: all `test_dist_build.py` tests pass.

- [ ] **Step 5: Commit the typed build selector**

```bash
git add w3xtool/dist_build.py tests/test_dist_build.py
git commit -m "feat: select Windows package format"
```

---

### Task 2: Parameterize the Single PyInstaller Spec

**Files:**
- Modify: `tests/test_dist_build.py`
- Modify: `魔兽地图提取器.spec`

**Interfaces:**
- Consumes: `W3XRAY_PYINSTALLER_MODE=onedir|onefile`.
- Produces: onedir `COLLECT` or direct onefile `EXE`, never both in one invocation.
- Preserves: one shared `Analysis`, `PYZ`, data list, binary list, and hidden import list.

- [ ] **Step 1: Add a failing spec topology contract**

Replace the current spec string test with assertions covering both modes:

```python
def test_spec_supports_onedir_and_onefile_from_one_analysis() -> None:
    spec = (Path(__file__).resolve().parents[1] / f"{APP_NAME}.spec").read_text(
        encoding="utf-8",
    )

    assert "W3XRAY_PYINSTALLER_MODE" in spec
    assert "build_mode == 'onefile'" in spec
    assert "a.binaries" in spec
    assert "a.datas" in spec
    assert "exclude_binaries=False" in spec
    assert "exclude_binaries=True" in spec
    assert "COLLECT(" in spec
    assert spec.count("Analysis(") == 1
    assert "CascLib.dll" in spec
    assert "collect_all('customtkinter')" in spec
```

- [ ] **Step 2: Run the test and confirm the current onedir-only spec fails**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest \
  tests/test_dist_build.py::test_spec_supports_onedir_and_onefile_from_one_analysis \
  -q -p no:cacheprovider
```

Expected: FAIL because the mode environment and onefile branch are absent.

- [ ] **Step 3: Implement the conditional spec topology**

Import `os`, parse and validate the mode before `Analysis`:

```python
import os

build_mode = os.environ.get('W3XRAY_PYINSTALLER_MODE', 'onedir')
if build_mode not in {'onedir', 'onefile'}:
    raise ValueError(f'unsupported W3XRAY_PYINSTALLER_MODE: {build_mode}')
```

Keep the existing `Analysis` and `PYZ` unchanged. Replace the existing EXE/COLLECT tail with:

```python
common_exe_options = {
    'name': '魔兽地图提取器',
    'debug': False,
    'bootloader_ignore_signals': False,
    'strip': False,
    'upx': False,
    'upx_exclude': [],
    'runtime_tmpdir': None,
    'console': False,
    'disable_windowed_traceback': False,
    'argv_emulation': False,
    'target_arch': None,
    'codesign_identity': None,
    'entitlements_file': None,
}

if build_mode == 'onefile':
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        exclude_binaries=False,
        **common_exe_options,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        **common_exe_options,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name='魔兽地图提取器',
    )
```

- [ ] **Step 4: Verify both dry-run modes and spec tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_dist_build.py -q -p no:cacheprovider
uv run w3xray-dist --dry-run
uv run w3xray-dist --dry-run --onefile
```

Expected: tests pass; the default output path is under the app directory and onefile output is directly under `dist/`.

- [ ] **Step 5: Commit the spec topology**

```bash
git add 魔兽地图提取器.spec tests/test_dist_build.py
git commit -m "feat: build onedir and onefile from one spec"
```

---

### Task 3: Prove Packaged CascLib Loads

**Files:**
- Modify: `tests/test_acceptance_runner.py`
- Modify: `w3xtool/acceptance_runner.py`

**Interfaces:**
- Produces acceptance check `bundled_casclib`.
- Consumes `require_windows`; skips the lane for portable non-Windows acceptance.
- Uses `default_dll_path() -> Path` and `CtypesCascLibApi(dll_path=path)`.

- [ ] **Step 1: Add failing skip and DLL-load tests**

Add to `tests/test_acceptance_runner.py`:

```python
def test_portable_acceptance_skips_bundled_casclib(tmp_path: Path) -> None:
    module = importlib.import_module("w3xtool.acceptance_runner")
    config = module.AcceptanceConfig(
        map_path=_MAP,
        campaign_path=None,
        war3_dir=None,
        output_dir=tmp_path,
        run_gui=False,
        require_windows=False,
    )

    report = module.run_acceptance(config)
    statuses = {check.name: check.status.value for check in report.checks}
    assert statuses["bundled_casclib"] == "skip"


def test_windows_acceptance_loads_bundled_casclib(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = importlib.import_module("w3xtool.acceptance_runner")
    dll = tmp_path / "CascLib.dll"
    dll.write_bytes(b"MZfixture")
    loaded: list[Path] = []

    monkeypatch.setattr(module, "default_dll_path", lambda: dll)
    monkeypatch.setattr(module, "CtypesCascLibApi", lambda *, dll_path: loaded.append(dll_path))

    check = module._bundled_casclib_check(require_windows=True)

    assert check.status.value == "pass"
    assert loaded == [dll]
    assert "CascLib.dll" in check.detail
```

- [ ] **Step 2: Run tests and confirm the missing lane failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest \
  tests/test_acceptance_runner.py::test_portable_acceptance_skips_bundled_casclib \
  tests/test_acceptance_runner.py::test_windows_acceptance_loads_bundled_casclib \
  -q -p no:cacheprovider
```

Expected: FAIL because `bundled_casclib` and `_bundled_casclib_check` do not exist.

- [ ] **Step 3: Implement the acceptance lane**

Extend the import from `casclib_api`:

```python
from .casclib_api import CtypesCascLibApi, MAX_CASC_FILE_SIZE, default_dll_path
```

Append the check immediately after `windows_runtime` in `run_acceptance()`:

```python
checks.append(_bundled_casclib_check(config.require_windows))
```

Add:

```python
def _bundled_casclib_check(require_windows: bool) -> AcceptanceCheck:
    if not require_windows:
        return AcceptanceCheck("bundled_casclib", AcceptanceStatus.SKIP, "未要求 Windows", 0)
    return _run_check("bundled_casclib", _check_bundled_casclib)


def _check_bundled_casclib() -> str:
    path = default_dll_path()
    _ = CtypesCascLibApi(dll_path=path)
    return f"path={path}; bytes={path.stat().st_size}"
```

- [ ] **Step 4: Run acceptance tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_acceptance_runner.py -q -p no:cacheprovider
```

Expected: all acceptance tests pass and portable runs report `bundled_casclib=skip`.

- [ ] **Step 5: Commit the packaged DLL gate**

```bash
git add w3xtool/acceptance_runner.py tests/test_acceptance_runner.py
git commit -m "test: verify bundled CascLib at runtime"
```

---

### Task 4: Build and Accept Both Formats on Windows

**Files:**
- Modify: `tests/test_windows_acceptance_assets.py`
- Modify: `.github/workflows/windows-package.yml`
- Modify: `tools/run_windows_acceptance.ps1`

**Interfaces:**
- Consumes: `uv run w3xray-dist` and `uv run w3xray-dist --onefile`.
- Triggers formal push builds from `main` (with pull requests and manual dispatch preserved).
- Produces: `artifacts/windows-onedir/acceptance.json` and `artifacts/windows-onefile/acceptance.json`.
- Produces release-ready `artifacts/windows-release/w3xray-v0.1.1-windows-x64.zip` and `.exe`.

- [ ] **Step 1: Strengthen workflow/script tests before changing assets**

Update `test_hosted_windows_workflow_packages_and_executes_artifact()` to require:

```python
for required in (
    "uv run w3xray-dist",
    "uv run w3xray-dist --onefile",
    "artifacts/windows-onedir",
    "artifacts/windows-onefile",
    "Compress-Archive",
    "w3xray-v$Version-windows-x64.zip",
    "w3xray-v$Version-windows-x64.exe",
    "actions/upload-artifact@v4",
):
    assert required in workflow
```

Update the real-machine script test with the same two build commands and both evidence directories. Preserve both ASCII-only assertions.

- [ ] **Step 2: Run the tests and confirm missing onefile wiring**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_windows_acceptance_assets.py -q -p no:cacheprovider
```

Expected: FAIL because onefile, separate evidence, and release-ready assets are absent.

- [ ] **Step 3: Update hosted workflow with explicit paths**

Change `push.branches` from `local` to `main`. Keep the source block ASCII-only. The workflow sequence becomes:

```yaml
- name: Build onedir executable
  run: uv run w3xray-dist
- name: Execute packaged onedir acceptance
  shell: powershell
  run: |
    $OnedirExe = @(Get-ChildItem -LiteralPath ".\dist" -Filter "*.exe" -File -Recurse)
    if ($OnedirExe.Count -ne 1) { throw "Expected one onedir executable" }
    & $OnedirExe[0].FullName acceptance `
      --map ".\tests\fixtures\maps\war3net-map-script-builder.w3x" `
      --campaign ".\tests\fixtures\reference\stormlib-campaign.w3n" `
      --output ".\artifacts\windows-onedir" `
      --report ".\artifacts\windows-onedir\acceptance.json" `
      --repeat 5 --require-windows
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
- name: Build onefile executable
  run: uv run w3xray-dist --onefile
- name: Execute packaged onefile acceptance
  shell: powershell
  run: |
    $OnefileExe = @(Get-ChildItem -LiteralPath ".\dist" -Filter "*.exe" -File)
    if ($OnefileExe.Count -ne 1) { throw "Expected one direct executable" }
    & $OnefileExe[0].FullName acceptance `
      --map ".\tests\fixtures\maps\war3net-map-script-builder.w3x" `
      --campaign ".\tests\fixtures\reference\stormlib-campaign.w3n" `
      --output ".\artifacts\windows-onefile" `
      --report ".\artifacts\windows-onefile\acceptance.json" `
      --repeat 5 --require-windows
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Create release-ready assets using ASCII source text:

```powershell
$Version = uv run python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
$ReleaseDir = ".\artifacts\windows-release"
New-Item -ItemType Directory -Path $ReleaseDir -Force | Out-Null
$Onedir = @(Get-ChildItem -LiteralPath ".\dist" -Directory)
if ($Onedir.Count -ne 1) { throw "Expected one onedir directory" }
Compress-Archive -LiteralPath $Onedir[0].FullName -DestinationPath "$ReleaseDir\w3xray-v$Version-windows-x64.zip"
Copy-Item -LiteralPath $OnefileExe[0].FullName -Destination "$ReleaseDir\w3xray-v$Version-windows-x64.exe"
Copy-Item -LiteralPath ".\artifacts\windows-onedir\acceptance.json" -Destination "$ReleaseDir\windows-onedir-acceptance.json"
Copy-Item -LiteralPath ".\artifacts\windows-onefile\acceptance.json" -Destination "$ReleaseDir\windows-onefile-acceptance.json"
```

Upload `artifacts/windows-release/*` as artifact `w3xray-windows-release-assets` with
`actions/upload-artifact@v4`.

- [ ] **Step 4: Update the real-machine script to accept both formats**

In `tools/run_windows_acceptance.ps1`, preserve ASCII-only source and perform the same sequence. Use distinct output/report directories and include `--war3-dir $env:W3XRAY_WAR3_DIR` in both invocations. Do not discover both executables with one recursive count after onefile is built.

- [ ] **Step 5: Run workflow asset and full local tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_windows_acceptance_assets.py tests/test_dist_build.py tests/test_acceptance_runner.py -q -p no:cacheprovider
uv run python -m pytest -q -rs -p no:cacheprovider
```

Expected: all tests pass; only the pre-existing environment-dependent skips remain.

- [ ] **Step 6: Commit dual Windows workflow support**

```bash
git add .github/workflows/windows-package.yml tools/run_windows_acceptance.ps1 tests/test_windows_acceptance_assets.py
git commit -m "ci: build and accept both Windows packages"
```

---

### Task 5: Version and User Documentation

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `README.md`

**Interfaces:**
- Produces project version `0.1.1`.
- Documents direct EXE and ZIP behavior without claiming code signing.

- [ ] **Step 1: Update README packaging expectations**

Change the direct-use section to state:

```markdown
Windows Release 同时提供：

- `w3xray-v0.1.1-windows-x64.zip`：完整解压后运行，启动更快，适合长期使用。
- `w3xray-v0.1.1-windows-x64.exe`：单文件直接运行，首次启动会解压到临时目录，可能出现 SmartScreen 提示。

两者功能相同；遇到杀软误报或启动问题时优先使用 ZIP 版。
```

- [ ] **Step 2: Bump the project and lockfile version**

Set:

```toml
version = "0.1.1"
```

Then run:

```bash
uv lock
```

Confirm both `pyproject.toml` and the editable `w3xray` package entry in `uv.lock` report `0.1.1`.

- [ ] **Step 3: Verify documentation and metadata**

Run:

```bash
rg -n '0\.1\.1|windows-x64\.zip|windows-x64\.exe|SmartScreen' pyproject.toml uv.lock README.md
git diff --check
```

Expected: version and both user assets are documented with no whitespace errors.

- [ ] **Step 4: Commit version and documentation**

```bash
git add pyproject.toml uv.lock README.md
git commit -m "docs: prepare dual-package release"
```

---

### Task 6: Verify, Merge to Main, Build, and Publish v0.1.1

**Files:**
- Verify all changed files from Tasks 1-5.
- No generated binaries are committed.

**Interfaces:**
- Consumes release-ready assets from the successful Windows workflow run for the merged `main` commit.
- Produces tag and GitHub Release `v0.1.1` with direct ZIP and EXE downloads.

- [ ] **Step 1: Run final local gates**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -q -rs -p no:cacheprovider
uv run python -m compileall -q main.py w3xtool
git diff --check
git status --short --branch
```

Expected: tests and compileall exit 0; only intended committed changes exist; branch is ahead of `origin/local`.

- [ ] **Step 2: Push `local`, then fast-forward it into `main`**

```bash
git push origin local
LOCAL_SHA=$(git rev-parse local)
git switch main
git pull --ff-only origin main
git merge --ff-only local
test "$(git rev-parse HEAD)" = "$LOCAL_SHA"
```

Expected: `local` is published, `main` advances without a merge commit, and `main` HEAD exactly equals the verified `local` SHA.

- [ ] **Step 3: Re-verify merged `main`, push it, and wait for its exact Windows run**

Use:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -q -rs -p no:cacheprovider
uv run python -m compileall -q main.py w3xtool
git diff --check
MAIN_SHA=$(git rev-parse HEAD)
git push origin main
RUN_ID=$(gh run list --repo HenTai-Miao/w3xray \
  --workflow "Windows package acceptance" \
  --branch main \
  --commit "$MAIN_SHA" \
  --limit 1 \
  --json databaseId \
  --jq '.[0].databaseId')
test -n "$RUN_ID"
gh run watch "$RUN_ID" --repo HenTai-Miao/w3xray --exit-status
gh run view "$RUN_ID" --repo HenTai-Miao/w3xray --json headSha,status,conclusion,jobs,url
```

Expected: `headSha` equals `MAIN_SHA`; onedir build/acceptance, onefile build/acceptance, asset preparation, and upload all conclude `success`.

- [ ] **Step 4: Download and verify release-ready assets in a task temp directory**

Create the task directory and download the exact artifact:

```bash
TEMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/codex-w3xray-v0.1.1.XXXXXX")
gh run download "$RUN_ID" \
  --repo HenTai-Miao/w3xray \
  --name w3xray-windows-release-assets \
  --dir "$TEMP_DIR"
```

Verify:

```bash
find "$TEMP_DIR" -maxdepth 2 -type f -print
unzip -tq "$TEMP_DIR/w3xray-v0.1.1-windows-x64.zip"
file "$TEMP_DIR/w3xray-v0.1.1-windows-x64.exe"
ZIP_SHA=$(shasum -a 256 "$TEMP_DIR/w3xray-v0.1.1-windows-x64.zip" | awk '{print $1}')
EXE_SHA=$(shasum -a 256 "$TEMP_DIR/w3xray-v0.1.1-windows-x64.exe" | awk '{print $1}')
test -n "$ZIP_SHA"
test -n "$EXE_SHA"
```

Expected: ZIP integrity passes; EXE is PE32+ x86-64; both hashes are recorded for release notes.

- [ ] **Step 5: Create the immutable release from the built commit**

Confirm `v0.1.1` does not exist, then run:

```bash
gh release create v0.1.1 \
  "$TEMP_DIR/w3xray-v0.1.1-windows-x64.zip" \
  "$TEMP_DIR/w3xray-v0.1.1-windows-x64.exe" \
  "$TEMP_DIR/windows-onedir-acceptance.json" \
  "$TEMP_DIR/windows-onefile-acceptance.json" \
  --repo HenTai-Miao/w3xray \
  --target "$MAIN_SHA" \
  --title "w3xray v0.1.1" \
  --notes "Windows ZIP and direct EXE, both accepted from main commit $MAIN_SHA. ZIP SHA-256: $ZIP_SHA. EXE SHA-256: $EXE_SHA. The direct EXE is unsigned and may show a SmartScreen warning; use the ZIP build if startup or antivirus compatibility is better there." \
  --latest
```

- [ ] **Step 6: Verify GitHub Release state and clean temp artifacts**

Run:

```bash
gh api repos/HenTai-Miao/w3xray/releases/latest
git ls-remote origin refs/tags/v0.1.1
git status --short --branch
rm -rf -- "$TEMP_DIR"
```

Expected: latest tag is `v0.1.1`; ZIP, direct EXE, and both acceptance reports have state `uploaded`; tag commit equals the workflow `headSha` and `main` HEAD; worktree is clean. Remove the task temp directory after verification.

Do not delete or retarget `v0.1.0`.
