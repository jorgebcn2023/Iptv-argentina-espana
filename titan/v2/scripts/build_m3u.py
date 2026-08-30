#!/usr/bin/env python3
"""Build country-organized M3U files from normalized channel records."""
from __future__ import annotations
from pathlib import Path

def build(entries: list[dict], out_dir: str = "playlists") -> None:
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[dict]] = {}
    for entry in entries:
        country = entry.get("country", "unknown").lower().replace(" ", "-")
        grouped.setdefault(country, []).append(entry)
    for country, rows in grouped.items():
        lines = ["#EXTM3U"]
        for row in rows:
            title = row.get("name", "Unknown")
            url = row["url"]
            group = row.get("group", country)
            logo = row.get("logo", "")
            attrs = f' group-title="{group}"'
            if logo:
                attrs += f' tvg-logo="{logo}"'
            lines += [f"#EXTINF:-1{attrs},{title}", url]
        (root / f"{country}.m3u").write_text("\n".join(lines) + "\n", encoding="utf-8")
