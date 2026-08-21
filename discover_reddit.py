import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
USER_AGENT = 'IPTV-Playlist-Discovery/1.0 (public source indexer)'
OUT = Path('config/reddit-sources.json')
URL_RE = re.compile(r'https?://[^\s<>()\[\]{}"\']+', re.I)
PLAYLIST_RE = re.compile(r'\.(?:m3u8?|txt)(?:$|[?#])|raw\.githubusercontent\.com/.+|github\.com/[^/]+/[^/]+/(?:raw|blob)/.+\.(?:m3u8?|txt)(?:$|[?#])', re.I)


def load_settings():
    try:
        return yaml.safe_load(Path('config/reddit.yml').read_text(encoding='utf-8')) or {}
    except FileNotFoundError:
        return {}


def normalize_url(url):
    url = url.rstrip('.,;:!?)]}')
    if 'github.com/' in url and '/blob/' in url:
        parts = urlparse(url)
        bits = parts.path.strip('/').split('/')
        if len(bits) >= 5 and bits[2] == 'blob':
            return 'https://raw.githubusercontent.com/' + '/'.join([bits[0], bits[1]] + bits[3:])
    return url


def allowed(url, settings):
    p = urlparse(url)
    if p.scheme != 'https':
        return False
    host = p.hostname or ''
    allowed_hosts = {x.lower() for x in settings.get('allowed_hosts', [])}
    if allowed_hosts and not any(host == x or host.endswith('.' + x) for x in allowed_hosts):
        return False
    return bool(PLAYLIST_RE.search(url))


def main():
    s = load_settings()
    if not s.get('enabled', True):
        OUT.write_text(json.dumps({'generated_at': datetime.now(timezone.utc).isoformat(), 'sources': []}, indent=2) + '\n', encoding='utf-8')
        return 0
    subreddits = s.get('subreddits', ['IPTV'])
    limit = max(1, min(int(s.get('posts_per_subreddit', 25)), 100))
    priority = int(s.get('priority', 200))
    timeout = int(s.get('timeout_seconds', 15))
    discovered = {}
    headers = {'User-Agent': USER_AGENT, 'Accept': 'application/json'}
    for sub in subreddits:
        endpoint = f'https://www.reddit.com/r/{sub}/new.json?limit={limit}&raw_json=1'
        try:
            r = requests.get(endpoint, headers=headers, timeout=timeout)
            r.raise_for_status()
            posts = r.json().get('data', {}).get('children', [])
        except (requests.RequestException, ValueError) as e:
            logging.warning('Reddit %s no disponible: %s', sub, type(e).__name__)
            continue
        for child in posts:
            d = child.get('data') or {}
            text = '\n'.join(str(d.get(k) or '') for k in ('url', 'selftext', 'title'))
            for raw in URL_RE.findall(text):
                url = normalize_url(raw)
                if not allowed(url, s):
                    continue
                key = url.split('#', 1)[0]
                discovered.setdefault(key, {
                    'name': f'reddit_{sub}_{len(discovered)+1}',
                    'enabled': True,
                    'priority': priority,
                    'timeout_seconds': timeout,
                    'url': key,
                    'origin': 'reddit',
                    'subreddit': sub,
                    'post_url': 'https://www.reddit.com' + str(d.get('permalink') or ''),
                    'first_seen': datetime.now(timezone.utc).isoformat(),
                })
    payload = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'sources': list(discovered.values()),
        'count': len(discovered),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    logging.info('Fuentes públicas candidatas descubiertas en Reddit: %s', len(discovered))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
