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
USER_AGENT = "IPTV-Argentina-Espana/11.0"
PROBE_TIMEOUT = (3, 5)
WORKERS = 48
WEB_HOSTS = {"youtube.com","www.youtube.com","youtu.be","m.youtube.com","twitch.tv","www.twitch.tv","facebook.com","www.facebook.com","instagram.com","www.instagram.com","tiktok.com","www.tiktok.com","twitter.com","x.com"}
COUNTRY_NAMES = {"AR":"Argentina","ES":"España","IT":"Italia","GB":"Reino Unido","UK":"Reino Unido","US":"Estados Unidos","BR":"Brasil"}
GENRES = [("Noticias",["news","noticia","noticias","cnn","bbc news","c5n","america noticias"]),("Deportes",["sport","sports","deporte","deportes","espn","fox sports","tyc sports","tnt sports","dazn"]),("Documentales",["documental","documentary","history","nat geo","national geographic","discovery","animal planet"]),("Infantiles",["kids","infantil","disney","nick","nickelodeon","cartoon","baby","junior"]),("Películas y Series",["movie","movies","cine","pelicula","peliculas","series","film","axn","fx","warner","universal","paramount"]),("Música",["music","musica","mtv","vh1","vevo","hit","hits"]),("Entretenimiento",["entertainment","entretenimiento","reality","show","comedy"])]

def norm(v):
    v=unicodedata.normalize("NFKD",str(v or "")); return "".join(c for c in v if not unicodedata.combining(c)).lower().strip()
def load(p):
    try:
        with open(p,encoding="utf-8") as f:return yaml.safe_load(f) or {}
    except Exception as e: logging.error("No se puede leer %s: %s",p,e); return {}
def attr(line,key):
    m=re.search(rf'{re.escape(key)}=["\']([^"\']*)["\']',line,re.I); return m.group(1).strip() if m else ""
def channel_name(line):
    return line[line.rfind(",")+1:].strip()
def country(line):
    raw=attr(line,"tvg-country") or attr(line,"country"); return {x for x in re.split(r"[,;|/ ]+",raw.upper()) if x} if raw else set()
def infer_country(line):
    for c in country(line):
        if c in COUNTRY_NAMES:return COUNTRY_NAMES[c]
    t=norm(line)
    for label,keys in [("Argentina",["argentina"]),("España",["espana","españa","spain"]),("Italia",["italia","italy"]),("Reino Unido",["reino unido","united kingdom","british"]),("Estados Unidos",["united states","usa","american"]),("Brasil",["brasil","brazil"])]:
        if any(k in t for k in keys):return label
    return "Internacional"
def section(line):
    g=attr(line,"group-title").strip()
    if g and norm(g) not in {"-","_","n/a","null","none","general"}:return g
    t=norm(line+" "+channel_name(line))
    for label,keys in GENRES:
        if any(norm(k) in t for k in keys):return label
    return infer_country(line)
def set_group(line,g):
    if attr(line,"group-title").strip():return line
    p=line.rfind(","); return line[:p]+f' group-title="{g}"'+line[p:]
def stream_url(v):return v.strip().lower().startswith(("http://","https://","rtmp://","rtmps://","rtsp://","udp://","srt://","acestream://"))
def parse(lines):
    out=[]; i=0
    while i<len(lines):
        if not lines[i].strip().startswith("#EXTINF"):i+=1;continue
        ext=lines[i].strip(); directives=[]; url=""; j=i+1
        while j<len(lines):
            x=lines[j].strip()
            if not x:j+=1;continue
            if x.startswith("#EXTINF"):break
            if x.startswith("#"):directives.append(x);j+=1;continue
            if stream_url(x):url=x;break
            j+=1
        if url:out.append((ext,url,directives))
        i=max(j,i+1)
    return out
def base_url(u):return u.split("|",1)[0].strip()
def headers(ds,u):
    h={"User-Agent":USER_AGENT,"Accept":"*/*","Connection":"close"}
    if "|" in u:
        for p in re.split(r"[|&]",u.split("|",1)[1]):
            if "=" in p:
                k,v=p.split("=",1); k=k.strip().lower(); mp={"user-agent":"User-Agent","http-user-agent":"User-Agent","referer":"Referer","http-referrer":"Referer","origin":"Origin","cookie":"Cookie"}.get(k)
                if mp:h[mp]=v.strip()
    for d in ds:
        l=d.lower()
        if l.startswith("#extvlcopt:http-referrer="):h["Referer"]=d.split("=",1)[1].strip()
        elif l.startswith("#extvlcopt:http-origin="):h["Origin"]=d.split("=",1)[1].strip()
        elif l.startswith("#extvlcopt:http-user-agent="):h["User-Agent"]=d.split("=",1)[1].strip()
    return h
def kind(u):
    p=urlparse(base_url(u)); host=p.netloc.lower().split(":")[0]; path=p.path.lower()
    if host in WEB_HOSTS or host.endswith(".youtube.com") or host.endswith(".twitch.tv"):return 2
    if p.scheme in {"rtmp","rtmps","rtsp","udp","srt","acestream"} or any(x in path for x in (".m3u8",".m3u",".mpd",".ts","/hls/","/live/","/playlist","/manifest")):return 0
    return 1
def probe_hls(url,r,h):
    if "text/html" in (r.headers.get("content-type") or "").lower():return False,"HTML response"
    text=r.text[:131072]
    if not text.lstrip().startswith("#EXTM3U"):return False,"not an M3U response"
    lines=text.splitlines()
    if any(x.startswith("#EXTINF:") for x in lines):return True,"ok"
    for i,x in enumerate(lines[:-1]):
        if x.startswith("#EXT-X-STREAM-INF") and lines[i+1].strip() and not lines[i+1].startswith("#"):
            try:
                with requests.get(urljoin(url,lines[i+1].strip()),stream=True,timeout=PROBE_TIMEOUT,headers=h,allow_redirects=True) as c:
                    ok=c.status_code<400 and bool(next(c.iter_content(1024),b""));return ok,"ok" if ok else "variant unavailable"
            except requests.RequestException:return False,"variant unavailable"
    return False,"empty/invalid HLS playlist"
def probe(item):
    ext,u,ds,*_=item; k=kind(u)
    if k==2:return item,False,999.0,"web/resolver required",k
    started=monotonic(); q=base_url(u); h=headers(ds,u)
    try:
        with requests.get(q,stream=True,timeout=PROBE_TIMEOUT,headers=h,allow_redirects=True) as r:
            if r.status_code>=400:return item,False,monotonic()-started,f"HTTP {r.status_code}",k
            if k==0 and (q.lower().endswith((".m3u8",".m3u")) or "mpegurl" in (r.headers.get("content-type") or "").lower()):ok,status=probe_hls(q,r,h)
            else:ok=bool(next(r.iter_content(4096),b"")) and "text/html" not in (r.headers.get("content-type") or "").lower();status="ok" if ok else "empty/html response"
            return item,ok,monotonic()-started,status,k
    except requests.RequestException as e:return item,False,monotonic()-started,type(e).__name__,k
def allowed_source(src,ext):
    a=src.get("allowed_countries")
    if not a:return True
    a={str(x).upper() for x in a};return bool(country(ext)&a) or infer_country(ext) in {COUNTRY_NAMES.get(x,"") for x in a}
def fetch_source(src,order):
    name=str(src.get("name",src.get("url",""))); url=str(src.get("url","")).strip(); audit={"name":name,"url":url,"priority":int(src.get("priority",9999)),"status":"unavailable","entries":0,"accepted":0}
    try:
        t=int(src.get("timeout_seconds",15)); r=requests.get(url,timeout=(min(5,t),t),headers={"User-Agent":USER_AGENT,"Accept":"*/*"},allow_redirects=True);r.raise_for_status(); es=parse(r.text.splitlines());audit.update(status="ok",entries=len(es));return order,src,es,audit
    except requests.RequestException as e:audit["error"]=type(e).__name__;return order,src,[],audit
def write_playlist(path,items):
    out=["#EXTM3U"]; groups=defaultdict(list)
    for x in items:groups[section(x[0])].append(x)
    preferred=["Argentina","España","Italia","Reino Unido","Estados Unidos","Brasil","Noticias","Deportes","Documentales","Películas y Series","Infantiles","Música","Entretenimiento","Internacional"]
    for g in [x for x in preferred if x in groups]+sorted(x for x in groups if x not in preferred):
        for ext,u,ds,*rest in sorted(groups[g],key=lambda x:(x[3],x[6],norm(channel_name(x[0])),x[7])):out.extend([ext,*ds,u])
    Path(path).write_text("\n".join(out)+"\n",encoding="utf-8")
def main():
    cfg,settings=load("config/sources.yml"),load("config/settings.yml");blocked=[norm(x) for x in settings.get("blocked_keywords",[])];allowed=[norm(x) for x in settings.get("allowed_keywords",[])]
    enabled=[(i,s) for i,s in enumerate(cfg.get("sources",[])) if isinstance(s,dict) and s.get("enabled",True) and s.get("url")]; source_results=[]
    with ThreadPoolExecutor(max_workers=min(max(1,int(settings.get("source_workers",8))),max(1,len(enabled)))) as ex:
        for f in as_completed([ex.submit(fetch_source,s,i) for i,s in enabled]):source_results.append(f.result())
    source_results.sort(); candidates=[]; audit={"sources":[],"input_entries":0,"output_entries":0,"stable_entries":0,"quarantined_entries":0,"duplicates_removed":[],"probe_summary":{},"web_resolver_entries":[],"quarantined":[]};eo=0
    for so,src,entries,sa in source_results:
        for ext,u,ds in entries:
            text=norm(ext+" "+u)
            if not allowed_source(src,ext) or (allowed and not any(x in text for x in allowed)) or any(x in text for x in blocked):continue
            candidates.append((ext,u,ds,int(src.get("priority",9999)),sa["name"],so,eo));sa["accepted"]+=1;eo+=1
        audit["sources"].append(sa)
    audit["input_entries"]=len(candidates);seen=set();uniq=[]
    for x in candidates:
        key=(x[0].strip(),x[1].strip(),tuple(x[2]))
        if key in seen:audit["duplicates_removed"].append({"source":x[4],"channel":channel_name(x[0]),"url":x[1],"reason":"exact duplicate"});continue
        seen.add(key);uniq.append(x)
    results=[]
    with ThreadPoolExecutor(max_workers=min(max(1,int(settings.get("probe_workers",WORKERS))),max(1,len(uniq)))) as ex:
        for f in as_completed([ex.submit(probe,x) for x in uniq]):results.append(f.result())
    statuses=Counter(); stable=[]; full=[]; quarantine=[]
    for item,ok,lat,status,k in results:
        statuses[status]+=1;ext,u,ds,p,src,so,eo=item; record=(set_group(ext,section(ext)),u,ds,p,src,ok,lat,k,so,eo,status);full.append(record)
        if ok:stable.append(record)
        else:
            q={"source":src,"channel":channel_name(ext),"url":u,"status":status}
            quarantine.append(record);audit["quarantined"].append(q)
            if k==2:audit["web_resolver_entries"].append(q)
    write_playlist("playlist.m3u",stable);write_playlist("playlist-full.m3u",full);write_playlist("playlist-quarantine.m3u",quarantine)
    audit["probe_summary"]=dict(statuses);audit["output_entries"]=len(full);audit["stable_entries"]=len(stable);audit["quarantined_entries"]=len(quarantine)
    Path("audit.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    logging.info("Estable: %s; cuarentena: %s; total: %s",len(stable),len(quarantine),len(full));return 0
if __name__=="__main__":raise SystemExit(main())
