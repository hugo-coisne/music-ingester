"""One-shot local radios via OpenSubsonic, with verified playable IDs only."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from . import history, watch_state
from .config import load_document
from .subsonic import Subsonic, SubsonicError, credentials, mirror


def select(api, allowed, kind, seed, *, limit=25, week=None):
    if kind not in {'artist', 'song', 'genre'} or not seed.strip() or not 1 <= limit <= 100:
        raise ValueError('Invalid radio seed or limit')
    week = week or datetime.now(timezone.utc).strftime('%G-W%V')
    source = 'radio:' + hashlib.sha256(json.dumps([kind, seed], ensure_ascii=False).encode()).hexdigest()
    warnings, candidates, artist_id = [], {}, None

    def add(songs, reason):
        for song in songs:
            sid = song.get('id')
            if sid in allowed and sid not in candidates:
                candidates[sid] = dict(id=sid, title=song.get('title', ''),
                                       artist=song.get('artist', ''), reason=reason)

    if kind == 'genre':
        name = seed
        add(api.call('getSongsByGenre', genre=seed, count=500).get('songsByGenre', {}).get('song', []),
            'Same genre in local library')
    else:
        if kind == 'song':
            if seed not in allowed:
                raise ValueError('Seed song has no verified local file')
            song = api.call('getSong', id=seed)['song']
            name = song.get('artist', '') + ' — ' + song['title']
            artist_id = song.get('artistId')
            add([song], 'Seed song')
        else:
            artist_id = seed
        if artist_id:
            artist = api.call('getArtist', id=artist_id)['artist']
            if kind == 'artist':
                name = artist['name']
            try:
                add(api.call('getSimilarSongs2', id=artist_id, count=100)
                    .get('similarSongs2', {}).get('song', []), 'Navidrome similar artists')
            except SubsonicError:
                warnings.append('Similarity API unavailable; using local artist tracks')
            # Bounded fallback even when no external similarity provider is configured.
            for album in artist.get('album', [])[:10]:
                songs = api.call('getAlbum', id=album['id'])['album'].get('song', [])
                add([s for s in songs if s.get('artistId') == artist_id], 'Same artist in local library')
    # Stable ordering within a week for a given result set; no fake similarity scores.
    ordered = sorted(candidates.values(), key=lambda s: (
        0 if kind == 'song' and s['id'] == seed else 1,
        0 if s['reason'] == 'Navidrome similar artists' else 1,
        hashlib.sha256((source + week + s['id']).encode()).hexdigest()))[:limit]
    return dict(source=source, name='Radio — ' + name, week=week, tracks=ordered,
                warnings=warnings, status='ready' if ordered else 'empty', acquisition_enabled=False)


def run(config_path, kind, seed, *, apply=False, limit=25):
    config_path = config_path.resolve()
    cfg, root = load_document(config_path), config_path.parent
    nav = cfg['navidrome']
    if not nav.get('enabled'):
        raise ValueError('Navidrome is disabled')
    if not nav.get('catalog_db'):
        raise ValueError('Physical catalog required to verify local radio tracks')
    state = (root / cfg['state_db']).resolve()
    music = (root / nav['music_root']).resolve()
    catalog = (root / nav['catalog_db']).resolve()
    if state == catalog or state == music or music in state.parents:
        raise ValueError('Radio state must be separate from library and Navidrome database')
    with history.import_lock(state, read_only=not apply), closing(watch_state.connect(state, readonly=not apply)) as db:
        api = Subsonic(nav['url'], **credentials(root / nav['credentials_file']),
                       catalog_db=catalog, library_id=int(nav.get('library_id', 1)))
        allowed = set(api.catalog(music).values())
        report = select(api, allowed, kind, seed, limit=limit)
        report['simulation'] = not apply
        if apply and report['tracks']:
            report['mirror'] = mirror(api, db, report['source'], report['name'],
                                      [s['id'] for s in report['tracks']])
        # Empty/error results do not erase an existing radio or create an empty one.
        if apply:
            with db:
                db.execute('INSERT INTO radio_runs(report) VALUES (?)', (json.dumps(report),))
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('watch.toml'))
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--artist-id')
    group.add_argument('--song-id')
    group.add_argument('--genre')
    parser.add_argument('--limit', type=int, default=25)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    kind, seed = next((kind, value) for kind, value in
                      [('artist', args.artist_id), ('song', args.song_id), ('genre', args.genre)] if value is not None)
    try:
        print(json.dumps(run(args.config, kind, seed, apply=args.apply, limit=args.limit),
                         indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        parser.exit(2, 'Radio failed: ' + type(exc).__name__ + '\n')
