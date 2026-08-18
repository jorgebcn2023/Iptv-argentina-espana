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

USER_AGENT = "IPTV-Argentina-Espana/3.2"
DEFAULT_SOURCE_TIMEOUT = 20
DEFAULT_PROBE_TIMEOUT = 8
DEFAULT_WORKERS = 24
PROBE_ATTEMPTS = 2
RETRY_ON_TRANSIENT = 1

COUNTRY_NAMES = {
    "AR": "Argentina", "ES": "España", "IT": "Italia",
    "GB": "Reino Unido", "UK": "Reino Unido",
    "US": "Estados Unidos", "BR": "Brasil",
}

GENRE_RULES = [
    ("Noticias", ["news", "noticia", "noticias", "news 24", "cnn", "bbc news", "tn ", "c5n", "america noticias"]),
    ("Deportes", ["sport", "sports", "deporte", "deportes", "espn", "fox sports", "tyc sports", "tnt sports", "dazn"]),
    ("Documentales", ["documental", "documentary", "history", "nat geo", "national geographic", "discovery", "animal planet"]),
    ("Infantiles", ["kids", "infantil", "disney", "nick", "nickelodeon", "cartoon", "baby", "junior"]),
    ("Películas y Series", ["movie", "movies", "cine", "pelicula", "peliculas", "series", "film", "filme", "axn", "fx", "warner", "universal", "paramount"]),
    ("Música", ["music", "musica", "mtv", "vh1", "vevo", "hit", "hits"]),
    ("Entretenimiento", ["entertainment", "entretenimiento", "reality", "show", "comedy"]),
    ("Infantil", ["kids", "children", "child"]),
]

TRANSIENT_STATUS = {408, 425, 429, 500, 502, 503, 504}


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


def attr(extinf: str, name: str) -> str:
    match = re.search(rf'{re.escape(name)}=["\']([^"\']*)["\']', extinf, re.I)
    return match.group(1).strip() if match else ""


def group_name(extinf: str) -> str:
    return attr(extinf, "group-title")


def country_codes(extinf: str) -> set[str]:
    raw = attr(extinf, "tvg-country") or attr(extinf, "country")
    if not raw:
        return set()
    return {p for p in re.split(r"[,;|/ ]+", raw.upper()) if p}


def infer_country(extinf: str) -> str:
    codes = country_codes(extinf)
    for code in codes:
        if code in COUNTRY_NAMES:
            return COUNTRY_NAMES[code]
    text = normalize_text(extinf)
    aliases = [
        ("Argentina", ["argentina"]),
        ("España", ["espana", "españa", "spain"]),
        ("Italia", ["italia", "italy"]),
        ("Reino Unido", ["reino unido", "united kingdom", "british", "uk"]),
        ("Estados Unidos", ["united states", "usa", "american"]),
        ("Brasil", ["brasil", "brazil"]),
    ]
    for country, keys in aliases:
        if any(k in text for k in keys):
            return country
    return "Internacional"


def infer_section(extinf: str) -> str:
    existing = group_name(extinf).strip()
    normalized_group = normalize_text(existing)
    if existing and normalized_group not in {"-", "_", "n/a", "null", "none", "general"}:
        return existing
    text = normalize_text(extinf + " " + channel_name(extinf))
    for genre, keywords in GENRE_RULES:
        if any(normalize_text(k) in text for k in keywords):
            return genre
    return infer_country(extinf)


def set_group_title(extinf: str, section: str) -> str:
    if re.search(r'group-title=["\']', extinf, re.I):
        return re.sub(r'group-title=["\'][^"\']*["\']', f'group-title="{section}"', extinf, count=1, flags=re.I)
    comma = extinf.rfind(",")
    insert_at = comma if comma >= 0 else len(extinf)
    return extinf[:insert_at] + f' group-title="{section}"' + extinf[insert_at:]


def _probe_once(url: str, timeout: int):
    started = monotonic()
    try:
        with requests.get(
            url,
            stream=True,
            timeout=(timeout, timeout),
            headers={"User-Agent": USER_AGENT, "Accept": "*/*", "Connection": "close"},
            allow_redirects=True,
        ) as response:
            status = response.status_code
            if status >= 400:
                return False, float("inf"), f"HTTP {status}", status
            first_chunk = next(response.iter_content(chunk_size=8192), b"")
            if not first_chunk:
                return False, float("inf"), "empty response", status
            return True, monotonic() - started, "ok", status
    except (RequestException, OSError) as exc:
        return False, float("inf"), str(exc), None
    except Exception as exc:
        return False, float("inf"), str(exc), None


def probe_stream(item, timeout):
    extinf, url, source_priority = item
    successes = []
    errors = []
    attempts = PROBE_ATTEMPTS + RETRY_ON_TRANSIENT
    for attempt in range(attempts):
        ok, latency, status, code = _probe_once(url, timeout)
        if ok:
            successes.append(latency)
            if len(successes) >= PROBE_ATTEMPTS:
                break
        else:
            errors.append(status)
            if code not in TRANSIENT_STATUS and code is not None:
                break
    if not successes:
        return item, False, float("inf"), errors[-1] if errors else "probe failed", 0
    return item, True, sum(successes) / len(successes), "ok", len(successes)


def source_allows_channel(source, extinf: str) -> bool:
    allowed = source.get("allowed_countries")
    if not allowed:
        return True
    allowed_norm = {str(x).upper() for x in allowed}
    codes = country_codes(extinf)
    if codes & allowed_norm:
        return True
    inferred = infer_country(extinf)
    return any(COUNTRY_NAMES.get(code, "") == inferred for code in allowed_norm)


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
        if not url:
            logging.warning("Fuente sin URL: %s", source_name)
            continue
        try:
            response = requests.get(
                url,
                timeout=int(source.get("timeout_seconds", DEFAULT_SOURCE_TIMEOUT)),
                headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
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
            if not source_allows_channel(source, line):
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

    scored = []
    if probe_enabled:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            futures = [executor.submit(probe_stream, item, probe_timeout) for item in candidates]
            for future in as_completed(futures):
                item, ok, latency, status, attempts_ok = future.result()
                scored.append((item[0], item[1], item[2], latency, ok, attempts_ok))
                if not ok:
                    logging.info("URL no saludable (se conserva): %s (%s)", channel_name(item[0]), status)
    else:
        scored = [(line, url, priority, 999.0, True, 0) for line, url, priority in candidates]

    # ÚNICA eliminación: URL idéntica. Nunca se deduplica por nombre de canal.
    seen_urls = set()
    unique = []
    for line, url, priority, latency, ok, attempts_ok in sorted(
        scored, key=lambda x: (not x[4], -x[5], x[3], x[2], normalize_text(channel_name(x[0])))
    ):
        canonical_url = url.strip()
        if canonical_url in seen_urls:
            continue
        seen_urls.add(canonical_url)
        section = infer_section(line)
        normalized_line = set_group_title(line, section)
        unique.append((normalized_line, url, priority, latency, ok, attempts_ok, section))

    sections = {}
    for line, url, priority, latency, ok, attempts_ok, section in unique:
        sections.setdefault(section, []).append((line, url, priority, latency, ok, attempts_ok))

    preferred_order = [
        "Argentina", "España", "Italia", "Reino Unido", "Estados Unidos", "Brasil",
        "Noticias", "Deportes", "Documentales", "Películas y Series", "Infantiles", "Música", "Entretenimiento", "Internacional"
    ]
    ordered_sections = [s for s in preferred_order if s in sections]
    ordered_sections += sorted(s for s in sections if s not in ordered_sections)

    out = ["#EXTM3U"]
    for section in ordered_sections:
        items = sections[section]
        items.sort(key=lambda x: (not x[4], -x[5], x[3], x[2], normalize_text(channel_name(x[0]))))
        for line, url, *_ in items:
            out.extend([line, url])

    entries = (len(out) - 1) // 2
    if entries == 0:
        logging.error("No se generaron canales")
        return 1

    try:
        Path("playlist.m3u").write_text("\n".join(out) + "\n", encoding="utf8")
    except OSError as exc:
        logging.error("Error escribiendo playlist.m3u: %s", exc)
        return 1

    healthy = sum(1 for x in unique if x[4])
    stable = sum(1 for x in unique if x[5] == PROBE_ATTEMPTS)
    logging.info("playlist.m3u optimizado: %d canales, %d URLs únicas, %d saludables, %d estables", entries, len(unique), healthy, stable)
    logging.info("Secciones generadas: %d", len(ordered_sections))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
