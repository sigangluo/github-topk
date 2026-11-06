"""Local paths and authenticated GitHub API access for the standalone catalog."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
RANKING_PATH = DATA / 'ranking.json'
API = 'https://api.github.com'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def token():
    value = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if value:
        return value
    try:
        result = subprocess.run(['gh', 'auth', 'token'], text=True, capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError('GitHub authentication unavailable; run gh auth login or set GH_TOKEN') from exc
    value = result.stdout.strip()
    if not value:
        raise RuntimeError('GitHub authentication unavailable; run gh auth login or set GH_TOKEN')
    return value


class GitHub:
    def __init__(self, auth=None):
        self.auth = auth or token()
        self._search_lock = threading.Lock()
        self._next_search_at = 0.0

    def _request(self, url, body=None):
        headers = {'Authorization': 'Bearer ' + self.auth,
                   'Accept': 'application/vnd.github+json', 'User-Agent': 'github-topk'}
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            headers['Content-Type'] = 'application/json'
        last = None
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, data=data, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return None
                last = f'HTTP {exc.code}'
                wait = min(60, 3 * (attempt + 1))
                if exc.code in (403, 429):
                    retry = exc.headers.get('Retry-After')
                    if retry and retry.isdigit():
                        wait = min(60, int(retry) + 1)
            except (urllib.error.URLError, TimeoutError) as exc:
                last = str(exc)
                wait = 3 * (attempt + 1)
            if attempt < 3:
                time.sleep(wait)
        raise RuntimeError(f'GitHub request failed: {url} ({last})')

    def rest(self, path, **params):
        suffix = '?' + urllib.parse.urlencode(params) if params else ''
        return self._request(API + path + suffix)

    def graphql(self, query):
        result = self._request(API + '/graphql', {'query': query})
        if result.get('errors'):
            raise RuntimeError(f'GitHub GraphQL errors: {result["errors"]}')
        return result['data']

    def search_repos(self, q, page=1, per_page=100):
        # Space starts of Search requests even when pages are fetched concurrently.
        with self._search_lock:
            wait = self._next_search_at - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._next_search_at = time.monotonic() + 2.3
        return self.rest('/search/repositories', q=q, sort='stars', order='desc', page=page, per_page=per_page)
