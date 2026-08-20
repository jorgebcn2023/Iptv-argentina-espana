import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

WEB = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}


def is_youtube(url):
    host = urlparse(url.split('|', 1)[0].strip()).netloc.lower().split(':')[0]
    return host in WEB or host.endswith('.youtube.com')


def resolve(url):
    cmd = [sys.executable, '-m', 'yt_dlp', '--no-playlist', '--no-warnings', '-J', url]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=45, check=True)
        info = json.loads(p.stdout)
        direct = info.get('url')
        if not direct:
            return None, 'no direct URL'
        headers = info.get('http_headers') or {}
        pairs = []
        mapping = {'User-Agent': 'User-Agent', 'Referer': 'Referer', 'Origin': 'Origin', 'Cookie': 'Cookie'}
        for src, dst in mapping.items():
            value = headers.get(src) or headers.get(src.lower())
            if value:
                pairs.append(f'{dst}={value}')
        if pairs:
            direct += '|' + '&'.join(pairs)
        return direct, 'ok'
    except subprocess.TimeoutExpired:
        return None, 'timeout'
    except Exception as e:
        return None, type(e).__name__


def main():
    src = Path('playlist.m3u').read_text(encoding='utf-8').splitlines()
    out = ['#EXTM3U']
    audit = {'generated_at': __import__('datetime').datetime.utcnow().isoformat() + 'Z', 'resolved': [], 'failed': []}
    pending = []
    for line in src:
        s = line.strip()
        if not s:
            continue
        if s.startswith('#EXTINF'):
            pending = [s]
            continue
        if s.startswith('#'):
            if pending:
                pending.append(s)
            continue
        if pending and is_youtube(s):
            direct, status = resolve(s)
            channel = pending[0].rsplit(',', 1)[-1].strip()
            if direct:
                out.extend(pending)
                out.append(direct)
                audit['resolved'].append({'channel': channel, 'source_url': s, 'status': status})
            else:
                audit['failed'].append({'channel': channel, 'source_url': s, 'status': status})
            pending = []
            continue
        pending = []
    Path('youtube-live.m3u').write_text('\n'.join(out) + '\n', encoding='utf-8')
    Path('youtube-audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"YouTube directos: {len(audit['resolved'])}; fallidos: {len(audit['failed'])}")


if __name__ == '__main__':
    main()
