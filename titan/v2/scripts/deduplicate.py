#!/usr/bin/env python3
"""Deduplicate M3U entries by normalized stream URL."""
from __future__ import annotations
import re
from urllib.parse import urlsplit, urlunsplit

def normalize_url(url: str) -> str:
    url = url.strip()
    p = urlsplit(url)
    if not p.scheme or not p.netloc:
        return url
    path = re.sub(r"/{2,}", "/", p.path)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, p.query, ""))

def deduplicate(entries: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen = set()
    result = []
    for title, url in entries:
        key = normalize_url(url)
        if key in seen:
            continue
        seen.add(key)
        result.append((title, url.strip()))
    return result
