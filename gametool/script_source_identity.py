"""Resolve logical script labels using only already-loaded source names."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


def source_name_key(name: str) -> str:
    """Collapse separators and single-dot parts; never resolve parent traversal."""
    mapped = name.replace("\\", "/")
    root = (
        "//"
        if mapped.startswith("//") and not mapped.startswith("///")
        else "/"
        if mapped.startswith("/")
        else ""
    )
    return root + "/".join(part for part in mapped.split("/") if part not in {"", "."})


@dataclass(frozen=True, slots=True)
class ScriptSourceMatch:
    key: str
    sources: tuple[str, ...]
    method: str
    diagnostic: str = ""


class ScriptSourceNames:
    """Prefer complete names, then export prefixes, then a unique basename."""

    def __init__(self, names: Iterable[str]) -> None:
        exact: dict[str, list[str]] = {}
        folded: dict[str, list[str]] = {}
        basenames: dict[str, list[str]] = {}
        self.cache: dict[str, ScriptSourceMatch] = {}
        self._ambiguous_notes: dict[int, str] = {}
        for name in dict.fromkeys(names):
            key = source_name_key(name)
            exact.setdefault(key, []).append(name)
            folded.setdefault(key.casefold(), []).append(name)
            basenames.setdefault(key.rsplit("/", 1)[-1].casefold(), []).append(name)
        self.exact = {key: tuple(sorted(values)) for key, values in exact.items()}
        self.folded = {key: tuple(sorted(values)) for key, values in folded.items()}
        self.basenames = {
            key: tuple(sorted(values)) for key, values in basenames.items()
        }

    def _match(
        self, key: str, sources: tuple[str, ...], method: str
    ) -> ScriptSourceMatch:
        if len(sources) > 1:
            identity = id(sources)
            note = self._ambiguous_notes.get(identity)
            if note is None:
                note = (
                    "索引来源未唯一确定；请补全来源列的相对路径或重新导出知识包。"
                    f"{len(sources)} 个候选: " + ", ".join(sources)
                )
                self._ambiguous_notes[identity] = note
            return ScriptSourceMatch(
                key,
                sources,
                "ambiguous",
                note,
            )
        return ScriptSourceMatch(sources[0] if sources else key, sources, method)

    def resolve(self, name: str) -> ScriptSourceMatch:
        cached = self.cache.get(name)
        if cached is not None:
            return cached
        key = source_name_key(name)
        parts = key.split("/")
        if ".." in parts:
            result = ScriptSourceMatch(
                key,
                (),
                "unsafe",
                "索引来源含上级目录，未猜测来源或独立确认点位；请核对来源列或重新导出",
            )
        elif candidates := self.exact.get(key):
            result = self._match(key, candidates, "exact")
        elif candidates := self.folded.get(key.casefold()):
            result = self._match(key, candidates, "casefold")
        else:
            prefixed: list[str] = []
            for index, part in enumerate(parts[:-1]):
                if part.casefold() == "脚本可读文本".casefold():
                    suffix = "/".join(parts[index + 1 :])
                    prefixed.extend(
                        self.exact.get(suffix) or self.folded.get(suffix.casefold(), ())
                    )
            if prefixed:
                result = self._match(key, tuple(sorted(set(prefixed))), "export-prefix")
            else:
                candidates = self.basenames.get(parts[-1].casefold(), ())
                result = self._match(
                    key, candidates, "basename" if candidates else "missing"
                )
        self.cache[name] = result
        return result
