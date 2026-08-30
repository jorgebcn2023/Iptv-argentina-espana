#!/usr/bin/env python3
"""TITAN v2 postprocessor: deduplicate generated M3U playlists by stream URL only.
Keeps the first metadata record for each normalized URL and writes a machine-readable report.
"""
from __future__ import annotations
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

FILES = ["playlist.m3u", "playlist-full.m3u", "playlist-quarantine.m3u", "youtube-live.m3u"]

def norm_url(url: str) -> str:
    u = url.strip()
    if not u:
        return ""
    try:
        p = urlsplit(u)
        scheme = p.scheme.lower()
        host = (p.hostname or "").lower()
        port = p.port
        netloc = host
        if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
            netloc += f":{port}"
        return urlunsplit((scheme, netloc, p.path, p.query, p.fragment))
    except ValueError:
        return u.lower()

def process(path: Path) -> dict:
    if not path.exists():
        return {"file": str(path), "present": False, "input": 0, "output": 0, "removed": 0}
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    seen = set()
    current = []
    input_entries = 0
    removed = []
    for line in lines:
        if line.startswith("#EXTINF"):
            if current:
                out.extend(current)
            current = [line]
        elif current:
            current.append(line)
            if line.strip() and not line.startswith("#"):
                input_entries += 1
                key = norm_url(line)
                if key in seen:
                    removed.append(key)
                    current = []
                else:
                    seen.add(key)
    if current:
        out.extend(current)
    output_entries = sum(1 for x in out if x.startswith("#EXTINF"))
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return {"file": str(path), "present": True, "input": input_entries, "output": output_entries, "removed": len(removed), "removed_urls": removed[:500]}

def main() -> int:
    report = {"mode": "url_only", "files": [process(Path(x)) for x in FILES]}
    Path("titan-dedupe-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
