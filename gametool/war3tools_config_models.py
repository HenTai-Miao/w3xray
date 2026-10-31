"""Immutable, lossless evidence for explicitly selected War3Tools INI files."""

from __future__ import annotations

from dataclasses import asdict, dataclass


CONFIGURATION_NOTICE = (
    "仅解释所选 War3Tools 配置的离线声明，不证明功能已在游戏中生效。"
    "不加载程序或 DLL，不执行地图，不应用改键或修改配置。"
)


@dataclass(frozen=True, slots=True)
class War3ToolsDiagnostic:
    code: str
    severity: str
    source: str
    message: str
    line: int | None = None
    related_lines: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class War3ToolsInventoryEntry:
    path: str
    relative_path: str
    kind: str
    suffix: str
    size: int
    identity: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class War3ToolsSource:
    path: str
    relative_path: str
    sha256: str = ""
    size: int = 0
    identity: tuple[int, ...] = ()
    raw_base64: str = ""
    raw_text: str | None = None
    encoding: str = ""
    requested_encoding: str = "auto"
    bom_bytes: int = 0
    stable: bool = False
    status: str = "unread"


@dataclass(frozen=True, slots=True)
class War3ToolsRecord:
    """One physical INI line; raw includes its exact original line ending."""

    ordinal: int
    line: int
    kind: str
    raw: str
    byte_offset: int
    byte_end: int
    section: str = ""
    section_occurrence: int = 0
    key: str | None = None
    value: str | None = None


@dataclass(frozen=True, slots=True)
class War3ToolsSetting:
    source: str
    line: int
    section: str
    section_occurrence: int
    key: str
    value: str
    category: str
    kind: str
    label: str
    state: str
    interpreted: str | bool | None = None
    basis: str = "observed_configuration_schema"


@dataclass(frozen=True, slots=True)
class War3ToolsFile:
    source: War3ToolsSource
    records: tuple[War3ToolsRecord, ...]
    settings: tuple[War3ToolsSetting, ...]
    diagnostics: tuple[War3ToolsDiagnostic, ...]
    complete: bool


@dataclass(frozen=True, slots=True)
class War3ToolsBinding:
    source: str
    line: int
    section: str
    section_occurrence: int
    group: str
    index: str
    key: str
    key_code: int | None
    key_name: str
    target: str | None
    state: str
    enabled: bool | None
    activation: tuple[str, ...]
    activation_proven: bool
    modifiers: tuple[str, ...] = ()
    related_lines: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class War3ToolsConflict:
    key_code: int
    key_name: str
    state: str
    message: str
    binding_indexes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class War3ToolsInspection:
    path: str
    selection_kind: str
    text_encoding: str
    inventory: tuple[War3ToolsInventoryEntry, ...]
    files: tuple[War3ToolsFile, ...]
    bindings: tuple[War3ToolsBinding, ...]
    conflicts: tuple[War3ToolsConflict, ...]
    diagnostics: tuple[War3ToolsDiagnostic, ...]
    inventory_complete: bool
    inspection_complete: bool
    input_error: bool
    root_identity: tuple[int, ...] = ()
    stable: bool = False
    runtime_verified: bool = False
    notice: str = CONFIGURATION_NOTICE

    @property
    def files_total(self) -> int:
        return len(self.files)

    @property
    def records_total(self) -> int:
        return sum(len(file.records) for file in self.files)

    @property
    def settings_total(self) -> int:
        return sum(len(file.settings) for file in self.files)

    @property
    def has_findings(self) -> bool:
        return bool(self.conflicts) or any(
            diagnostic.severity in {"warning", "error"}
            for diagnostic in self.diagnostics
        )

    @property
    def exit_code(self) -> int:
        if self.input_error or not self.inspection_complete or not self.stable:
            return 2
        return 1 if self.has_findings else 0

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "report_type": "war3tools_configuration_inspection",
            "report_is_configuration": False,
            "exit_code": self.exit_code,
            "files_total": self.files_total,
            "records_total": self.records_total,
            "settings_total": self.settings_total,
            **asdict(self),
        }

    def render(self) -> str:
        """Full human-readable evidence, with no implicit file or record limits."""
        lines = [
            "GameXRay War3Tools 离线配置检查",
            self.notice,
            f"来源: {self.path}",
            f"INI 文件 {self.files_total}；原始行 {self.records_total}；设置声明 {self.settings_total}；完整: {self.inspection_complete}；稳定: {self.stable}；退出码: {self.exit_code}",
            "== 完整文件库存 ==",
        ]
        lines.extend(
            f"[{entry.kind}] {entry.relative_path} · {entry.size} 字节"
            for entry in self.inventory
        )
        for file in self.files:
            source = file.source
            lines.extend(
                (
                    "",
                    f"== {source.relative_path} ==",
                    f"来源: {source.path}",
                    f"SHA-256: {source.sha256 or '未取得'} · 编码: {source.encoding or '未确认'} · BOM {source.bom_bytes} 字节 · 稳定: {source.stable}",
                )
            )
            for setting in file.settings:
                rendered = (
                    "开"
                    if setting.interpreted is True
                    else "关"
                    if setting.interpreted is False
                    else str(setting.interpreted)
                    if setting.interpreted is not None
                    else "未解释"
                )
                lines.append(
                    f"L{setting.line} [{setting.section}] {setting.key}={setting.value} · {setting.label} · {setting.state} · {rendered}"
                )
            lines.append("完整原文（含空行、注释、未知字段及重复声明）:")
            lines.append(
                source.raw_text
                if source.raw_text is not None
                else "未确认文本；完整原始字节 Base64:\n" + source.raw_base64
            )
        lines.extend(
            (
                "",
                "== 按键声明 ==",
                "键名按 Windows 虚拟键码表辅助显示；模式与修饰键枚举保持原声明，配置不证明运行激活。",
            )
        )
        for binding in self.bindings:
            lines.append(
                f"{binding.source}:L{binding.line} · {binding.group}{binding.index} · {binding.key_name} → {binding.target or '未声明/未解释目标'} · 开关={binding.enabled} · {binding.state}"
            )
            lines.append(
                "  声明条件: " + "; ".join((*binding.activation, *binding.modifiers))
            )
        lines.extend(("", "== 同键检查 =="))
        lines.extend(
            f"[{conflict.state}] {conflict.key_name} · 绑定索引 {conflict.binding_indexes} · {conflict.message}"
            for conflict in self.conflicts
        )
        if not self.conflicts:
            lines.append("未发现已读非空声明中的潜在同键项；不能据此保证运行时无冲突。")
        lines.extend(("", "== 完整诊断 =="))
        lines.extend(
            f"[{note.severity}/{note.code}] {note.source}"
            + (f":L{note.line}" if note.line is not None else "")
            + f": {note.message}"
            + (f" 相关行: {note.related_lines}" if note.related_lines else "")
            for note in self.diagnostics
        )
        lines.extend(
            (
                "",
                "选择实际 INI/配置目录后可重新检查；未知字段与 packed hex 数据需原格式说明或实现依据才能解释。",
            )
        )
        return "\n".join(lines) + "\n"
