"""Bounded cache for the specific public recommendation reads used by watch."""
import hashlib
import json
import re
import time

from .providers import Transport


class CachedTransport:
    """Use the worker's existing database/lock (an in-memory copy in dry-run)."""

    def __init__(self, db, transport=None, *, ttl_seconds=21600, max_entries=128,
                 max_bytes=8388608, force=False, clock=time.time):
        for value, lower, upper in ((ttl_seconds, 0, 604800), (max_entries, 1, 1024),
                                    (max_bytes, 1024, 33554432)):
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError('Invalid recommendation cache limits')
        self.db, self.transport = db, transport or Transport()
        self.ttl, self.max_entries, self.max_bytes = ttl_seconds, max_entries, max_bytes
        self.force, self.clock = force, clock

    @staticmethod
    def response_root(method, url, data, params):
        # Never cache authentication, scrobbling or unknown API calls.
        if method == 'POST' and url == 'https://ws.audioscrobbler.com/2.0/' and not params:
            return {'user.getTopTracks': 'toptracks', 'user.getLovedTracks': 'lovedtracks',
                    'track.getSimilar': 'similartracks'}.get((data or {}).get('method'))
        if method == 'GET' and not data:
            if re.fullmatch(r'https://api\.listenbrainz\.org/1/user/[^/?#]+/playlists/createdfor', url):
                return 'playlists'
            if re.fullmatch(r'https://api\.listenbrainz\.org/1/playlist/[0-9a-fA-F-]{36}', url):
                return 'playlist'
        return None

    def json(self, method, url, *, data=None, params=None):
        root = self.response_root(method, url, data, params)
        if root is None or self.ttl == 0:
            return self.transport.json(method, url, data=data, params=params)
        # All request parameters, including credential identity, affect the digest;
        # no URL, username, API key or request body is stored as cache metadata.
        key = hashlib.sha256(json.dumps([method, url, data, params], sort_keys=True,
                                        separators=(',', ':')).encode()).hexdigest()
        now = self.clock()
        if not self.force:
            row = self.db.execute('SELECT stored,payload FROM recommendation_http_cache WHERE key=?',
                                  (key,)).fetchone()
            if row and 0 <= now - row[0] < self.ttl:
                try:
                    value = json.loads(row[1])
                    if isinstance(value, dict) and root in value and 'error' not in value:
                        return value
                except (ValueError, TypeError):
                    pass  # A damaged entry is a miss, never a fabricated result.
        result = self.transport.json(method, url, data=data, params=params)
        if not isinstance(result, dict) or 'error' in result or root not in result:
            return result  # API-level errors and malformed responses must not be cached.
        payload = json.dumps(result, ensure_ascii=False, separators=(',', ':'))
        size = len(payload.encode())
        secret = (data or {}).get('api_key')
        if size > min(self.max_bytes, 2 * 1024 * 1024) or (secret and secret in payload):
            return result
        with self.db:
            self.db.execute('DELETE FROM recommendation_http_cache WHERE stored<=? OR stored>?',
                            (now - self.ttl, now))
            self.db.execute('INSERT OR REPLACE INTO recommendation_http_cache VALUES (?,?,?,?)',
                            (key, now, payload, size))
            # Evict oldest entries until both logical payload budgets are satisfied.
            rows = self.db.execute('SELECT key,bytes FROM recommendation_http_cache '
                                   'ORDER BY stored,key').fetchall()
            total, count = sum(row[1] for row in rows), len(rows)
            for old_key, old_size in rows:
                if count <= self.max_entries and total <= self.max_bytes:
                    break
                self.db.execute('DELETE FROM recommendation_http_cache WHERE key=?', (old_key,))
                count, total = count - 1, total - old_size
        return result
