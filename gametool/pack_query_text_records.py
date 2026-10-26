"""Complete CSV/TSV text records with their original encoded evidence."""

from collections.abc import Generator, Iterable, Iterator
import csv
from dataclasses import dataclass

from .csv_fields import full_csv_fields


@dataclass(frozen=True, slots=True)
class TextRecord:
    cells: tuple[str, ...]
    text: str

    def matches(self, query: str, *, ignore_case: bool = False) -> bool:
        """Search encoded evidence and decoded values without changing either."""
        if ignore_case:
            needle = query.casefold()
            return needle in self.text.casefold() or any(
                needle in cell.casefold() for cell in self.cells
            )
        return query in self.text or any(query in cell for cell in self.cells)


def tsv_records(lines: Iterable[str]) -> Generator[TextRecord, None, None]:
    """Keep complete quoted records, raw newlines and full decoded fields."""
    pending: list[str] = []

    def observed_lines() -> Iterator[str]:
        for line in lines:
            pending.append(line)
            yield line

    reader = csv.reader(observed_lines(), delimiter="\t")
    while True:
        # Restore process-global CSV settings before yielding to a consumer.
        # A partially consumed record iterator must not retain the shared lock.
        with full_csv_fields():
            try:
                cells = next(reader)
            except StopIteration:
                return
        text = "".join(pending)
        pending.clear()
        if text.endswith("\r\n"):
            text = text[:-2]
        elif text.endswith(("\n", "\r")):
            text = text[:-1]
        yield TextRecord(tuple(cells), text)
