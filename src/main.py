import requests, yaml
from pathlib import Path

def main():
    sources=yaml.safe_load(open('config/sources.yml'))['sources']
    allowed=yaml.safe_load(open('config/settings.yml'))['allowed_keywords']
    seen=set(); out=['#EXTM3U']
    for s in sources:
        try: lines=requests.get(s,timeout=30).text.splitlines()
        except: continue
        for i,l in enumerate(lines):
            if l.startswith('#EXTINF') and i+1<len(lines):
                u=lines[i+1]
                if u in seen: continue
                if any(a in (l+' '+u).lower() for a in allowed):
                    out += [l,u]; seen.add(u)
    Path('playlist.m3u').write_text('\n'.join(out),encoding='utf8')
if __name__=='__main__': main()
