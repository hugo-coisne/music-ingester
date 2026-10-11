"""Periodic playlist mirrors and recommendation acquisition. Simulation by default."""
import argparse
from collections import Counter
from contextlib import closing, redirect_stdout
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import time
import uuid

import requests
from ytmusicapi import YTMusic

from . import history, library, pipeline, watch_state
from .config import build_config, load_document
from .discovery.cli import lastfm_key
from .discovery.cache import CachedTransport
from .discovery.core import collect
from .discovery.providers import LastFM, ListenBrainz
from .subsonic import Subsonic, credentials, mirror


def playlist_ids(path):
    ids = []
    for line in path.read_text().splitlines():
        value = line.split('#', 1)[0].strip()
        if not value:
            continue
        if not re.fullmatch(r'[A-Za-z0-9_-]{10,150}', value):
            raise ValueError('Expected one YouTube Music playlist ID per line')
        if value not in ids:
            ids.append(value)
    return ids


def edit_ids(path, value, remove=False):
    if not re.fullmatch(r'[A-Za-z0-9_-]{10,150}', value):
        raise ValueError('Invalid playlist ID')
    with history.import_lock(path):
        ids = playlist_ids(path) if path.exists() else []
        if remove:
            ids = [x for x in ids if x != value]
        elif value not in ids:
            ids.append(value)
        temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        with temporary.open('x') as out:
            out.write('# YouTube Music playlist IDs; one per line\n' + '\n'.join(ids) + '\n')
            out.flush()
            os.fsync(out.fileno())
        temporary.replace(path)


class Session(requests.Session):
    def request(self, *args, **kwargs):
        kwargs.setdefault('timeout', (5, 30))
        return super().request(*args, **kwargs)


class Snapshot:
    def __init__(self, client, name, tracks):
        self.client, self.name, self.tracks = client, name, tracks

    def get_playlist(self, *args, **kwargs):
        return dict(title=self.name, tracks=self.tracks)

    def get_album(self, album_id):
        return self.client.get_album(album_id)


def resolve_song(client, candidate):
    """Only exact song/artist matches; reject alternative versions and ambiguity."""
    results = client.search(candidate['artist'] + ' ' + candidate['title'], filter='songs', limit=20)
    matches = {}
    for result in results:
        if library.normalize_text(result.get('title')) != library.normalize_text(candidate['title']):
            continue
        artists = {library.normalize_text(a.get('name')) for a in result.get('artists', [])}
        if library.normalize_text(candidate['artist']) not in artists:
            continue
        if not result.get('videoId') or not result.get('duration_seconds'):
            continue
        if candidate.get('duration') and abs(float(candidate['duration']) - float(result['duration_seconds'])) > 4:
            continue
        if candidate.get('album') and library.normalize_text(candidate['album']) != library.normalize_text(
            (result.get('album') or {}).get('name')
        ):
            continue
        matches[result['videoId']] = result
    # Never copy an unverified MBID from a recommendation to a YouTube recording.
    return next(iter(matches.values())) if len(matches) == 1 else None


def queue_key(track):
    return track.get('_key') or 'youtube:' + str(track.get('videoId'))


def local_path(track, index, imports):
    video_id = track.get('videoId')
    if video_id:
        row = imports.execute('SELECT status,local_path FROM imports WHERE video_id=?', (video_id,)).fetchone()
        if row and row[0] in ('done', 'existing') and row[1] and Path(row[1]).is_file():
            return Path(row[1]).resolve()
    match = library.find_existing_track(track, index)
    return match['path'].resolve() if match else None


def recommendation_jobs(config, root, db, index, now, force=False):
    jobs, errors = [], []
    transport = CachedTransport(db, force=force, clock=lambda: now,
                                **config.get('recommendation_cache', {}))
    for name, provider_type in (('lastfm', LastFM), ('listenbrainz', ListenBrainz)):
        settings = config.get(name, {})
        if not settings.get('enabled', False):
            continue
        source = name + ':' + settings['username']
        previous = db.execute('SELECT payload,updated FROM jobs WHERE source=?', (source,)).fetchone()
        if previous and not force and now - previous[1] < 7 * 86400:
            cached = json.loads(previous[0])
            jobs.extend(cached)
            if not cached:
                errors.append(dict(provider=name, error='NoRecommendations'))
            continue
        provider = (provider_type(settings['username'], lastfm_key(settings, root), transport=transport)
                    if name == 'lastfm' else provider_type(settings['username'], transport=transport))
        rank = config.get('ranking', {})
        report = collect([provider], index, limit=50 if name == 'listenbrainz' else 25,
                         blocked_artists=rank.get('blocked_artists', []),
                         blocked_tracks=rank.get('blocked_tracks', []), weights=rank.get('weights'))
        errors.extend(report['errors'])
        if report['errors']:
            if previous:
                jobs.extend(json.loads(previous[0]))
            continue  # Do not replace a good weekly snapshot with a partial response.
        groups = {'Discover Weekly — Last.fm': []} if name == 'lastfm' else {
            'Weekly Exploration — ListenBrainz': [], 'Weekly Jams — ListenBrainz': []}
        for candidate in report['candidates']:
            if candidate['status'] == 'ambiguous':
                errors.append(dict(provider=name, error='AmbiguousRecommendation'))
                continue
            for title in groups:
                if name == 'listenbrainz' and not any(title.split(' — ')[0].casefold() in p['reason']
                                                     for p in candidate['provenance']):
                    continue
                groups[title].append(dict(title=candidate['title'], artists=[{'name': candidate['artist']}],
                    duration_seconds=candidate['duration'], recording_mbid=candidate['recording_mbid'],
                    isrc=candidate['isrc'], _candidate=candidate, _key=candidate['key']))
        fresh = [dict(source=source + ':' + title, name=title, tracks=tracks[:25])
                 for title, tracks in groups.items() if tracks]
        # Empty provider: keep mirrors intact, report empty, no fabricated seeds.
        if not fresh:
            errors.append(dict(provider=name, error='NoRecommendations'))
            with db:
                db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?,?)', (source, '[]', now))
            continue
        with db:
            db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?,?)', (source, json.dumps(fresh), now))
        jobs.extend(fresh)
    return jobs, errors


def cycle(config, root, ingest, db, client, api, *, apply=False, force=False, now=None):
    now = time.time() if now is None else now
    limits = config.get('limits', {})
    maximum = int(limits.get('acquisitions', 10))
    max_bytes = int(limits.get('file_bytes', 100 * 1024 * 1024))
    min_free = int(limits.get('free_bytes', 2 * 1024 ** 3))
    if not 0 <= maximum <= 100 or max_bytes <= 0 or min_free < 0:
        raise ValueError('Invalid acquisition limits')
    enabled = apply and config.get('acquisition_enabled', False)
    roots = tuple(dict.fromkeys((*ingest.reference_libraries, ingest.library_dir)))
    if apply:
        ingest.library_dir.mkdir(parents=True, exist_ok=True)
        ingest.staging_dir.mkdir(parents=True, exist_ok=True)
        with history.import_lock(ingest.db_path), closing(history.connect_db(ingest.db_path)) as imports:
            history.recover_published(imports, ingest.library_dir)
    # Absent managed directory in dry-run is normal; absent reference mount is not.
    index = watch_state.cached_index(db, [p for p in roots if p != ingest.library_dir or p.exists()])
    report = dict(generated_at=datetime.fromtimestamp(now, timezone.utc).isoformat(),
                  simulation=not apply, acquisition_enabled=enabled, playlists=[], errors=[], warnings=[], attempts=0)
    jobs = []
    for playlist_id in playlist_ids(root / config['playlist_ids']):
        try:
            snapshot = client.get_playlist(playlist_id, limit=None)
            if not snapshot.get('title') or not isinstance(snapshot.get('tracks'), list):
                raise ValueError('Invalid playlist response')
            tracks = snapshot['tracks']
            count = snapshot.get('trackCount')
            if isinstance(count, int) and count > len(tracks):
                raise ValueError('Incomplete playlist response')
            jobs.append(dict(source='youtube:' + playlist_id, name=snapshot['title'], tracks=tracks))
        except Exception as exc:
            report['errors'].append(dict(source='youtube:' + playlist_id, error=type(exc).__name__))
    recommended, errors = recommendation_jobs(config, root, db, index, now, force)
    jobs.extend(recommended)
    report['warnings'].extend(e for e in errors if e.get('error') == 'NoRecommendations')
    report['errors'].extend(e for e in errors if e.get('error') != 'NoRecommendations')
    per_job = max(1, math.ceil(maximum / max(1, len(jobs))))
    if jobs:
        # Share the acquisition budget and rotate precedence so a large playlist
        # cannot indefinitely starve recommendations or a newly added source.
        offset = db.execute('SELECT count(*) FROM runs').fetchone()[0] % len(jobs)
        jobs = jobs[offset:] + jobs[:offset]
    if api:
        api.call('ping')  # Authentication must succeed before downloads/mutations.
    attempted = set()
    with closing(history.connect_db(ingest.db_path, read_only=not apply)) as imports:
        for job in jobs:
            output = dict(source=job['source'], name=job['name'], tracks=[], errors=[])
            report['playlists'].append(output)
            selected = []
            for raw in job['tracks']:
                track = dict(raw)
                key = queue_key(track)
                record = dict(title=track.get('title'), key=key, status='unavailable', path=None)
                output['tracks'].append(record)
                if track.get('isAvailable') is False:
                    record['status'] = 'source_unavailable'
                    continue
                found = local_path(track, index, imports)
                if found:
                    record.update(path=str(found), status='local')
                    continue
                queued = db.execute('SELECT track,attempts,next_at FROM queue WHERE key=?', (key,)).fetchone()
                if queued and queued[0]:
                    track = dict(json.loads(queued[0]), _key=key)
                if queued and queued[2] > now:
                    record['status'] = 'backoff'
                    continue
                if '_candidate' in track and not track.get('videoId'):
                    try:
                        resolved = resolve_song(client, track['_candidate'])
                    except Exception:
                        resolved = None
                    if not resolved:
                        record['status'] = 'unresolved_or_ambiguous'
                        with db:
                            db.execute('INSERT OR REPLACE INTO queue VALUES (?,?,?, ?,?)',
                                       (key, None, (queued[1] if queued else 0) + 1, now + 86400, record['status']))
                        continue
                    track = dict(resolved, _key=key)
                    with db:
                        db.execute('INSERT OR REPLACE INTO queue VALUES (?,?,0,0,?)',
                                   (key, json.dumps(track), 'resolved'))
                if not track.get('videoId'):
                    record['status'] = 'source_unavailable'
                    continue
                found = local_path(track, index, imports)
                if found:
                    record.update(path=str(found), status='local')
                    continue
                record['video_id'] = track['videoId']
                if not enabled:
                    record['status'] = 'would_acquire' if not apply else 'acquisition_disabled'
                    continue
                if report['attempts'] >= maximum or len(selected) >= per_job:
                    record['status'] = 'queued_limit'
                    continue
                if track['videoId'] in attempted:
                    record['status'] = 'pending_same_cycle'
                    continue
                if min(shutil.disk_usage(ingest.library_dir).free, shutil.disk_usage(ingest.staging_dir).free) < min_free + (len(selected) + 1) * 2 * max_bytes:
                    record['status'] = 'insufficient_space'
                    continue
                attempted.add(track['videoId'])
                report['attempts'] += 1
                selected.append(track)
            if selected:
                pipeline.run_sync(Snapshot(client, job['name'], selected), job['source'], ingest,
                                  library_index=index, max_bytes=max_bytes)
            for record in output['tracks']:
                if not record.get('video_id'):
                    continue
                found = local_path({'videoId': record['video_id']}, index, imports)
                if found:
                    record.update(path=str(found), status='local')
                    with db:
                        db.execute('UPDATE queue SET status=?,attempts=0,next_at=0 WHERE key=?', ('local', record['key']))
                elif record['video_id'] in {t['videoId'] for t in selected}:
                    previous = db.execute('SELECT attempts,track FROM queue WHERE key=?', (record['key'],)).fetchone()
                    attempts = (previous[0] if previous else 0) + 1
                    record['status'] = 'download_failed'
                    with db:
                        db.execute('INSERT OR REPLACE INTO queue VALUES (?,?,?,?,?)',
                                   (record['key'], previous[1] if previous else None, attempts,
                                    now + min(86400, 900 * 2 ** min(attempts - 1, 7)), 'download_failed'))
    catalog = api.catalog(root / config['navidrome']['music_root']) if api else {}
    wait = float(config.get('navidrome', {}).get('index_wait_seconds', 0))
    if not 0 <= wait <= 60:
        raise ValueError('Index wait must be between zero and 60 seconds')
    pending = {Path(t['path']) for p in report['playlists'] for t in p['tracks'] if t['path']}
    # Let Navidrome's filesystem watcher index new audio; never force a full scan
    # of the legacy library (which contains historical missing paths).
    deadline = time.monotonic() + wait
    while apply and api and pending - catalog.keys() and time.monotonic() < deadline:
        time.sleep(min(5, max(0, deadline - time.monotonic())))
        catalog = api.catalog(root / config['navidrome']['music_root'])
    for output in report['playlists']:
        ids = []
        for record in output['tracks']:
            song_id = catalog.get(Path(record['path'])) if record['path'] else None
            if song_id:
                ids.append(song_id)
                record.update(status='playable', navidrome_id=song_id)
            elif record['path']:
                record['status'] = 'awaiting_index' if api else 'local_unverified'
        if apply and api:
            try:
                output['mirror'] = mirror(api, db, output['source'], output['name'], ids)
            except Exception as exc:
                output['errors'].append(type(exc).__name__)
        output['missing'] = sum(t['status'] != 'playable' for t in output['tracks'])
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run', 'status', 'add', 'remove', 'list'])
    parser.add_argument('playlist_id', nargs='?')
    parser.add_argument('--config', type=Path, default=Path('watch.toml'))
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--summary', action='store_true', help='Print counts instead of individual tracks')
    parser.add_argument('--refresh-recommendations', action='store_true')
    args = parser.parse_args(argv)
    try:
        if not args.config.is_file():
            raise ValueError('Copy watch.example.toml to watch.toml')
        config, root = load_document(args.config), args.config.resolve().parent
        ids_path = root / config['playlist_ids']
        if args.action in ('add', 'remove'):
            edit_ids(ids_path, args.playlist_id or '', args.action == 'remove')
            print(json.dumps(playlist_ids(ids_path)))
            return 0
        if args.action == 'list':
            print(json.dumps(playlist_ids(ids_path)))
            return 0
        path = (root / config['state_db']).resolve()
        ingest_path = (root / config['ingest_config']).resolve()
        ingest = build_config(document=load_document(ingest_path), profile=config.get('profile', 'sandbox'),
                              config_path=ingest_path, environment={})
        if path == ingest.db_path or any(p == path or p in path.parents for p in
                                       (*ingest.reference_libraries, ingest.library_dir, ingest.staging_dir)):
            raise ValueError('Watch state must be separate from music and import state')
        with history.import_lock(path, read_only=not args.apply), closing(watch_state.connect(path, readonly=not args.apply)) as db:
            if args.action == 'status':
                row = db.execute('SELECT report FROM runs ORDER BY id DESC LIMIT 1').fetchone()
                report = json.loads(row[0]) if row else {}
            else:
                settings = config.get('navidrome', {})
                api = Subsonic(settings['url'], **credentials(root / settings['credentials_file']),
                    catalog_db=root / settings['catalog_db'] if settings.get('catalog_db') else None,
                    library_id=int(settings.get('library_id', 1))) if settings.get('enabled') else None
                if args.apply and not api:
                    raise ValueError('Live synchronization requires Navidrome credentials')
                with redirect_stdout(sys.stderr):
                    report = cycle(config, root, ingest, db, YTMusic(requests_session=Session()), api,
                                   apply=args.apply, force=args.refresh_recommendations)
                if args.apply:
                    with db:
                        db.execute('INSERT INTO runs(report) VALUES (?)', (json.dumps(report),))
            if args.summary:
                report = dict(report, playlists=[dict(source=p['source'], name=p['name'],
                    counts=dict(Counter(t['status'] for t in p['tracks'])), mirror=p.get('mirror'),
                    missing=p['missing'], errors=p['errors']) for p in report.get('playlists', [])])
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return int(bool(report.get('errors') or any(p['errors'] or any(
                t['status'] == 'download_failed' for t in p.get('tracks', [])) or p.get('counts', {}).get('download_failed')
                for p in report.get('playlists', []))))
    except Exception as exc:
        parser.exit(2, 'Watch failed: ' + type(exc).__name__ + '\n')
