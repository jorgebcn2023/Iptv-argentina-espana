import json
import logging
import re
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import monotonic
from urllib.parse import urljoin, urlparse

import requests
import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
USER_AGENT = "IPTV-Argentina-Espana/10.0"
PROBE_TIMEOUT = (3, 5)
WORKERS = 48
WEB_HOSTS = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com", "twitch.tv", "www.twitch.tv", "facebook.com", "www.facebook.com", "instagram.com", "www.instagram.com", "tiktok.com", "www.tiktok.com", "twitter.com", "x.com"}
COUNTRY_NAMES = {"AR": "Argentina", "ES": "España", "IT": "Italia", "GB": "Reino Unido", "UK": "Reino Unido", "US": "Estados Unidos", "BR": "Brasil"}
GENRES = [("Noticias", ["news", "noticia", "noticias", "cnn", "bbc news", "tn ", "c5n", "america noticias"]), ("Deportes", ["sport", "sports", "deporte", "deportes", "espn", "fox sports", "tyc sports", "tnt sports", "dazn"]), ("Documentales", ["documental", "documentary", "history", "nat geo", "national geographic", "discovery", "animal planet"]), ("Infantiles", ["kids", "infantil", "disney", "nick", "nickelodeon", "cartoon", "baby", "junior"]), ("Películas y Series", ["movie", "movies", "cine", "pelicula", "peliculas", "series", "film", "axn", "fx", "warner", "universal", "paramount"]), ("Música", ["music", "musica", "mtv", "vh1", "vevo", "hit", "hits"]), ("Entretenimiento", ["entertainment", "entretenimiento", "reality", "show", "comedy"])]

def norm(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(c for c in value if not unicodedata.combining(c)).lower().strip()

def load(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except Exception as exc:
        logging.error("No se puede leer %s: %s", path, exc)
        return {}

def attr(line, key):
    match = re.search(rf'{re.escape(key)}=["\']([^"\']*)["\']', line, re.I)
    return match.group(1).strip() if match else ""

def channel_name(line):
    pos = line.rfind(",")
    return line[pos + 1:].strip() if pos >= 0 else "Unknown"

def country(line):
    raw = attr(line, "tvg-country") or attr(line, "country")
    return {item for item in re.split(r"[,;|/ ]+", raw.upper()) if item} if raw else set()

def infer_country(line):
    for code in country(line):
        if code in COUNTRY_NAMES:
            return COUNTRY_NAMES[code]
    text = norm(line)
    for label, keys in [("Argentina", ["argentina"]), ("España", ["espana", "españa", "spain"]), ("Italia", ["italia", "italy"]), ("Reino Unido", ["reino unido", "united kingdom", "british"]), ("Estados Unidos", ["united states", "usa", "american"]), ("Brasil", ["brasil", "brazil"])]:
        if any(key in text for key in keys): return label
    return "Internacional"

def section(line):
    group = attr(line, "group-title").strip()
    if group and norm(group) not in {"-", "_", "n/a", "null", "none", "general"}: return group
    text = norm(line + " " + channel_name(line))
    for label, keys in GENRES:
        if any(norm(key) in text for key in keys): return label
    return infer_country(line)

def set_group(line, group):
    if attr(line, "group-title").strip(): return line
    pos = line.rfind(",")
    return line[:pos] + f' group-title="{group}"' + line[pos:] if pos >= 0 else line

def stream_url(value):
    return value.strip().lower().startswith(("http://", "https://", "rtmp://", "rtmps://", "rtsp://", "udp://", "srt://", "acestream://"))

def parse(lines):
    entries, index = [], 0
    while index < len(lines):
        if not lines[index].strip().startswith("#EXTINF"):
            index += 1; continue
        extinf, directives, url, cursor = lines[index].strip(), [], "", index + 1
        while cursor < len(lines):
            value = lines[cursor].strip()
            if not value: cursor += 1; continue
            if value.startswith("#EXTINF"): break
            if value.startswith("#"): directives.append(value); cursor += 1; continue
            if stream_url(value): url = value; break
            cursor += 1
        if url: entries.append((extinf, url, directives))
        index = max(cursor, index + 1)
    return entries

def pipe_headers(url):
    headers = {}
    if "|" not in url: return headers
    mapping = {"user-agent": "User-Agent", "http-user-agent": "User-Agent", "referer": "Referer", "http-referrer": "Referer", "http-referer": "Referer", "origin": "Origin", "http-origin": "Origin", "cookie": "Cookie", "http-cookie": "Cookie"}
    for part in re.split(r"[|&]", url.split("|", 1)[1]):
        if "=" in part:
            key, value = part.split("=", 1); mapped = mapping.get(key.strip().lower())
            if mapped: headers[mapped] = value.strip()
    return headers

def request_headers(directives, url):
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*", "Connection": "close"}; headers.update(pipe_headers(url))
    for directive in directives:
        lower = directive.lower()
        if lower.startswith("#extvlcopt:http-referrer="): headers["Referer"] = directive.split("=", 1)[1].strip()
        elif lower.startswith("#extvlcopt:http-origin="): headers["Origin"] = directive.split("=", 1)[1].strip()
        elif lower.startswith("#extvlcopt:http-user-agent="): headers["User-Agent"] = directive.split("=", 1)[1].strip()
    return headers

def base_url(url): return url.split("|", 1)[0].strip()

def kind(url):
    parsed = urlparse(base_url(url)); host, path = parsed.netloc.lower().split(":")[0], parsed.path.lower()
    if host in WEB_HOSTS or host.endswith(".youtube.com") or host.endswith(".twitch.tv"): return 2
    if parsed.scheme in {"rtmp", "rtmps", "rtsp", "udp", "srt", "acestream"} or any(token in path for token in (".m3u8", ".m3u", ".mpd", ".ts", "/hls/", "/live/", "/playlist", "/manifest")): return 0
    return 1

def probe_hls(request_url, response, headers):
    if "text/html" in (response.headers.get("content-type") or "").lower(): return False, "HTML response"
    text = response.text[:131072]
    if not text.lstrip().startswith("#EXTM3U"): return False, "not an M3U response"
    lines = text.splitlines()
    if any(line.startswith("#EXTINF:") for line in lines): return True, "ok"
    for idx, line in enumerate(lines[:-1]):
        if line.startswith("#EXT-X-STREAM-INF") and lines[idx + 1].strip() and not lines[idx + 1].startswith("#"):
            try:
                with requests.get(urljoin(request_url, lines[idx + 1].strip()), stream=True, timeout=PROBE_TIMEOUT, headers=headers, allow_redirects=True) as child:
                    ok = child.status_code < 400 and bool(next(child.iter_content(1024), b"")); return ok, "ok" if ok else "variant unavailable"
            except requests.RequestException: return False, "variant unavailable"
    return False, "empty/invalid HLS playlist"

def probe(item):
    extinf, url, directives, *_ = item; stream_kind = kind(url)
    if stream_kind == 2: return item, False, 999.0, "web/resolver required", stream_kind
    request_url, headers, started = base_url(url), request_headers(directives, url), monotonic()
    try:
        with requests.get(request_url, stream=True, timeout=PROBE_TIMEOUT, headers=headers, allow_redirects=True) as response:
            if response.status_code >= 400: return item, False, monotonic() - started, f"HTTP {response.status_code}", stream_kind
            if stream_kind == 0 and (request_url.lower().endswith((".m3u8", ".m3u")) or "mpegurl" in (response.headers.get("content-type") or "").lower()): ok, status = probe_hls(request_url, response, headers)
            else:
                ok = bool(next(response.iter_content(4096), b"")) and "text/html" not in (response.headers.get("content-type") or "").lower(); status = "ok" if ok else "empty/html response"
            return item, ok, monotonic() - started, status, stream_kind
    except requests.RequestException as exc: return item, False, monotonic() - started, type(exc).__name__, stream_kind

def allowed_source(source, extinf):
    allowed = source.get("allowed_countries")
    if not allowed: return True
    allowed = {str(code).upper() for code in allowed}
    return bool(country(extinf) & allowed) or infer_country(extinf) in {COUNTRY_NAMES.get(code, "") for code in allowed}

def fetch_source(source, source_order):
    source_name, priority, url = str(source.get("name", source.get("url", ""))), int(source.get("priority", 9999)), str(source.get("url", "")).strip()
    audit = {"name": source_name, "url": url, "priority": priority, "status": "unavailable", "entries": 0, "accepted": 0}
    try:
        timeout = int(source.get("timeout_seconds", 15)); response = requests.get(url, timeout=(min(5, timeout), timeout), headers={"User-Agent": USER_AGENT, "Accept": "*/*"}, allow_redirects=True); response.raise_for_status(); entries = parse(response.text.splitlines()); audit.update(status="ok", entries=len(entries)); return source_order, source, entries, audit
    except requests.RequestException as exc:
        audit["error"] = type(exc).__name__; logging.warning("Fuente no disponible %s: %s", source_name, exc); return source_order, source, [], audit

def main():
    cfg, settings = load("config/sources.yml"), load("config/settings.yml")
    blocked, allowed_words = [norm(word) for word in settings.get("blocked_keywords", [])], [norm(word) for word in settings.get("allowed_keywords", [])]
    enabled = [(index, source) for index, source in enumerate(cfg.get("sources", [])) if isinstance(source, dict) and source.get("enabled", True) and source.get("url")]
    source_results = []
    with ThreadPoolExecutor(max_workers=min(max(1, int(settings.get("source_workers", 8))), max(1, len(enabled)))) as executor:
        for future in as_completed([executor.submit(fetch_source, source, index) for index, source in enabled]): source_results.append(future.result())
    source_results.sort(key=lambda result: result[0]); candidates, audit, entry_order = [], {"sources": [], "input_entries": 0, "output_entries": 0, "duplicates_removed": [], "probe_summary": {}, "web_resolver_entries": []}, 0
    for source_order, source, entries, source_audit in source_results:
        priority, source_name = int(source.get("priority", 9999)), source_audit["name"]
        for extinf, url, directives in entries:
            text = norm(extinf + " " + url)
            if not allowed_source(source, extinf) or (allowed_words and not any(word in text for word in allowed_words)) or any(word in text for word in blocked): continue
            candidates.append((extinf, url, directives, priority, source_name, source_order, entry_order)); source_audit["accepted"] += 1; entry_order += 1
        audit["sources"].append(source_audit)
    audit["input_entries"] = len(candidates)
    if not candidates: Path("audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); return 1
    seen, unique_candidates = set(), []
    for item in candidates:
        key = (item[0].strip(), item[1].strip(), tuple(item[2]))
        if key in seen: audit["duplicates_removed"].append({"source": item[4], "channel": channel_name(item[0]), "url": item[1], "reason": "exact duplicate"}); continue
        seen.add(key); unique_candidates.append(item)
    if bool(settings.get("probe_streams", True)):
        results = []
        with ThreadPoolExecutor(max_workers=min(max(1, int(settings.get("probe_workers", WORKERS))), max(1, len(unique_candidates)))) as executor:
            for future in as_completed([executor.submit(probe, item) for item in unique_candidates]): results.append(future.result())
    else: results = [(item, False, 999.0, "not probed", kind(item[1])) for item in unique_candidates]
    statuses, unique = Counter(), []
    for item, ok, latency, status, stream_kind in results:
        statuses[status] += 1; extinf, url, directives, priority, source_name, source_order, entry_order = item; unique.append((set_group(extinf, section(extinf)), url, directives, priority, source_name, ok, latency, stream_kind, source_order, entry_order, status))
        if stream_kind == 2: audit["web_resolver_entries"].append({"source": source_name, "channel": channel_name(extinf), "url": url, "status": status})
    audit["probe_summary"], audit["output_entries"] = dict(statuses), len(unique)
    preferred = ["Argentina", "España", "Italia", "Reino Unido", "Estados Unidos", "Brasil", "Noticias", "Deportes", "Documentales", "Películas y Series", "Infantiles", "Música", "Entretenimiento", "Internacional"]; sections = defaultdict(list)
    for item in unique: sections[section(item[0])].append(item)
    out = ["#EXTM3U"]
    for section_name in [name for name in preferred if name in sections] + sorted(name for name in sections if name not in preferred):
        items = sections[section_name]; items.sort(key=lambda item: (0 if item[5] else (3 if item[7] == 2 else 2), item[3], item[6] if item[5] else 999.0, norm(channel_name(item[0])), item[8], item[9]))
        for extinf, url, directives, *_ in items: out.extend([extinf, *directives, url])
    Path("playlist.m3u").write_text("\n".join(out) + "\n", encoding="utf-8"); Path("audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logging.info("Playlist generada: %s entradas; fuentes activas: %s/%s", audit["output_entries"], sum(1 for source in audit["sources"] if source["status"] == "ok"), len(audit["sources"])); return 0

if __name__ == "__main__": raise SystemExit(main())
