#!/usr/bin/env python3
from __future__ import annotations
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

URL_RE = re.compile(r"^https?://\S+$", re.I)


def normalize_url(url: str) -> str:
    url = url.strip()
    p = urlsplit(url)
    scheme = p.scheme.lower()
    host = p.hostname.lower() if p.hostname else ""
    port = p.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc += f":{port}"
    return urlunsplit((scheme, netloc, p.path or "", p.query, ""))


def merge_m3u(inputs: list[Path], output: Path) -> dict[str, int]:
    seen: set[str] = set()
    out: list[str] = ["#EXTM3U"]
    total = duplicates = accepted = 0
    pending: list[str] = []

    for path in inputs:
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                if line.startswith("#EXTINF"):
                    pending = [line]
                continue
            if not URL_RE.match(line):
                pending = []
                continue
            total += 1
            key = normalize_url(line)
            if key in seen:
                duplicates += 1
                pending = []
                continue
            seen.add(key)
            if pending:
                out.extend(pending)
            out.append(line)
            accepted += 1
            pending = []

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(out) + "\n", encoding="utf-8")
    return {"input_urls": total, "duplicates": duplicates, "accepted": accepted}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("inputs", nargs="+", type=Path)
    args = parser.parse_args()
    print(merge_m3u(args.inputs, args.output))
