from __future__ import annotations
from dataclasses import dataclass

@dataclass
class Entry:
    metadata: list[str]
    url: str

def parse_entries(text: str) -> list[Entry]:
    lines = [line.rstrip("\r") for line in text.splitlines()]
    entries: list[Entry] = []
    pending: list[str] = []

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            pending = [line]
            continue
        if line.startswith("#"):
            if pending:
                pending.append(line)
            continue
        if pending:
            entries.append(Entry(metadata=pending, url=line))
            pending = []
    return entries

def render_entry(entry: Entry) -> list[str]:
    return [*entry.metadata, entry.url]
