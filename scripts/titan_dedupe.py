#!/usr/bin/env python3
"""Deterministic M3U normalizer/deduplicator for TITAN IPTV v2.
Keeps the first occurrence of each normalized URL and preserves metadata.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def normalize_url(url: str) -> str:
    url = url.strip()
    p = urlsplit(url)
    if p.scheme.lower() in {"http", "https"}:
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, p.query, ""))
    return url


def dedupe_m3u(text: str):
    lines = text.splitlines()
    out = []
    seen = set()
    removed = 0
    pending = []
    for line in lines:
        if line.startswith("#EXTINF"):
            pending = [line]
            continue
        if line.startswith("#") or not line.strip():
            if pending:
                pending.append(line)
            else:
                out.append(line)
            continue
        url = normalize_url(line)
        if url in seen:
            removed += 1
            pending = []
            continue
        seen.add(url)
        out.extend(pending)
        out.append(line.strip())
        pending = []
    return "\n".join(out).rstrip() + "\n", removed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    args = ap.parse_args()
    text = Path(args.input).read_text(encoding="utf-8", errors="replace")
    result, removed = dedupe_m3u(text)
    Path(args.output).write_text(result, encoding="utf-8")
    print(f"TITAN dedupe: removed={removed}")

if __name__ == "__main__":
    main()
