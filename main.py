import logging
import unicodedata
from pathlib import Path

import requests
import yaml
from requests.exceptions import RequestException

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def normalize_text(s: str) -> str:
    if s is None:
        return ""
    nk = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nk if not unicodedata.combining(c)).lower()


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


def main():
    sources_doc = load_yaml("config/sources.yml")
    sources = sources_doc.get("sources", [])
    settings = load_yaml("config/settings.yml")

    allowed_keywords = settings.get("allowed_keywords")
    if allowed_keywords:
        allowed_norm = [normalize_text(a) for a in allowed_keywords]
        use_whitelist = True
    else:
        use_whitelist = False
        include_all = settings.get("include_all", True)
        blocked_keywords = settings.get("blocked_keywords", [])
        priority_keywords = settings.get("priority_keywords", [])
        blocked_norm = [normalize_text(b) for b in blocked_keywords]
        priority_norm = [normalize_text(p) for p in priority_keywords]

    seen = set()
    priority_entries = []
    regular_entries = []
    out = ["#EXTM3U"]
    successful_sources = 0

    for source in sources:
        if not isinstance(source, dict):
            logging.warning("Fuente ignorada por formato inválido: %r", source)
            continue
        url = str(source.get("url", "")).strip()
        name = str(source.get("name", url))
        if not url:
            logging.warning("Fuente sin URL: %s", name)
            continue

        try:
            r = requests.get(
                url,
                timeout=int(source.get("timeout_seconds", 30)),
                headers={"User-Agent": "IPTV-Argentina-Espana/1.0"},
                allow_redirects=True,
            )
            r.raise_for_status()
            lines = r.text.splitlines()
            successful_sources += 1
        except RequestException as e:
            logging.warning("Error request a %s: %s", name, e)
            continue
        except Exception as e:
            logging.warning("Error procesando %s: %s", name, e)
            continue

        for i, line in enumerate(lines):
            if not line.startswith("#EXTINF") or i + 1 >= len(lines):
                continue
            u = lines[i + 1].strip()
            if not u or u.startswith("#"):
                continue

            name_match = line.rfind(",")
            channel_name = line[name_match + 1:].strip() if name_match >= 0 else "Unknown"
            channel_key = (channel_name, u)
            if channel_key in seen:
                continue

            combined = normalize_text(line + " " + u)
            if use_whitelist:
                if not any(a in combined for a in allowed_norm):
                    continue
                regular_entries.extend([line, u])
                seen.add(channel_key)
            else:
                if any(b in combined for b in blocked_norm):
                    continue
                if include_all:
                    if any(p in combined for p in priority_norm):
                        priority_entries.extend([line, u])
                    else:
                        regular_entries.extend([line, u])
                    seen.add(channel_key)
                elif any(p in combined for p in priority_norm):
                    priority_entries.extend([line, u])
                    seen.add(channel_key)

    out.extend(priority_entries)
    out.extend(regular_entries)

    entries = (len(out) - 1) // 2
    if successful_sources == 0 or entries == 0:
        logging.error(
            "No se pudo generar una playlist válida: %d fuentes correctas, %d entradas",
            successful_sources,
            entries,
        )
        return 1

    try:
        Path("playlist.m3u").write_text("\n".join(out) + "\n", encoding="utf8")
        logging.info("playlist.m3u escrito (%d entradas)", entries)
    except Exception as e:
        logging.error("Error escribiendo playlist.m3u: %s", e)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
