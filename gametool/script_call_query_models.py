"""Complete source-call and original index evidence returned by pack queries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .pack_query_script_coverage import ScriptCoverage
from .pack_query_script_snapshot import ScriptPackSnapshotIdentity

if TYPE_CHECKING:
    from .script_behavior_index import ScriptBehaviorCall, ScriptBehaviorDiagnostic


@dataclass(frozen=True, slots=True)
class ScriptCallQueryDiagnostic:
    source: str
    code: str
    message: str
    raw: str = ""
    ordinal: int | None = None
    core: ScriptBehaviorDiagnostic | None = None

    def render(self) -> str:
        location = self.source
        if self.ordinal is not None:
            location += f" / 逻辑记录 {self.ordinal}"
        return f"[⚠ {location} — {self.code}: {self.message}]" + (
            "\n    完整证据: " + self.raw if self.raw else ""
        )


@dataclass(frozen=True, slots=True)
class ScriptCallIndexRow:
    """The original logical record and its separately normalized semantic roles."""

    path: str
    ordinal: int
    cells: tuple[str, ...]
    raw: str
    semantic_cells: tuple[str, ...] = ()
    file_fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class ScriptCallQueryRecord:
    """One source site or one explicitly unverified index/diagnostic record."""

    origin: str
    source: str
    language: str
    line: str
    offset: str
    callee: str
    owner: str
    binding: str
    arguments: tuple[str, ...]
    raw: str
    call: ScriptBehaviorCall | None = None
    index_rows: tuple[ScriptCallIndexRow, ...] = ()
    diagnostics: tuple[ScriptCallQueryDiagnostic, ...] = ()
    source_file_fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class ScriptCallQueryResult:
    lines: tuple[str, ...]
    calls: tuple[ScriptCallQueryRecord, ...]
    total: int
    omitted: int
    diagnostics: tuple[ScriptCallQueryDiagnostic, ...]
    has_matches: bool
    input_error: bool
    source_stable: bool
    script_coverage: ScriptCoverage
    snapshot_identity: ScriptPackSnapshotIdentity | None = None
