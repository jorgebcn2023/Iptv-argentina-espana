import requests
import yaml
import logging
import unicodedata
from pathlib import Path
from requests.exceptions import RequestException

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def normalize_text(s: str) -> str:
    if s is None:
        return ""
    # Normaliza y elimina acentos/diacríticos, pasar a minúsculas
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
    allowed_keywords = settings.get("allowed_keywords", [])
    blocked_keywords = settings.get("blocked_keywords", [])
    allowed_norm = [normalize_text(a) for a in allowed_keywords]
    blocked_norm = [normalize_text(b) for b in blocked_keywords]

    seen = set()
    out = ["#EXTM3U"]

    for s in sources:
        try:
            r = requests.get(s, timeout=30)
            if r.status_code != 200:
                logging.warning("No se pudo obtener %s (status=%s)", s, r.status_code)
                continue
            lines = r.text.splitlines()
        except RequestException as e:
            logging.warning("Error request a %s: %s", s, e)
            continue
        except Exception as e:
            logging.warning("Error procesando %s: %s", s, e)
            continue

        for i, l in enumerate(lines):
            if l.startswith("#EXTINF") and i + 1 < len(lines):
                u = lines[i + 1].strip()
                if not u:
                    continue
                if u in seen:
                    continue
                combined = normalize_text(l + " " + u)
                # Incluir solo si cumple con palabras clave permitidas
                if not any(a in combined for a in allowed_norm):
                    continue
                # Excluir si está en la lista de palabras bloqueadas
                if any(b in combined for b in blocked_norm):
                    continue
                out.extend([l, u])
                seen.add(u)

    try:
        Path("playlist.m3u").write_text("\n".join(out), encoding="utf8")
        logging.info("playlist.m3u escrito (%d entradas)", max(0, (len(out)-1)//2))
    except Exception as e:
        logging.error("Error escribiendo playlist.m3u: %s", e)

if __name__ == "__main__":
    main()
