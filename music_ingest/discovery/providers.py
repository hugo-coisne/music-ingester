"""External APIs isolated behind small bounded adapters; no acquisition endpoints."""
import time
from urllib.parse import quote, urlparse

import requests

from .. import identity, library
from .core import Candidate, ProviderError


class Transport:
    """Read calls only. Never include credentials in URLs or exception messages."""
    def __init__(self, session=None, sleep=time.sleep):
        self.session = session or requests.Session()
        self.sleep = sleep

    def json(self, method: str, url: str, *, data=None, params=None):
        if not url.startswith('https://'):
            raise ProviderError('HTTPS required')
        for attempt in range(3):
            self.sleep(0.25 if attempt == 0 else 2 ** (attempt - 1))
            try:
                with self.session.request(method, url, data=data, params=params,
                                          timeout=(3, 15), allow_redirects=False,
                                          headers={'User-Agent': 'home-music-discovery/0.1'},
                                          stream=True) as response:
                    if response.status_code == 204:
                        return {}
                    if response.status_code == 429 or response.status_code >= 500:
                        continue
                    if response.status_code != 200:
                        raise ProviderError('Provider HTTP failure')
                    content = bytearray()
                    for block in response.iter_content(65536):
                        content.extend(block)
                        if len(content) > 2 * 1024 * 1024:
                            raise ProviderError('Response too large')
                    import json
                    result = json.loads(content)
                    if not isinstance(result, dict):
                        raise ProviderError('Invalid response shape')
                    return result
            except requests.RequestException:
                continue
            except ValueError:
                raise ProviderError('Invalid JSON') from None
        raise ProviderError('Provider unavailable after three attempts')


def rows(value):
    if value is None or value == '':
        return []
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list) or any(not isinstance(x, dict) for x in value):
        raise ProviderError('Unexpected API collection')
    return value


class LastFM:
    name = 'lastfm'

    def __init__(self, username: str, api_key: str, transport=None):
        self.username, self.api_key = username, api_key
        self.transport = transport or Transport()

    def call(self, method, **params):
        if not self.username or not self.api_key:
            raise ProviderError('Last.fm username and API key required')
        # POST keeps the API key out of URLs. Real-service compatibility is an
        # explicit integration gate until a user-owned API key is configured.
        data = self.transport.json('POST', 'https://ws.audioscrobbler.com/2.0/',
                                   data=dict(method=method, api_key=self.api_key,
                                             format='json', **params))
        if 'error' in data:
            raise ProviderError('Last.fm API rejected the request')
        return data

    def candidates(self):
        top = self.call('user.getTopTracks', user=self.username, period='3month', limit=5)
        loved = self.call('user.getLovedTracks', user=self.username, limit=5)
        seeds = rows(top['toptracks'].get('track')) + rows(loved['lovedtracks'].get('track'))
        seen = set()
        for seed in seeds[:10]:
            artist = seed.get('artist', {}).get('name')
            title = seed.get('name')
            if not artist or not title or (artist, title) in seen:
                continue
            seen.add((artist, title))
            similar = self.call('track.getSimilar', artist=artist, track=title,
                                autocorrect=0, limit=25)
            for item in rows(similar['similartracks'].get('track'))[:25]:
                raw_score = float(item.get('match', 0))
                if raw_score < 0:
                    continue
                yield Candidate(self.name, item['artist']['name'], item['name'],
                                raw_score / (1 + raw_score),
                                f'Similar to {artist} — {title}; Last.fm match={raw_score}',
                                recording_mbid=identity.mbid(item.get('mbid')))


class ListenBrainz:
    name = 'listenbrainz'

    def __init__(self, username: str, transport=None):
        self.username = username
        self.transport = transport or Transport()

    def candidates(self):
        if not self.username:
            return
        base = 'https://api.listenbrainz.org/1/'
        listing = self.transport.json('GET', base + 'user/' + quote(self.username, safe='')
                                      + '/playlists/createdfor', params={'count': 25})
        # No private/experimental recommendation endpoint is required.
        selected = {}
        if not listing:
            return
        for item in rows(listing['playlists']):
            playlist = item['playlist']
            name = playlist['title'].casefold()
            kind = next((x for x in ('weekly exploration', 'weekly jams') if x in name), None)
            if not kind:
                continue
            if kind not in selected or playlist.get('date', '') > selected[kind].get('date', ''):
                selected[kind] = playlist
        for kind, info in sorted(selected.items()):
            playlist_id = identity.mbid(urlparse(info['identifier']).path.rstrip('/').split('/')[-1])
            if not playlist_id:
                raise ProviderError('Invalid playlist identifier')
            response = self.transport.json('GET', base + 'playlist/' + playlist_id,
                                           params={'fetch_metadata': 'true'})
            for position, item in enumerate(rows(response['playlist'].get('track'))[:25]):
                identifiers = item.get('identifier') or []
                if isinstance(identifiers, str):
                    identifiers = [identifiers]
                recording = next((identity.mbid(urlparse(x).path.rstrip('/').split('/')[-1])
                                  for x in identifiers if '/recording/' in x), None)
                if not item.get('creator') or not item.get('title'):
                    continue  # An unresolved MBID is not an invented title.
                yield Candidate(self.name, item['creator'], item['title'], 1 / (1 + position / 25),
                                f'{kind}; playlist={playlist_id}; position={position + 1}',
                                album=item.get('album'), recording_mbid=recording,
                                duration=float(item['duration']) / 1000 if item.get('duration') else None)


class LocalLibrary:
    """Explicit artist seeds only: do not pretend random files reflect user taste."""
    name = 'local'

    def __init__(self, index: dict, artists: list[str]):
        self.index = index
        self.artists = {library.normalize_text(a) for a in artists}

    def candidates(self):
        seen = set()
        for items in self.index.values():
            for item in items:
                if item['path'] in seen or not item['path'].is_file():
                    continue
                seen.add(item['path'])
                if not self.artists.intersection(library.normalize_text(a) for a in item['artists']):
                    continue
                yield Candidate(self.name, item['artists'][0], item['title'], 0.5,
                                'Local recording by an explicitly selected seed artist',
                                duration=item['duration'], recording_mbid=item.get('recording_mbid'),
                                isrc=item.get('isrc'))
