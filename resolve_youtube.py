import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

WEB = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}


def is_youtube(url):
    host = urlparse(url.split('|', 1)[0].strip()).netloc.lower().split(':')[0]
    return host in WEB or host.endswith('.youtube.com')


def run_ytdlp(url, extra_args=None, timeout=120):
    cmd = [
        sys.executable, '-m', 'yt_dlp',
        '--no-playlist', '--no-warnings', '--ignore-config',
        '--extractor-retries', '3', '--fragment-retries', '3',
        '--retry-sleep', 'http:2',
        '--geo-bypass', '--js-runtimes', 'node',
        '-J'
    ]
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(url)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def resolve(url):
    attempts = [
        [],
        ['--extractor-args', 'youtube:player_client=web,ios,android'],
        ['--extractor-args', 'youtube:player_client=android_vr,web_safari']
    ]
    errors = []
    for extra in attempts:
        try:
            p = run_ytdlp(url, extra)
        except subprocess.TimeoutExpired:
            errors.append('timeout')
            continue
        if p.returncode != 0:
            err = (p.stderr or p.stdout or '').strip().replace('\n', ' ')
            errors.append(err[:500] or f'exit {p.returncode}')
            continue
        try:
            info = json.loads(p.stdout)
        except json.JSONDecodeError as e:
            errors.append(f'json error: {e}')
            continue
        direct = info.get('url')
        if not direct:
            errors.append('no direct URL')
            continue
        headers = info.get('http_headers') or {}
        pairs = []
        for key in ('User-Agent', 'Referer', 'Origin', 'Cookie'):
            value = headers.get(key) or headers.get(key.lower())
            if value:
                pairs.append(f'{key}={value}')
        if pairs:
            direct += '|' + '&'.join(pairs)
        return direct, 'ok', None
    return None, 'failed', errors[-1] if errors else 'unknown error'


def main():
    src = Path('playlist.m3u').read_text(encoding='utf-8').splitlines()
    out = ['#EXTM3U']
    audit = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'resolved': [], 'failed': []
    }
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
            direct, status, error = resolve(s)
            channel = pending[0].rsplit(',', 1)[-1].strip()
            if direct:
                out.extend(pending)
                out.append(direct)
                audit['resolved'].append({'channel': channel, 'source_url': s, 'status': status})
            else:
                audit['failed'].append({'channel': channel, 'source_url': s, 'status': status, 'error': error})
            pending = []
            continue
        pending = []
    Path('youtube-live.m3u').write_text('\n'.join(out) + '\n', encoding='utf-8')
    Path('youtube-audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"YouTube directos: {len(audit['resolved'])}; fallidos: {len(audit['failed'])}")


if __name__ == '__main__':
    main()
