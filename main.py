import logging
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import monotonic

import requests
import yaml
from requests.exceptions import RequestException

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

USER_AGENT = "IPTV-Argentina-Espana/2.1"
DEFAULT_SOURCE_TIMEOUT = 20
DEFAULT_PROBE_TIMEOUT = 8
DEFAULT_WORKERS = 20


def normalize_text(s: str) -> str:
    if s is None:
        return ""
    nk = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in nk if not unicodedata.combining(c)).lower().strip()


def load_yaml(path: str):
    try:
        with open(path, "r", encoding="utf8") as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        logging.error("Archivo no encontrado: %s", path)
        return {}
    except Exception as e:
        logging.error("Error leyendo %s: %s", path, e)
        return {}


def channel_name(extinf: str) -> str:
    pos = extinf.rfind(",")
    return extinf[pos + 1:].strip() if pos >= 0 else "Unknown"


def group_name(extinf: str) -> str:
    match = re.search(r'group-title=["\']([^"\']*)["\']', extinf, re.I)
    return match.group(1).strip() if match else ""


def country_code(extinf: str) -> str:
    match = re.search(r'tvg-country=["\']([^"\']*)["\']', extinf, re.I)
    if match:
        return match.group(1).strip().upper()
    return ""


def probe_stream(item, timeout):
    extinf, url, source_priority = item
    started = monotonic()
    try:
        with requests.get(
            url,
            stream=True,
            timeout=(timeout, timeout),
            headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
            allow_redirects=True,
        ) as response:
            response.raise_for_status()
            first_chunk = next(response.iter_content(chunk_size=4096), b"")
            if not first_chunk:
                return item, False, float("inf"), "empty response"
            latency = monotonic() - started
            return item, True, latency, "ok"
    except (RequestException, OSError) as exc:
        return item, False, float("inf"), str(exc)
    except Exception as exc:
        return item, False, float("inf"), str(exc)


def main():
    sources_doc = load_yaml("config/sources.yml")
    sources = sources_doc.get("sources", [])
    settings = load_yaml("config/settings.yml")

    probe_timeout = int(settings.get("probe_timeout_seconds", DEFAULT_PROBE_TIMEOUT))
    workers = int(settings.get("probe_workers", DEFAULT_WORKERS))
    probe_enabled = bool(settings.get("probe_streams", True))

    allowed_keywords = settings.get("allowed_keywords")
    if allowed_keywords:
        allowed_norm = [normalize_text(a) for a in allowed_keywords]
        use_whitelist = True
    else:
        use_whitelist = False
        include_all = settings.get("include_all", True)
        blocked_norm = [normalize_text(b) for b in settings.get("blocked_keywords", [])]
        priority_norm = [normalize_text(p) for p in settings.get("priority_keywords", [])]

    candidates = []
    successful_sources = 0

    for source in sources:
        if not isinstance(source, dict) or not source.get("enabled", True):
            continue
        url = str(source.get("url", "")).strip()
        source_name = str(source.get("name", url))
        source_priority = int(source.get("priority", 9999))
        allowed_countries = {str(c).upper() for c in source.get("allowed_countries", [])}
        if not url:
            logging.warning("Fuente sin URL: %s", source_name)
            continue

        try:
            response = requests.get(
                url,
                timeout=int(source.get("timeout_seconds", DEFAULT_SOURCE_TIMEOUT)),
                headers={"User-Agent": USER_AGENT},
                allow_redirects=True,
            )
            response.raise_for_status()
            lines = response.text.splitlines()
            successful_sources += 1
        except (RequestException, OSError) as exc:
            logging.warning("Fuente no disponible %s: %s", source_name, exc)
            continue

        for i, line in enumerate(lines):
            if not line.startswith("#EXTINF") or i + 1 >= len(lines):
                continue
            stream_url = lines[i + 1].strip()
            if not stream_url or stream_url.startswith("#"):
                continue

            if allowed_countries and country_code(line) not in allowed_countries:
                continue

            combined = normalize_text(line + " " + stream_url)
            if use_whitelist:
                if not any(k in combined for k in allowed_norm):
                    continue
            else:
                if any(k in combined for k in blocked_norm):
                    continue
                if not include_all and not any(k in combined for k in priority_norm):
                    continue

            candidates.append((line, stream_url, source_priority))

    if not candidates or successful_sources == 0:
        logging.error("No se encontraron candidatos: %d fuentes correctas", successful_sources)
        return 1

    if probe_enabled:
        healthy = []
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            futures = [executor.submit(probe_stream, item, probe_timeout) for item in candidates]
            for future in as_completed(futures):
                item, ok, latency, status = future.result()
                if ok:
                    healthy.append((item[0], item[1], item[2], latency))
                else:
                    logging.info("Descartado stream no saludable: %s (%s)", channel_name(item[0]), status)
        candidates_scored = healthy
        logging.info("Streams saludables: %d/%d", len(candidates_scored), len(candidates))
    else:
        candidates_scored = [(line, url, priority, 999.0) for line, url, priority in candidates]

    best = {}
    for line, url, source_priority, latency in candidates_scored:
        key = (normalize_text(channel_name(line)), normalize_text(group_name(line)))
        score = (latency, source_priority)
        if key not in best or score < best[key][0]:
            best[key] = (score, line, url)

    selected = [(v[1], v[2]) for v in best.values()]
    priority_norm = [normalize_text(p) for p in settings.get("priority_keywords", [])]
    priority_selected = []
    regular_selected = []
    for line, url in selected:
        combined = normalize_text(line + " " + url)
        (priority_selected if any(p in combined for p in priority_norm) else regular_selected).extend([line, url])

    out = ["#EXTM3U"] + priority_selected + regular_selected
    entries = (len(out) - 1) // 2
    if entries == 0:
        logging.error("Todos los streams fueron descartados durante la comprobación")
        return 1

    try:
        Path("playlist.m3u").write_text("\n".join(out) + "\n", encoding="utf8")
    except OSError as exc:
        logging.error("Error escribiendo playlist.m3u: %s", exc)
        return 1

    logging.info("playlist.m3u optimizado: %d canales seleccionados", entries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
