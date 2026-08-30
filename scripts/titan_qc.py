#!/usr/bin/env python3
"""Static QC for TITAN-generated M3U files."""
from __future__ import annotations
import argparse
from pathlib import Path
from urllib.parse import urlsplit


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("playlist")
    args=ap.parse_args()
    lines=Path(args.playlist).read_text(encoding="utf-8",errors="replace").splitlines()
    if not lines or lines[0].strip() != "#EXTM3U":
        raise SystemExit("QC FAIL: missing #EXTM3U")
    urls=[x.strip() for x in lines if x.strip() and not x.startswith("#")]
    bad=[u for u in urls if urlsplit(u).scheme not in {"http","https"}]
    duplicates=len(urls)-len(set(urls))
    if bad: raise SystemExit(f"QC FAIL: invalid URL schemes={len(bad)}")
    if duplicates: raise SystemExit(f"QC FAIL: duplicate URLs={duplicates}")
    print(f"QC PASS: entries={len(urls)} unique_urls={len(set(urls))}")

if __name__ == "__main__":
    main()
