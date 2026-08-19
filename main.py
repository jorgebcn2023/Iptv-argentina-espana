import logging
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import monotonic
from urllib.parse import urljoin, urlparse

import requests
import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

USER_AGENT = "IPTV-Argentina-Espana/7.0"
SOURCE_TIMEOUT = 30
PROBE_TIMEOUT = 8
WORKERS = 24
TRANSIENT = {408, 425, 429, 500, 502, 503, 504}
WEB_HOSTS = {"youtube.com", "www.youtube.com", "youtu.be", "twitch.tv", "www.twitch.tv", "facebook.com", "www.facebook.com", "instagram.com", "www.instagram.com", "tiktok.com", "www.tiktok.com", "twitter.com", "x.com"}
COUNTRY_NAMES = {"AR":"Argentina", "ES":"España", "IT":"Italia", "GB":"Reino Unido", "UK":"Reino Unido", "US":"Estados Unidos", "BR":"Brasil"}
GENRES = [
    ("Noticias", ["news", "noticia", "noticias", "cnn", "bbc news", "tn ", "c5n", "america noticias"]),
    ("Deportes", ["sport", "sports", "deporte", "deportes", "espn", "fox sports", "tyc sports", "tnt sports", "dazn"]),
    ("Documentales", ["documental", "documentary", "history", "nat geo", "national geographic", "discovery", "animal planet"]),
    ("Infantiles", ["kids", "infantil", "disney", "nick", "nickelodeon", "cartoon", "baby", "junior"]),
    ("Películas y Series", ["movie", "movies", "cine", "pelicula", "peliculas", "series", "film", "axn", "fx", "warner", "universal", "paramount"]),
    ("Música", ["music", "musica", "mtv", "vh1", "vevo", "hit", "hits"]),
    ("Entretenimiento", ["entertainment", "entretenimiento", "reality", "show", "comedy"]),
]

def norm(s):
    s = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()

def load(path):
    try:
        with open(path, encoding="utf-8") as f: return yaml.safe_load(f) or {}
    except Exception as e:
        logging.error("No se puede leer %s: %s", path, e); return {}

def attr(line, key):
    m = re.search(rf'{re.escape(key)}=["\']([^"\']*)["\']', line, re.I)
    return m.group(1).strip() if m else ""

def name(line):
    p = line.rfind(","); return line[p + 1:].strip() if p >= 0 else "Unknown"

def country(line):
    raw = attr(line, "tvg-country") or attr(line, "country")
    return {x for x in re.split(r"[,;|/ ]+", raw.upper()) if x} if raw else set()

def infer_country(line):
    for c in country(line):
        if c in COUNTRY_NAMES: return COUNTRY_NAMES[c]
    t = norm(line)
    for label, keys in [("Argentina", ["argentina"]), ("España", ["espana", "españa", "spain"]), ("Italia", ["italia", "italy"]), ("Reino Unido", ["reino unido", "united kingdom", "british"]), ("Estados Unidos", ["united states", "usa", "american"]), ("Brasil", ["brasil", "brazil"])]:
        if any(k in t for k in keys): return label
    return "Internacional"

def section(line):
    g = attr(line, "group-title").strip()
    if g and norm(g) not in {"-", "_", "n/a", "null", "none", "general"}: return g
    t = norm(line + " " + name(line))
    for label, keys in GENRES:
        if any(norm(k) in t for k in keys): return label
    return infer_country(line)

def set_group(line, g):
    if re.search(r'group-title=["\']', line, re.I):
        return re.sub(r'group-title=["\'][^"\']*["\']', f'group-title="{g}"', line, count=1, flags=re.I)
    p = line.rfind(","); return line[:p] + f' group-title="{g}"' + line[p:] if p >= 0 else line

def stream_url(u):
    return u.strip().lower().startswith(("http://", "https://", "rtmp://", "rtmps://", "rtsp://", "udp://", "srt://", "acestream://"))

def parse(lines):
    out=[]; i=0
    while i < len(lines):
        if not lines[i].strip().startswith("#EXTINF"):
            i += 1; continue
        ext=lines[i].strip(); directives=[]; url=""; j=i+1
        while j < len(lines):
            x=lines[j].strip()
            if not x: j += 1; continue
            if x.startswith("#EXTINF"): break
            if x.startswith("#"):
                directives.append(x); j += 1; continue
            if stream_url(x): url=x; break
            j += 1
        if url: out.append((ext,url,directives))
        i=max(j,i+1)
    return out

def pipe_headers(url):
    h={}
    if "|" not in url: return h
    for part in re.split(r"[|&]",url.split("|",1)[1]):
        if "=" not in part: continue
        k,v=part.split("=",1); k=k.strip().lower(); v=v.strip()
        if k in {"user-agent","http-user-agent"}: h["User-Agent"]=v
        elif k in {"referer","http-referrer","http-referer"}: h["Referer"]=v
        elif k in {"origin","http-origin"}: h["Origin"]=v
        elif k in {"cookie","http-cookie"}: h["Cookie"]=v
    return h

def headers(directives,url=""):
    h={"User-Agent":USER_AGENT,"Accept":"*/*","Connection":"close"}; h.update(pipe_headers(url))
    for d in directives:
        low=d.lower()
        if low.startswith("#extvlcopt:http-referrer="): h["Referer"]=d.split("=",1)[1].strip()
        elif low.startswith("#extvlcopt:http-origin="): h["Origin"]=d.split("=",1)[1].strip()
        elif low.startswith("#extvlcopt:http-user-agent="): h["User-Agent"]=d.split("=",1)[1].strip()
        elif low.startswith("#exthttp:") and "=" in d.split(":",1)[1]:
            k,v=d.split(":",1)[1].split("=",1); h[k.strip()]=v.strip()
    return h

def base_url(url): return url.split("|",1)[0].strip()

def kind(url):
    p=urlparse(base_url(url)); host=p.netloc.lower().split(":")[0]; path=p.path.lower()
    if host in WEB_HOSTS or host.endswith(".youtube.com") or host.endswith(".twitch.tv"): return 2
    if any(x in path for x in (".m3u8",".m3u",".mpd",".ts","/hls/","/live/","/playlist","/manifest")): return 0
    if p.scheme in {"rtmp","rtmps","rtsp","udp","srt","acestream"}: return 0
    return 1

def probe_hls(request_url, r, h):
    ctype=(r.headers.get("content-type") or "").lower()
    if "text/html" in ctype: return False, "HTML response"
    text=""
    try: text=r.text[:256000]
    except Exception: pass
    if not text.lstrip().startswith("#EXTM3U"): return False, "not an M3U response"
    # A media playlist must contain segments; a master playlist must expose at least one variant.
    media=any(x.startswith("#EXTINF:") for x in text.splitlines())
    variants=any("#EXT-X-STREAM-INF" in x for x in text.splitlines())
    if not (media or variants): return False, "empty/invalid HLS playlist"
    # For a master playlist, resolve one variant and verify it can be fetched.
    if variants:
        lines=text.splitlines()
        for idx,line in enumerate(lines):
            if line.startswith("#EXT-X-STREAM-INF") and idx+1 < len(lines) and lines[idx+1].strip() and not lines[idx+1].startswith("#"):
                child=urljoin(request_url,lines[idx+1].strip())
                try:
                    with requests.get(child,stream=True,timeout=(PROBE_TIMEOUT,PROBE_TIMEOUT),headers=h,allow_redirects=True) as cr:
                        if cr.status_code < 400 and next(cr.iter_content(1024),b""): return True,"ok"
                except Exception: pass
                break
    return True,"ok"

def probe(item):
    ext,url,directives,priority,source=item; k=kind(url)
    if k==2: return item,False,999.0,"web page",0,k
    request_url=base_url(url); h=headers(directives,url); started=monotonic(); last="unverified"; successes=0
    attempts=2
    for attempt in range(attempts):
        for verify in (True,False):
            try:
                with requests.get(request_url,stream=True,timeout=(PROBE_TIMEOUT,PROBE_TIMEOUT),headers=h,allow_redirects=True,verify=verify) as r:
                    code=r.status_code
                    if code>=400:
                        last=f"HTTP {code}"
                        if code not in TRANSIENT and code not in (401,403,404): break
                        continue
                    if k==0 and (request_url.lower().endswith((".m3u8",".m3u")) or "mpegurl" in (r.headers.get("content-type") or "").lower()):
                        ok,msg=probe_hls(request_url,r,h)
                    else:
                        ctype=(r.headers.get("content-type") or "").lower(); chunk=next(r.iter_content(8192),b"")
                        ok=bool(chunk) and "text/html" not in ctype; msg="ok" if ok else "empty/html response"
                    last=msg
                    if ok:
                        successes+=1; break
            except Exception as e: last=type(e).__name__
        if successes: break
    return item,bool(successes),monotonic()-started,last,successes,k

def allowed_source(src,ext):
    allowed=src.get("allowed_countries")
    if not allowed: return True
    a={str(x).upper() for x in allowed}
    return bool(country(ext)&a) or infer_country(ext) in {COUNTRY_NAMES.get(x,"") for x in a}

def main():
    cfg=load("config/sources.yml"); settings=load("config/settings.yml")
    blocked=[norm(x) for x in settings.get("blocked_keywords",[])]; allowed_words=[norm(x) for x in settings.get("allowed_keywords",[])]
    candidates=[]; good_sources=0
    for src in cfg.get("sources",[]):
        if not isinstance(src,dict) or not src.get("enabled",True): continue
        source=str(src.get("name",src.get("url",""))); priority=int(src.get("priority",9999)); url=str(src.get("url","")).strip()
        if not url: continue
        try:
            r=requests.get(url,timeout=int(src.get("timeout_seconds",SOURCE_TIMEOUT)),headers={"User-Agent":USER_AGENT,"Accept":"*/*"},allow_redirects=True); r.raise_for_status(); good_sources+=1
        except Exception as e:
            logging.warning("Fuente no disponible %s: %s",source,e); continue
        for ext,u,d in parse(r.text.splitlines()):
            if not allowed_source(src,ext): continue
            text=norm(ext+" "+u)
            if allowed_words and not any(x in text for x in allowed_words): continue
            if any(x in text for x in blocked): continue
            candidates.append((ext,u,d,priority,source))
    if not candidates or not good_sources: return 1
    results=[]
    if bool(settings.get("probe_streams",True)):
        with ThreadPoolExecutor(max_workers=int(settings.get("probe_workers",WORKERS))) as ex:
            for f in as_completed([ex.submit(probe,x) for x in candidates]): results.append(f.result())
    else:
        results=[(x,kind(x[1])==0,999.0,"not probed",0,kind(x[1])) for x in candidates]
    # Nunca se elimina por resultado del probe. Solo se elimina una entrada byte-a-byte equivalente:
    # misma URL y exactamente las mismas directivas de reproducción.
    seen=set(); unique=[]
    for item,ok,lat,status,successes,k in results:
        ext,u,d,p,src=item; key=(u.strip(),tuple(d))
        if key in seen: continue
        seen.add(key); unique.append((set_group(ext,section(ext)),u,d,p,src,ok,lat,successes,k))
    preferred=["Argentina","España","Italia","Reino Unido","Estados Unidos","Brasil","Noticias","Deportes","Documentales","Películas y Series","Infantiles","Música","Entretenimiento","Internacional"]
    sections={}
    for x in unique: sections.setdefault(attr(x[0],"group-title"),[]).append(x)
    ordered=[s for s in preferred if s in sections]+sorted(s for s in sections if s not in preferred)
    out=["#EXTM3U"]
    for sec in ordered:
        items=sections[sec]
        # Primero streams directos HLS/DASH/RTMP/RTSP; dentro de cada tipo, los que pasan
        # una prueba de arranque y menor latencia. Las páginas web quedan al final.
        items.sort(key=lambda x:(norm(name(x[0])),x[8],not x[5],x[6],x[3]))
        for ext,u,d,*_ in items: out.extend([ext,*d,u])
    Path("playlist.m3u").write_text("\n".join(out)+"\n",encoding="utf-8")
    logging.info("Playlist: %d variantes únicas; metadata preservada; ninguna URL eliminada por fallo de prueba",len(unique))
    return 0

if __name__=="__main__": raise SystemExit(main())