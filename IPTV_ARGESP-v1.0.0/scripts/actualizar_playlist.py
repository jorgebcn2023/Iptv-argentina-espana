from __future__ import annotations

from pathlib import Path
import hashlib
import logging
import tempfile
import time

import requests
import yaml

from m3u_parser import parse_entries, render_entry

BASE = Path(__file__).resolve().parents[1]
SOURCES = BASE / "config/sources.yml"
SETTINGS = BASE / "config/settings.yml"
CACHE = BASE / "downloads"
OUTPUT = BASE / "playlists/playlist_IPTV_ARG_ESP_FINAL.m3u"

def load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def cache_path(source):
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(source["url"].encode()).hexdigest()[:16]
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in source["name"])
    return CACHE / f"{safe}-{key}.m3u"

def fetch(source, timeout, retries, delay, user_agent):
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(
                source["url"],
                timeout=timeout,
                headers={"User-Agent": user_agent},
                allow_redirects=True,
            )
            r.raise_for_status()
            text = r.text
            if not parse_entries(text):
                raise ValueError("Fuente M3U/M3U8 vacía o inválida")
            return text
        except Exception as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(delay)
    raise RuntimeError(last)

def atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as f:
        f.write(text)
        f.flush()
        tmp = Path(f.name)
    tmp.replace(path)

def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    settings = load_yaml(SETTINGS)
    upd = settings.get("update", {})
    timeout = int(upd.get("timeout_seconds", 30))
    retries = int(upd.get("retries", 3))
    delay = int(upd.get("retry_delay_seconds", 3))
    ua = str(upd.get("user_agent", "IPTV-Argentina-Espana/1.0"))

    sources = [
        s for s in load_yaml(SOURCES).get("sources", [])
        if s.get("enabled", True)
    ]

    collected = []
    failed = []

    for source in sorted(sources, key=lambda s: s.get("priority", 100)):
        cache = cache_path(source)
        try:
            text = fetch(source, timeout, retries, delay, ua)
            cache.write_text(text, encoding="utf-8")
            collected.append(text)
            logging.info("OK %s", source["name"])
        except Exception as exc:
            if cache.exists():
                collected.append(cache.read_text(encoding="utf-8"))
                logging.warning("Falla %s; usando caché: %s", source["name"], exc)
            else:
                failed.append(source["name"])
                logging.error("Falla %s sin caché: %s", source["name"], exc)

    if not collected:
        logging.error("Todas las fuentes fallaron; se conserva la playlist actual")
        return 1

    blocked = [x.casefold() for x in load_yaml(SETTINGS).get("filter", {}).get("blocked_keywords", [])]
    seen_urls = set()
    out = ["#EXTM3U"]

    for text in collected:
        for entry in parse_entries(text):
            if entry.url in seen_urls:
                continue
            extinf = entry.metadata[0] if entry.metadata else ""
            if any(word in extinf.casefold() for word in blocked):
                continue
            seen_urls.add(entry.url)
            out.extend(render_entry(entry))

    atomic_write(OUTPUT, "\n".join(out) + "\n")
    logging.info("Playlist generada con %d streams", len(seen_urls))
    if failed:
        logging.warning("Fuentes fallidas: %s", ", ".join(failed))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
