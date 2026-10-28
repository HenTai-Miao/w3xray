"""Lossless evidence and typed results for explicit offline hotkey files."""

from __future__ import annotations

from dataclasses import dataclass


CONTRACT_BASIS = (
    "由 v2.0.0 静态读取合同重建；不是官方导出格式或实机兼容保证。"
    "仅检查用户明确选择的文件，不应用改键、不发送输入。"
)
CONTRACT_MODEL_SHA256 = (
    "470bfe76944f5e0a63d7651ae48405d4ffd9a4c608fa697d73a36dc16f971986"
)
CONTRACT_SAMPLE_SHA256 = (
    "96918355fd386afb7eabae8286e0a552c7dcbc81a239bc35e165fdc75529af41"
)


@dataclass(frozen=True, slots=True)
class JsonMember:
    """One object member, including every occurrence of a repeated key."""

    key: str
    node: int


@dataclass(frozen=True, slots=True)
class JsonNode:
    """Flat JSON syntax tree; numbers retain their original token spelling."""

    kind: str
    start: int
    end: int
    value: str | bool | None = None
    members: tuple[JsonMember, ...] = ()
    elements: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class HotkeyDiagnostic:
    code: str
    severity: str
    path: str
    message: str
    related: tuple[str, ...] = ()
    basis: str = "original_declaration"


@dataclass(frozen=True, slots=True)
class HotkeySource:
    path: str
    sha256: str = ""
    size: int = 0
    stable: bool = False
    identity: tuple[int, ...] = ()
    raw_base64: str = ""
    utf8_text: str | None = None
    utf8_bom: bool = False


@dataclass(frozen=True, slots=True)
class HotkeyBinding:
    ordinal: int
    path: str
    node: int
    binding_id: str | None
    declared_group: str | None
    compatible_id: str | None
    compatible_group: str | None
    source: str | None
    target: str | None
    canonical_source: str | None
    canonical_target: str | None


@dataclass(frozen=True, slots=True)
class CompatibleBinding:
    """Separately labelled projection, never a replacement for raw evidence."""

    binding_id: str
    source: str | None
    target: str | None
    enabled: bool | None
    smartcast: bool | None
    repeat: bool | None
    slot_index: int | None
    group: str | None
    origin_ordinal: int | None
    origin_path: str
    state: str
    slot_index_literal: str | None = None


@dataclass(frozen=True, slots=True)
class HotkeyProfile:
    name: str
    occurrence: int
    path: str
    node: int
    bindings: tuple[HotkeyBinding, ...]
    compatibility_bindings: tuple[CompatibleBinding, ...]
    compatibility_complete: bool
    bindings_coverage_complete: bool


@dataclass(frozen=True, slots=True)
class HotkeyInspection:
    source: HotkeySource
    nodes: tuple[JsonNode, ...]
    root: int | None
    profiles: tuple[HotkeyProfile, ...]
    profiles_total: int
    selected_profile: str | None
    diagnostics: tuple[HotkeyDiagnostic, ...]
    inspection_complete: bool
    input_error: bool
    contract_basis: str = CONTRACT_BASIS
    contract_model_sha256: str = CONTRACT_MODEL_SHA256
    contract_sample_sha256: str = CONTRACT_SAMPLE_SHA256
    runtime_verified: bool = False

    @property
    def has_findings(self) -> bool:
        return any(d.severity in {"warning", "error"} for d in self.diagnostics)

    @property
    def exit_code(self) -> int:
        if self.input_error or not self.inspection_complete:
            return 2
        return 1 if self.has_findings else 0


@dataclass(frozen=True, slots=True)
class HotkeyDifference:
    path: str
    kind: str
    before: str | None
    after: str | None
    old_node: int | None = None
    new_node: int | None = None


@dataclass(frozen=True, slots=True)
class HotkeyDiff:
    old: HotkeyInspection
    new: HotkeyInspection
    differences: tuple[HotkeyDifference, ...]
    diagnostics: tuple[HotkeyDiagnostic, ...]
    comparison_complete: bool
    has_changes: bool
    contract_basis: str = CONTRACT_BASIS
    runtime_verified: bool = False

    @property
    def exit_code(self) -> int:
        if not self.comparison_complete:
            return 2
        return (
            1
            if self.has_changes or self.old.has_findings or self.new.has_findings
            else 0
        )
