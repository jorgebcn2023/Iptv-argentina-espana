#!/usr/bin/env python3
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "playlists"
COUNTRIES = {"AR":"argentina","ES":"espana","IT":"italia","GB":"reino-unido","US":"estados-unidos","BR":"brasil"}

URL_RE = re.compile(r"^https?://", re.I)

def normalize_url(url: str) -> str:
    url = url.strip()
    if not URL_RE.match(url):
        return url
    p = urlsplit(url)
    scheme = p.scheme.lower()
    host = p.hostname.lower() if p.hostname else ""
    port = p.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc += f":{port}"
    return urlunsplit((scheme, netloc, p.path or "", p.query, ""))

def parse_m3u(text: str):
    lines = [x.rstrip("\r") for x in text.splitlines()]
    out=[]
    pending=None
    for line in lines:
        if line.startswith("#EXTINF:"):
            pending=line
        elif pending and URL_RE.match(line.strip()):
            out.append((pending, line.strip()))
            pending=None
    return out

def dedupe(entries):
    seen=set(); result=[]
    for meta,url in entries:
        key=normalize_url(url)
        if key in seen:
            continue
        seen.add(key); result.append((meta,url))
    return result

def country_from_meta(meta):
    m=re.search(r'(?:tvg-country|country)="([^"]+)"', meta, re.I)
    if m:
        return m.group(1).upper()
    return None

def write_playlist(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("#EXTM3U\n")
        for meta,url in entries:
            f.write(meta+"\n"+url+"\n")

def build(source_files):
    entries=[]
    for source in source_files:
        entries.extend(parse_m3u(Path(source).read_text(encoding="utf-8", errors="replace")))
    entries=dedupe(entries)
    write_playlist(OUT/"all.m3u", entries)
    for code,name in COUNTRIES.items():
        selected=[e for e in entries if country_from_meta(e[0])==code]
        write_playlist(OUT/f"{name}.m3u", selected)
    return len(entries)

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        raise SystemExit("Uso: build_playlist.py <m3u> [<m3u> ...]")
    print(f"TITAN: {build(sys.argv[1:])} entradas únicas")
