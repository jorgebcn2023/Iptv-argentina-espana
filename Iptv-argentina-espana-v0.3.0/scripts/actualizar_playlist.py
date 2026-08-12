from pathlib import Path
from dataclasses import dataclass
import hashlib
import logging
import tempfile

import requests
import yaml

BASE = Path(__file__).resolve().parents[1]
SOURCES = BASE / "config" / "sources.yml"
OUTPUT = BASE / "playlists" / "playlist_IPTV_ARG_ESP_FINAL.m3u"
CACHE = BASE / "downloads"

TIMEOUT = 30
RETRIES = 3
USER_AGENT = "IPTV-Manager/0.3.1"


@dataclass
class Entry:
    extinf: str
    url: str


def load_sources():
    with SOURCES.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def parse_m3u(text):
    lines = [x.strip() for x in text.splitlines()]
    out = []
    for i, line in enumerate(lines[:-1]):
        if line.startswith("#EXTINF"):
            url = lines[i + 1]
            if url and not url.startswith("#"):
                out.append(Entry(line, url))
    return out


def fetch(url):
    last = None
    for _ in range(RETRIES):
        try:
            r = requests.get(
                url,
                timeout=TIMEOUT,
                headers={"User-Agent": USER_AGENT},
                allow_redirects=True,
            )
            r.raise_for_status()
            text = r.text
            if "#EXTINF" not in text or not parse_m3u(text):
                raise ValueError("Fuente M3U vacía o inválida")
            return text
        except Exception as exc:
            last = exc
    raise last


def cache_path(name, url):
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    CACHE.mkdir(parents=True, exist_ok=True)
    return CACHE / f"{name}-{key}.m3u"


def write_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as tmp:
        tmp.write(text)
        name = tmp.name
    Path(name).replace(path)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sources = load_sources().get("sources", [])
    collected = []
    failed = []

    for src in sources:
        if not src.get("enabled", True):
            continue
        name = src["name"]
        url = src["url"]
        cache = cache_path(name, url)
        try:
            text = fetch(url)
            cache.write_text(text, encoding="utf-8")
            collected.append(text)
            logging.info("OK: %s", name)
        except Exception as exc:
            if cache.exists():
                collected.append(cache.read_text(encoding="utf-8"))
                logging.warning("Falla %s; usando caché: %s", name, exc)
            else:
                failed.append(name)
                logging.error("Falla %s sin caché: %s", name, exc)

    if not collected:
        logging.error("Ninguna fuente válida; no se modifica la playlist")
        return 1

    seen_urls = set()
    lines = ["#EXTM3U"]

    for text in collected:
        for entry in parse_m3u(text):
            if entry.url in seen_urls:
                continue
            seen_urls.add(entry.url)
            lines.extend([entry.extinf, entry.url])

    write_atomic(OUTPUT, "\n".join(lines) + "\n")
    logging.info("Playlist generada con %d streams", len(seen_urls))

    if failed:
        logging.warning("Fuentes sin datos: %s", ", ".join(failed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
