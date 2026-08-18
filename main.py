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

USER_AGENT = "IPTV-Argentina-Espana/3.4"
DEFAULT_SOURCE_TIMEOUT = 20
DEFAULT_PROBE_TIMEOUT = 8
DEFAULT_WORKERS = 24
PROBE_ATTEMPTS = 2
RETRY_ON_TRANSIENT = 1

COUNTRY_NAMES = {"AR":"Argentina","ES":"España","IT":"Italia","GB":"Reino Unido","UK":"Reino Unido","US":"Estados Unidos","BR":"Brasil"}
GENRE_RULES = [("Noticias",["news","noticia","noticias","news 24","cnn","bbc news","tn ","c5n","america noticias"]),("Deportes",["sport","sports","deporte","deportes","espn","fox sports","tyc sports","tnt sports","dazn"]),("Documentales",["documental","documentary","history","nat geo","national geographic","discovery","animal planet"]),("Infantiles",["kids","infantil","disney","nick","nickelodeon","cartoon","baby","junior"]),("Películas y Series",["movie","movies","cine","pelicula","peliculas","series","film","filme","axn","fx","warner","universal","paramount"]),("Música",["music","musica","mtv","vh1","vevo","hit","hits"]),("Entretenimiento",["entertainment","entretenimiento","reality","show","comedy"]),("Infantil",["kids","children","child"])]
TRANSIENT_STATUS={408,425,429,500,502,503,504}

def normalize_text(s):
    nk=unicodedata.normalize("NFKD",str(s or "")); return "".join(c for c in nk if not unicodedata.combining(c)).lower().strip()
def load_yaml(path):
    try:
        with open(path,encoding="utf8") as f:return yaml.safe_load(f) or {}
    except Exception as e: logging.error("Error leyendo %s: %s",path,e); return {}
def channel_name(extinf):
    p=extinf.rfind(","); return extinf[p+1:].strip() if p>=0 else "Unknown"
def attr(extinf,name):
    m=re.search(rf'{re.escape(name)}=["\']([^"\']*)["\']',extinf,re.I); return m.group(1).strip() if m else ""
def group_name(extinf): return attr(extinf,"group-title")
def country_codes(extinf):
    raw=attr(extinf,"tvg-country") or attr(extinf,"country"); return {p for p in re.split(r"[,;|/ ]+",raw.upper()) if p} if raw else set()
def infer_country(extinf):
    for code in country_codes(extinf):
        if code in COUNTRY_NAMES:return COUNTRY_NAMES[code]
    text=normalize_text(extinf)
    for country,keys in [("Argentina",["argentina"]),("España",["espana","españa","spain"]),("Italia",["italia","italy"]),("Reino Unido",["reino unido","united kingdom","british","uk"]),("Estados Unidos",["united states","usa","american"]),("Brasil",["brasil","brazil"])]:
        if any(k in text for k in keys):return country
    return "Internacional"
def infer_section(extinf):
    existing=group_name(extinf).strip()
    if existing and normalize_text(existing) not in {"-","_","n/a","null","none","general"}:return existing
    text=normalize_text(extinf+" "+channel_name(extinf))
    for genre,keywords in GENRE_RULES:
        if any(normalize_text(k) in text for k in keywords):return genre
    return infer_country(extinf)
def set_group_title(extinf,section):
    if re.search(r'group-title=["\']',extinf,re.I):return re.sub(r'group-title=["\'][^"\']*["\']',f'group-title="{section}"',extinf,count=1,flags=re.I)
    comma=extinf.rfind(","); return extinf[:comma]+f' group-title="{section}"'+extinf[comma:] if comma>=0 else extinf
def is_stream_url(value):
    return value.strip().lower().startswith(("http://","https://","rtmp://","rtmps://","udp://","rtsp://","srt://","acestream://"))
def parse_source_entries(lines):
    entries=[]; i=0
    while i<len(lines):
        if not lines[i].strip().startswith("#EXTINF"):i+=1;continue
        extinf=lines[i].strip(); directives=[]; j=i+1; url=""
        while j<len(lines):
            c=lines[j].strip()
            if not c:j+=1;continue
            if c.startswith("#EXTINF"):break
            if c.startswith("#"):
                if c.upper().startswith(("#EXTVLCOPT:","#KODIPROP:","#EXTHTTP:")):directives.append(c)
                j+=1;continue
            if is_stream_url(c):url=c;break
            j+=1
        if url:entries.append((extinf,url,directives))
        i=max(j,i+1)
    return entries
def directive_headers(directives):
    headers={}
    for d in directives:
        low=d.lower()
        if low.startswith("#extvlcopt:http-referrer="):headers["Referer"]=d.split("=",1)[1].strip()
        elif low.startswith("#extvlcopt:http-user-agent="):headers["User-Agent"]=d.split("=",1)[1].strip()
        elif low.startswith("#exthttp:") and "=" in d.split(":",1)[1]:
            k,v=d.split(":",1)[1].split("=",1);headers[k.strip()]=v.strip()
    headers.setdefault("User-Agent",USER_AGENT);headers.setdefault("Accept","*/*");headers.setdefault("Connection","close");return headers
def _probe_once(url,timeout,directives):
    started=monotonic()
    try:
        with requests.get(url,stream=True,timeout=(timeout,timeout),headers=directive_headers(directives),allow_redirects=True) as r:
            if r.status_code>=400:return False,float("inf"),f"HTTP {r.status_code}",r.status_code
            if not next(r.iter_content(chunk_size=8192),b""):return False,float("inf"),"empty response",r.status_code
            return True,monotonic()-started,"ok",r.status_code
    except (RequestException,OSError) as e:return False,float("inf"),str(e),None
def probe_stream(item,timeout):
    extinf,url,priority,directives=item; successes=[];errors=[]
    for _ in range(PROBE_ATTEMPTS+RETRY_ON_TRANSIENT):
        ok,lat,msg,code=_probe_once(url,timeout,directives)
        if ok:
            successes.append(lat)
            if len(successes)>=PROBE_ATTEMPTS:break
        else:
            errors.append(msg)
            if code is not None and code not in TRANSIENT_STATUS:break
    return item,bool(successes),(sum(successes)/len(successes) if successes else float("inf")),(errors[-1] if errors else "ok"),len(successes)
def source_allows_channel(source,extinf):
    allowed=source.get("allowed_countries")
    if not allowed:return True
    allowed_norm={str(x).upper() for x in allowed};codes=country_codes(extinf)
    if codes&allowed_norm:return True
    inferred=infer_country(extinf);return any(COUNTRY_NAMES.get(c,"")==inferred for c in allowed_norm)
def main():
    sources_doc=load_yaml("config/sources.yml");sources=sources_doc.get("sources",[]);settings=load_yaml("config/settings.yml")
    probe_timeout=int(settings.get("probe_timeout_seconds",DEFAULT_PROBE_TIMEOUT));workers=int(settings.get("probe_workers",DEFAULT_WORKERS));probe_enabled=bool(settings.get("probe_streams",True))
    allowed_keywords=settings.get("allowed_keywords");use_whitelist=bool(allowed_keywords);allowed_norm=[normalize_text(a) for a in allowed_keywords] if use_whitelist else []
    include_all=settings.get("include_all",True);blocked_norm=[normalize_text(b) for b in settings.get("blocked_keywords",[])];priority_norm=[normalize_text(p) for p in settings.get("priority_keywords",[])]
    candidates=[];successful_sources=0
    for source in sources:
        if not isinstance(source,dict) or not source.get("enabled",True):continue
        url=str(source.get("url","")).strip();name=str(source.get("name",url));priority=int(source.get("priority",9999))
        if not url:continue
        try:
            r=requests.get(url,timeout=int(source.get("timeout_seconds",DEFAULT_SOURCE_TIMEOUT)),headers={"User-Agent":USER_AGENT,"Accept":"*/*"},allow_redirects=True);r.raise_for_status();lines=r.text.splitlines();successful_sources+=1
        except (RequestException,OSError) as e:logging.warning("Fuente no disponible %s: %s",name,e);continue
        for line,stream_url,directives in parse_source_entries(lines):
            if not source_allows_channel(source,line):continue
            combined=normalize_text(line+" "+stream_url)
            if use_whitelist:
                if not any(k in combined for k in allowed_norm):continue
            elif any(k in combined for k in blocked_norm):continue
            elif not include_all and not any(k in combined for k in priority_norm):continue
            candidates.append((line,stream_url,priority,directives))
    if not candidates or not successful_sources:return 1
    scored=[]
    if probe_enabled:
        with ThreadPoolExecutor(max_workers=max(1,workers)) as ex:
            futures=[ex.submit(probe_stream,x,probe_timeout) for x in candidates]
            for f in as_completed(futures):
                item,ok,lat,status,attempts=f.result();scored.append((item[0],item[1],item[2],item[3],lat,ok,attempts))
                if not ok:logging.info("URL no verificable desde GitHub (SE CONSERVA): %s (%s)",channel_name(item[0]),status)
    else:scored=[(l,u,p,d,999.0,True,0) for l,u,p,d in candidates]
    # GitHub Actions solo puntúa/ordena. No elimina URLs por 403, 404, timeout, SSL, geo-block o bloqueo de datacenter.
    seen_urls=set();unique=[]
    for line,url,priority,directives,lat,ok,attempts in sorted(scored,key=lambda x:(not x[5],-x[6],x[4],x[2],normalize_text(channel_name(x[0])))):
        canonical=url.strip()
        if canonical in seen_urls:continue
        seen_urls.add(canonical);section=infer_section(line);unique.append((set_group_title(line,section),url,priority,directives,lat,ok,attempts,section))
    sections={}
    for item in unique:sections.setdefault(item[7],[]).append(item[:7])
    preferred=["Argentina","España","Italia","Reino Unido","Estados Unidos","Brasil","Noticias","Deportes","Documentales","Películas y Series","Infantiles","Música","Entretenimiento","Internacional"]
    ordered=[s for s in preferred if s in sections]+sorted(s for s in sections if s not in preferred)
    out=["#EXTM3U"]
    for section in ordered:
        items=sorted(sections[section],key=lambda x:(not x[5],-x[6],x[4],x[2],normalize_text(channel_name(x[0]))))
        for line,url,_,directives,*_ in items:out.extend([line,*directives,url])
    Path("playlist.m3u").write_text("\n".join(out)+"\n",encoding="utf8")
    logging.info("playlist.m3u: %d canales, %d URLs únicas; %d verificadas y %d no verificables conservadas",len(unique),len(unique),sum(x[5] for x in unique),sum(not x[5] for x in unique))
    return 0
if __name__=="__main__":raise SystemExit(main())