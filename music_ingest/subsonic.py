"""Bounded OpenSubsonic adapter. Credentials only travel in POST bodies."""
import hashlib
from contextlib import closing
import json
from pathlib import Path
import secrets
import sqlite3
from urllib.parse import urlsplit

import requests


class SubsonicError(RuntimeError):
    pass


def credentials(path: Path):
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError('Credentials must be a private regular file (0600)')
    if path.stat().st_size > 8192:
        raise ValueError('Credentials file too large')
    value = json.loads(path.read_text())
    if any(not isinstance(value.get(k), str) or not value[k] for k in ('username', 'password')):
        raise ValueError('Missing credentials')
    return value


class Subsonic:
    def __init__(self, url, username, password, session=None, catalog_db=None, library_id=1):
        parsed = urlsplit(url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Invalid server URL')
        if parsed.scheme != 'https' and not (
            parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', '::1', 'localhost'}
        ):
            raise ValueError('HTTPS required except on loopback')
        self.url, self.username, self.password = url.rstrip('/'), username, password
        self.session = session or requests.Session()
        self.catalog_db, self.library_id = catalog_db, library_id

    def call(self, endpoint, **params):
        salt = secrets.token_hex(16)
        data = dict(u=self.username, t=hashlib.md5((self.password + salt).encode()).hexdigest(),
                    s=salt, v='1.16.1', c='home-music', f='json', **params)
        try:
            # Mutations are never retried blindly: the ownership journal handles recovery.
            with self.session.post(self.url + '/rest/' + endpoint, data=data,
                                   timeout=(5, 30), allow_redirects=False, stream=True) as response:
                if response.status_code != 200:
                    raise SubsonicError('Navidrome HTTP failure')
                content = bytearray()
                for block in response.iter_content(65536):
                    content.extend(block)
                    if len(content) > 8 * 1024 * 1024:
                        raise SubsonicError('Navidrome response too large')
                value = json.loads(content)['subsonic-response']
                if value['status'] != 'ok':
                    code = value.get('error', {}).get('code')
                    raise SubsonicError('Navidrome API error ' + str(code) if isinstance(code, int)
                                        else 'Navidrome API failure')
                return value
        except (requests.RequestException, ValueError, KeyError, TypeError):
            raise SubsonicError('Navidrome transport or response failure') from None

    def catalog(self, music_root: Path):
        """Return only catalog entries whose physical file is still present."""
        music_root = music_root.resolve()
        physical = None
        if self.catalog_db:
            # Navidrome's API path is virtual, based on tags, not a disk filename.
            # Isolate its version-dependent schema here; read WAL consistently.
            try:
                uri = Path(self.catalog_db).resolve().as_uri() + '?mode=ro'
                with closing(sqlite3.connect(uri, uri=True, timeout=5)) as db:
                    physical = dict(db.execute('SELECT id,path FROM media_file WHERE library_id=?',
                                               (self.library_id,)).fetchall())
            except sqlite3.Error:
                raise SubsonicError('Navidrome physical catalog unavailable or schema unsupported') from None
        result, seen = {}, set()
        for offset in range(0, 100000, 500):
            songs = self.call('search3', query='', songCount=500, songOffset=offset,
                              artistCount=0, albumCount=0).get('searchResult3', {}).get('song', [])
            for song in songs:
                if song['id'] in seen:
                    raise SubsonicError('Catalog pagination repeated an ID')
                seen.add(song['id'])
                # Intersect API-visible IDs with physical paths; never grant access
                # to songs hidden from the authenticated account.
                relative = physical.get(song['id'], '') if physical is not None else song.get('path', '')
                path = (music_root / relative).resolve()
                if music_root in path.parents and path.is_file():
                    result[path] = song['id']
            if len(songs) < 500:
                return result
        raise SubsonicError('Catalog exceeds safety limit')


def mirror(api, db, source, name, song_ids):
    """Journal ownership BEFORE creating. Never adopt a personal playlist by name."""
    ids = list(dict.fromkeys(song_ids))
    row = db.execute('SELECT token,playlist_id FROM mirrors WHERE source=?', (source,)).fetchone()
    if not row:
        token = secrets.token_hex(16)
        with db:
            db.execute('INSERT INTO mirrors(source,token) VALUES (?,?)', (source, token))
        row = token, None
    token, playlist_id = row
    marker, temporary_name = 'home-music:' + token, '__home_music__' + token
    if not playlist_id:
        playlists = api.call('getPlaylists').get('playlists', {}).get('playlist', [])
        owned = [p for p in playlists if p.get('owner') == api.username and
                 (p.get('comment') == marker or p.get('name') == temporary_name)]
        if len(owned) > 1:
            raise SubsonicError('Multiple playlists claim the same ownership')
        if owned:
            playlist_id = owned[0]['id']
        else:
            playlist_id = api.call('createPlaylist', name=temporary_name, songId=ids)['playlist']['id']
        with db:
            db.execute('UPDATE mirrors SET playlist_id=? WHERE source=?', (playlist_id, source))
    current = api.call('getPlaylist', id=playlist_id)['playlist']
    if current.get('owner') != api.username or not (
        current.get('comment') == marker or current.get('name') == temporary_name
    ):
        raise SubsonicError('Playlist ownership changed; refusing mutation')
    if current.get('readonly'):
        raise SubsonicError('Playlist is read-only')
    old_ids = [song['id'] for song in current.get('entry', [])]
    changed = (old_ids != ids or current.get('name') != name
               or current.get('comment') != marker or current.get('public') is not True)
    if changed:
        with db:
            db.execute('INSERT INTO playlist_backups(source,payload) VALUES (?,?)',
                       (source, json.dumps(current)))
        if old_ids != ids:
            if ids:
                api.call('createPlaylist', playlistId=playlist_id, songId=ids)
            else:
                # Navidrome 0.64 treats createPlaylist without songId as no replacement.
                api.call('updatePlaylist', playlistId=playlist_id,
                         songIndexToRemove=list(range(len(old_ids))))
        api.call('updatePlaylist', playlistId=playlist_id, name=name, comment=marker, public='true')
    verified = api.call('getPlaylist', id=playlist_id)['playlist']
    if (verified['name'] != name or [s['id'] for s in verified.get('entry', [])] != ids
            or verified.get('public') is not True):
        raise SubsonicError('Playlist verification failed')
    return dict(id=playlist_id, changed=changed, playable=len(ids))
