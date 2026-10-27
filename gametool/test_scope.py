"""Explicit Windows product and independent native-contract test scopes."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

import pytest

_REPOSITORY = Path(__file__).resolve().parents[1]
_MANIFEST = _REPOSITORY / "retired_contract_tests" / "scope-manifest.json"
_SCOPE_ENV = "GAMEXRAY_TEST_SCOPE"
_PLUGIN_NAME = "gamexray-strict-test-scope"


class ScopeRequestError(ValueError):
    """An explicitly selected test scope lacks its required runtime or inputs."""


@dataclass(frozen=True, slots=True)
class ScopeRequest:
    name: str
    arguments: tuple[str, ...]
    environment: dict[str, str]


def prepare_test_scope(arguments: tuple[str, ...]) -> ScopeRequest:
    """Choose a physical suite before pytest; missing real inputs are errors."""
    parser = argparse.ArgumentParser(add_help=False, exit_on_error=False)
    parser.add_argument(
        "--suite", choices=("windows", "real-data", "retired-posix"), default="windows"
    )
    parser.add_argument("--lane", choices=("all", "casc", "historical"))
    for option in ("war3-dir", "maps-root", "old-output", "new-output"):
        parser.add_argument("--" + option)
    try:
        options, forwarded = parser.parse_known_args(arguments)
    except (argparse.ArgumentError, SystemExit) as exc:
        raise ScopeRequestError(str(exc)) from exc
    environment = {_SCOPE_ENV: options.suite}
    if options.suite == "windows":
        if sys.platform != "win32":
            raise ScopeRequestError(
                "默认回归仅支持 Windows；独立 POSIX 契约需显式 --suite retired-posix。"
            )
        if options.lane or any(
            getattr(options, key)
            for key in ("war3_dir", "maps_root", "old_output", "new_output")
        ):
            raise ScopeRequestError("真实输入选项必须同时显式选择 --suite real-data。")
    elif options.suite == "retired-posix":
        if sys.platform != "darwin" and not sys.platform.startswith("linux"):
            raise ScopeRequestError(
                "退役 POSIX 原语契约不能在 Windows 冒充执行；请使用支持的 native runtime。"
            )
        forwarded.append(str(_REPOSITORY / "retired_contract_tests" / "posix"))
    else:
        if sys.platform != "win32":
            raise ScopeRequestError("真实安装/历史输入验收仅支持 Windows。")
        lane = options.lane or "all"
        targets: list[str] = []
        required: list[tuple[str, str | None]] = []
        if lane in {"all", "casc"}:
            required.append(("GAMEXRAY_WAR3_DIR", options.war3_dir))
            targets.append(
                str(
                    _REPOSITORY
                    / "real_data_acceptance"
                    / "test_casclib_windows_integration.py"
                )
            )
        if lane in {"all", "historical"}:
            required.extend(
                (
                    ("GAMEXRAY_MAPS_ROOT", options.maps_root),
                    ("GAMEXRAY_OLD_OUTPUT", options.old_output),
                    ("GAMEXRAY_NEW_OUTPUT", options.new_output),
                )
            )
            targets.append(
                str(
                    _REPOSITORY
                    / "real_data_acceptance"
                    / "test_real_map_item_relation_acceptance.py"
                )
            )
        for variable, supplied in required:
            value = supplied or os.environ.get(variable)
            if not value or not Path(value).is_dir():
                raise ScopeRequestError(
                    f"显式真实数据验收缺少可读目录：{variable}；没有执行或跳过该验收。"
                )
            environment[variable] = str(Path(value).resolve())
        if "GAMEXRAY_WAR3_DIR" in environment:
            root = Path(environment["GAMEXRAY_WAR3_DIR"])
            if (
                not (root / ".build.info").is_file()
                or not (root / "Data" / "data").is_dir()
            ):
                raise ScopeRequestError(
                    "真实 CASC 验收需要 .build.info 与 Data/data；Classic MPQ 不能替代。"
                )
        forwarded.extend(targets)
    if any(
        value in {"no:gametool.test_scope", "no:gamexray-strict-test-scope"}
        for value in forwarded
    ):
        raise ScopeRequestError("不能关闭受支持回归的严格结果门禁。")
    return ScopeRequest(options.suite, tuple(forwarded) or ("-q",), environment)


def load_scope_manifest() -> dict[str, Any]:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1:
        raise ScopeRequestError("未知测试范围清单版本。")
    return value


def verify_retired_contracts() -> None:
    """Prove every moved function still has its complete original AST."""
    import ast

    manifest = load_scope_manifest()
    modules: dict[str, dict[str, str]] = {}
    for record in (
        *manifest["retired_functions"],
        *manifest.get("reference_integrations", ()),
    ):
        relative = record["new_module"]
        if relative not in modules:
            path = _REPOSITORY / relative
            if not path.resolve().is_relative_to(
                _REPOSITORY / "retired_contract_tests"
            ):
                raise ScopeRequestError(f"退役范围清单越界：{relative}")
            tree = ast.parse(path.read_text(encoding="utf-8"))
            modules[relative] = {
                node.name: hashlib.sha256(
                    ast.dump(node, include_attributes=False).encode()
                ).hexdigest()
                for node in tree.body
                if isinstance(node, ast.FunctionDef)
            }
        actual = modules[relative].get(record["original_function"])
        if actual != record["original_function_ast_sha256"]:
            raise ScopeRequestError(
                f"退役安全契约 AST 已改变或丢失：{relative}::{record['original_function']}"
            )


class StrictScopePolicy:
    """Reject every skipped/xfail outcome without changing any test result."""

    def __init__(self) -> None:
        self.scope = os.environ.get(_SCOPE_ENV, "windows")
        self.collected: list[str] = []
        self.unexpected: list[dict[str, str]] = []
        self.passed: set[str] = set()
        self.report_path: Path | None = None

    def pytest_sessionstart(self, session: pytest.Session) -> None:
        from .test_environment import create_test_environment

        del session
        environment = create_test_environment()
        self.report_path = Path(environment["GAMEXRAY_CACHE_DIR"]) / "test-scope.json"

    def pytest_collection_modifyitems(
        self, session: pytest.Session, items: list[pytest.Item]
    ) -> None:
        self.collected = [item.nodeid for item in items]
        if self.scope != "windows":
            return
        manifest = load_scope_manifest()
        retired = {
            (row["old_module"], row["original_function"])
            for row in manifest["retired_functions"]
        }
        observed: set[tuple[str, str | None]] = set()
        for item in items:
            path = Path(str(item.path)).resolve()
            if path.is_relative_to(
                _REPOSITORY / "retired_contract_tests"
            ) or path.is_relative_to(_REPOSITORY / "real_data_acceptance"):
                raise pytest.UsageError(
                    "该物理测试目录必须通过显式 --suite 入口执行，不能混入 Windows 产品回归。"
                )
            relative = (
                path.relative_to(_REPOSITORY).as_posix()
                if path.is_relative_to(_REPOSITORY)
                else str(path)
            )
            original = (
                item.originalname if isinstance(item, pytest.Function) else item.name
            )
            observed.add((relative, original))
            if (relative, original) in retired:
                raise pytest.UsageError(
                    f"退役 native 契约仍混入 Windows 产品目录：{item.nodeid}"
                )
        full_suite = bool(session.config.args) and all(
            Path(argument).resolve() == _REPOSITORY / "tests"
            for argument in session.config.args
        )
        if full_suite:
            verify_retired_contracts()
            missing = [
                (row["module"], row["function"])
                for row in manifest["required_windows_functions"]
                if (row["module"], row["function"]) not in observed
            ]
            if missing:
                raise pytest.UsageError(
                    "Windows 必需契约未被收集："
                    + ", ".join(f"{module}::{name}" for module, name in missing)
                )

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.skipped:
            self.unexpected.append(
                {
                    "nodeid": report.nodeid,
                    "phase": "collect",
                    "outcome": "skipped",
                    "detail": str(report.longrepr),
                }
            )

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        xfail = getattr(report, "wasxfail", None)
        if report.skipped or xfail is not None:
            self.unexpected.append(
                {
                    "nodeid": report.nodeid,
                    "phase": report.when,
                    "outcome": "xfail/xpass" if xfail is not None else "skipped",
                    "detail": str(report.longrepr),
                }
            )
        elif report.when == "call" and report.passed:
            self.passed.add(report.nodeid)

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if self.unexpected and int(exitstatus) == 0:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
        manifest = load_scope_manifest()
        report = {
            "schema": "gamexray-test-scope",
            "schema_version": 1,
            "scope": self.scope,
            "exit_code": int(session.exitstatus),
            "selected_nodeids": self.collected,
            "passed_nodeids": sorted(self.passed),
            "unexpected_outcomes": self.unexpected,
            "retired_contracts": manifest["retired_cases"]
            if self.scope == "windows"
            else [],
            "real_data_not_requested": manifest["real_data_cases"]
            if self.scope == "windows"
            else [],
            "manifest_sha256": hashlib.sha256(_MANIFEST.read_bytes()).hexdigest(),
        }
        try:
            if self.report_path is None:
                raise OSError("范围报告未分配私有目录")
            with self.report_path.open("x", encoding="utf-8") as handle:
                json.dump(report, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        except OSError as exc:
            if int(session.exitstatus) == 0:
                session.exitstatus = pytest.ExitCode.TESTS_FAILED
            print(f"测试范围证据写入失败：{exc}", file=sys.stderr)
        if self.unexpected:
            print(
                "Windows/显式测试范围拒绝任何 skip、xfail 或 xpass：", file=sys.stderr
            )
            for item in self.unexpected:
                print(
                    f"  {item['nodeid']}: {item['outcome']} {item['detail']}",
                    file=sys.stderr,
                )
        print(f"\nTEST-SCOPE {self.scope}: {self.report_path}")


def install_scope_policy(config: pytest.Config) -> None:
    if not config.pluginmanager.hasplugin(_PLUGIN_NAME):
        config.pluginmanager.register(StrictScopePolicy(), _PLUGIN_NAME)


def pytest_configure(config: pytest.Config) -> None:
    install_scope_policy(config)
