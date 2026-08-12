"""Actualiza la playlist IPTV desde todas las fuentes configuradas."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import logging
import tempfile
import time

import requests
import yaml

BASE = Path(__file__).resolve().parents[1]
CONFIG = BASE / "config"
DOWNLOADS = BASE / "downloads"
PLAYLIST_DIR = BASE / "playlists"
PLAYLIST = PLAYLIST_DIR / "playlist_IPTV_ARG_ESP_FINAL.m3u"

SOURCES_FILE = CONFIG / "sources.yml"
TIMEOUT = 30
RETRIES = 3
RETRY_DELAY = 3
USER_AGENT = "IPTV-Argentina-Espana/0.3.1"

@dataclass
class Entry:
    extinf: str
    url: str

def load_sources() -> list[dict]:
    with SOURCES_FILE.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return [s for s in data.get("sources", []) if s.get("enabled", True)]

def parse_entries(text: str) -> list[Entry]:
    lines = [x.strip() for x in text.splitlines()]
    result: list[Entry] = []
    for i, line in enumerate(lines[:-1]):
        if line.startswith("#EXTINF"):
            url = lines[i + 1]
            if url and not url.startswith("#"):
                result.append(Entry(line, url))
    return result

def cache_file(source: dict) -> Path:
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(source["url"].encode("utf-8")).hexdigest()[:16]
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in source["name"])
    return DOWNLOADS / f"{safe}-{key}.m3u"

def fetch(source: dict) -> str:
    last_error = None
    for attempt in range(1, RETRIES + 1):
        try:
            response = requests.get(
                source["url"],
                timeout=TIMEOUT,
                headers={"User-Agent": USER_AGENT},
                allow_redirects=True,
            )
            response.raise_for_status()
            text = response.text
            entries = parse_entries(text)
            if not entries:
                raise ValueError("La fuente no contiene entradas M3U válidas")
            return text
        except Exception as exc:
            last_error = exc
            if attempt < RETRIES:
                time.sleep(RETRY_DELAY)
    raise RuntimeError(f"{source['name']}: {last_error}")

def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as tmp:
        tmp.write(content)
        tmp.flush()
        tmp_name = tmp.name
    Path(tmp_name).replace(path)

def build_playlist(texts: list[str]) -> tuple[str, int]:
    seen_urls: set[str] = set()
    lines = ["#EXTM3U"]

    for text in texts:
        for entry in parse_entries(text):
            url = entry.url.strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            lines.extend((entry.extinf, url))

    return "
".join(lines) + "
", len(seen_urls)

def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sources = load_sources()

    valid_texts: list[str] = []
    failed: list[str] = []

    for source in sources:
        cache = cache_file(source)
        try:
            text = fetch(source)
            cache.write_text(text, encoding="utf-8")
            valid_texts.append(text)
            logging.info("OK: %s", source["name"])
        except Exception as exc:
            if cache.exists():
                valid_texts.append(cache.read_text(encoding="utf-8"))
                logging.warning("Falla %s; usando caché: %s", source["name"], exc)
            else:
                failed.append(source["name"])
                logging.error("Falla %s sin caché: %s", source["name"], exc)

    if not valid_texts:
        logging.error("Todas las fuentes fallaron; se conserva la playlist existente")
        return 1

    playlist, count = build_playlist(valid_texts)
    atomic_write(PLAYLIST, playlist)
    logging.info("Playlist generada: %d streams", count)

    if failed:
        logging.warning("Fuentes sin datos: %s", ", ".join(failed))

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
