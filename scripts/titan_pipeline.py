#!/usr/bin/env python3
"""TITAN IPTV v2: deterministic source merge, URL dedupe and country playlists."""
from __future__ import annotations
import hashlib, json, re, sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

COUNTRIES = {"AR":"Argentina","ES":"España","IT":"Italia","GB":"Reino Unido","US":"Estados Unidos","BR":"Brasil"}
COUNTRY_HINTS = {"AR":["argentina","arg"],"ES":["spain","españa","espana","spanish","es"],"IT":["italy","italia","ita"],"GB":["uk","united kingdom","british","gb","england"],"US":["usa","united states","us","america"],"BR":["brazil","brasil","br"]}

def normalize_url(url: str) -> str:
    p=urlsplit(url.strip())
    if p.scheme.lower() not in {"http","https"} or not p.netloc: return ""
    return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path or "/",p.query,p.fragment))

def detect_country(text: str, fallback: str="") -> str:
    s=text.lower()
    for code,hints in COUNTRY_HINTS.items():
        if any(re.search(r"(?<![a-z])"+re.escape(h)+r"(?![a-z])",s) for h in hints): return code
    return fallback if fallback in COUNTRIES else ""

def parse_m3u(text: str, source: str):
    rows=[]; meta={}
    for line in text.splitlines():
        line=line.strip()
        if line.startswith('#EXTINF:'):
            attrs=dict(re.findall(r'(\w+(?:-\w+)*)="([^"]*)"',line))
            name=line.rsplit(',',1)[-1].strip() if ',' in line else attrs.get('tvg-name','Unknown')
            meta={"name":name,"attrs":attrs}
        elif line and not line.startswith('#'):
            u=normalize_url(line)
            if u and meta:
                a=meta["attrs"]; rows.append({"name":meta["name"],"url":u,"country":detect_country(' '.join([meta['name'],a.get('tvg-country',''),a.get('group-title','')]), a.get('tvg-country','')),"group":a.get('group-title','General'),"logo":a.get('tvg-logo',''),"source":source})
            meta={}
    return rows

def dedupe(rows):
    out=[]; seen=set()
    for r in rows:
        key=r['url']
        if key in seen: continue
        seen.add(key); out.append(r)
    return out

def write_m3u(rows, path):
    lines=['#EXTM3U']
    for r in rows:
        attrs=f'tvg-name="{r["name"].replace(chr(34), chr(39))}"'
        if r.get('logo'): attrs+=f' tvg-logo="{r["logo"].replace(chr(34), chr(39))}"'
        if r.get('country'): attrs+=f' tvg-country="{r["country"]}"'
        attrs+=f' group-title="{r.get("group","General").replace(chr(34), chr(39))}"'
        lines += [f'#EXTINF:-1 {attrs},{r["name"]}', r['url']]
    Path(path).parent.mkdir(parents=True,exist_ok=True); Path(path).write_text('\n'.join(lines)+'\n',encoding='utf-8')

def main():
    if len(sys.argv)<2: print('usage: titan_pipeline.py input.m3u [output_dir]'); return 2
    src=Path(sys.argv[1]); out=Path(sys.argv[2] if len(sys.argv)>2 else 'playlists/TITAN')
    rows=dedupe(parse_m3u(src.read_text(encoding='utf-8',errors='replace'),src.name))
    write_m3u(rows,out/'all.m3u')
    for code,name in COUNTRIES.items(): write_m3u([r for r in rows if r['country']==code],out/f'{code.lower()}.m3u')
    report={'source':str(src),'total_unique_urls':len(rows),'countries':{c:sum(r['country']==c for r in rows) for c in COUNTRIES},'sha256':hashlib.sha256(src.read_bytes()).hexdigest()}
    (out/'build-report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    return 0
if __name__=='__main__': raise SystemExit(main())
