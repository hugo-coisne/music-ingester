"""Ownership, recovery, conservative acquisition and periodic cycle contracts."""
import json
from pathlib import Path
import sqlite3
from unittest.mock import Mock, patch

from music_ingest import history, library, watch, watch_state
from music_ingest.subsonic import Subsonic, SubsonicError, mirror
from tests.support import TemporaryTest, track


class FakeAPI:
    username = 'tester'

    def __init__(self):
        self.playlists = {'personal': dict(id='personal', name='Source', owner=self.username,
                                         entry=[{'id': 'personal-song'}])}
        self.mutations = 0
        self.fail_after_create = False
        self.files = {}

    def catalog(self, root):
        return self.files

    def call(self, endpoint, **params):
        if endpoint == 'ping':
            return {}
        if endpoint == 'getPlaylists':
            return {'playlists': {'playlist': list(self.playlists.values())}}
        if endpoint == 'getPlaylist':
            return {'playlist': self.playlists[params['id']].copy()}
        if endpoint == 'createPlaylist':
            self.mutations += 1
            key = params.get('playlistId', str(len(self.playlists)))
            if key not in self.playlists:
                self.playlists[key] = dict(id=key, name=params['name'], owner=self.username)
            if params.get('songId') or 'entry' not in self.playlists[key]:
                self.playlists[key]['entry'] = [{'id': x} for x in params.get('songId', [])]
            if self.fail_after_create:
                self.fail_after_create = False
                raise SubsonicError('Connection lost after remote commit')
            return {'playlist': self.playlists[key].copy()}
        if endpoint == 'updatePlaylist':
            self.mutations += 1
            playlist = self.playlists[params['playlistId']]
            if 'songIndexToRemove' in params:
                playlist['entry'] = [x for i, x in enumerate(playlist['entry']) if i not in params['songIndexToRemove']]
            self.playlists[params['playlistId']].update({k: v for k, v in params.items() if k != 'playlistId'})
            if 'public' in params:
                playlist['public'] = params['public'] == 'true'
            return {}
        raise AssertionError(endpoint)


class WatchTests(TemporaryTest):
    def setUp(self):
        super().setUp()
        self.db = watch_state.connect(self.root / 'watch.db')
        self.addCleanup(self.db.close)
        self.api = FakeAPI()

    def test_mirror_order_rename_empty_and_idempotence_preserves_personal(self):
        result = mirror(self.api, self.db, 'youtube:source', 'Source', ['b', 'a', 'b'])
        key = result['id']
        self.assertEqual(self.api.playlists[key]['entry'], [{'id': 'b'}, {'id': 'a'}])
        self.assertIs(self.api.playlists[key]['public'], True)
        mutations = self.api.mutations
        self.assertFalse(mirror(self.api, self.db, 'youtube:source', 'Source', ['b', 'a'])['changed'])
        self.assertEqual(mutations, self.api.mutations)
        mirror(self.api, self.db, 'youtube:source', 'Renamed', [])
        self.assertEqual(self.api.playlists[key]['entry'], [])
        self.assertEqual(self.api.playlists[key]['name'], 'Renamed')
        self.assertEqual(self.api.playlists['personal']['entry'], [{'id': 'personal-song'}])
        self.assertGreater(self.db.execute('SELECT count(*) FROM playlist_backups').fetchone()[0], 0)

    def test_private_mirror_becomes_public_without_changing_tracks(self):
        key = mirror(self.api, self.db, 'source', 'Source', ['a'])['id']
        self.api.playlists[key]['public'] = False
        personal = self.api.playlists['personal'].copy()
        self.assertTrue(mirror(self.api, self.db, 'source', 'Source', ['a'])['changed'])
        self.assertIs(self.api.playlists[key]['public'], True)
        self.assertEqual(self.api.playlists[key]['entry'], [{'id': 'a'}])
        self.assertEqual(self.api.playlists['personal'], personal)
        self.assertFalse(mirror(self.api, self.db, 'source', 'Source', ['a'])['changed'])

    def test_visibility_rejected_by_server_fails_verification(self):
        call = self.api.call
        def ignore_visibility(endpoint, **params):
            params.pop('public', None)
            return call(endpoint, **params)
        self.api.call = ignore_visibility
        with self.assertRaisesRegex(SubsonicError, 'verification failed'):
            mirror(self.api, self.db, 'source', 'Source', ['a'])

    def test_recovery_after_remote_create_before_local_commit(self):
        self.api.fail_after_create = True
        with self.assertRaises(SubsonicError):
            mirror(self.api, self.db, 'source', 'Source', ['a'])
        result = mirror(self.api, self.db, 'source', 'Source', ['a'])
        self.assertEqual(len(self.api.playlists), 2)
        self.assertEqual(result['playable'], 1)

    def test_ownership_change_refuses_modification(self):
        key = mirror(self.api, self.db, 'source', 'Source', ['a'])['id']
        self.api.playlists[key]['comment'] = 'adopted by human'
        with self.assertRaises(SubsonicError):
            mirror(self.api, self.db, 'source', 'Source', [])
        self.assertEqual(self.api.playlists[key]['entry'], [{'id': 'a'}])

    def test_refuse_foreign_database(self):
        path = self.root / 'other.db'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE precious(data)')
        with self.assertRaises(ValueError):
            watch_state.connect(path)
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [('precious',)])

    def test_list_management_and_lock(self):
        path = self.root / 'ids.txt'
        watch.edit_ids(path, 'PL123456789012')
        watch.edit_ids(path, 'PL123456789012')
        self.assertEqual(watch.playlist_ids(path), ['PL123456789012'])
        with history.import_lock(path), self.assertRaises(RuntimeError):
            watch.edit_ids(path, 'PLdifferent123')
        watch.edit_ids(path, 'PL123456789012', remove=True)
        self.assertEqual(watch.playlist_ids(path), [])

    def test_resolver_refuses_versions_artists_and_ambiguity(self):
        client = Mock()
        candidate = dict(artist='Air', title='Song', duration=180)
        client.search.return_value = [track('one', 'Song (Live)', duration=180),
                                     track('two', artist='Air Supply', duration=180)]
        self.assertIsNone(watch.resolve_song(client, candidate))
        client.search.return_value = [track('one', duration=180), track('two', duration=180)]
        self.assertIsNone(watch.resolve_song(client, candidate))
        client.search.return_value = [track('one', duration=180)]
        self.assertEqual(watch.resolve_song(client, candidate)['videoId'], 'one')

    def test_incremental_cache_rechecks_deleted_files(self):
        self.config.library_dir.mkdir()
        path = self.config.library_dir / 'song.m4a'
        path.touch()
        item = dict(path=path, title='Song', artists=['Air'], duration=1)
        with patch.object(library, 'index_audio_file', return_value=item) as read:
            watch_state.cached_index(self.db, [self.config.library_dir])
            watch_state.cached_index(self.db, [self.config.library_dir])
            self.assertEqual(read.call_count, 1)
            path.unlink()
            self.assertEqual(watch_state.cached_index(self.db, [self.config.library_dir]), {})

    def test_cycle_partial_success_retries_and_second_pass_no_duplicate(self):
        (self.root / 'ids.txt').write_text('PL1234567890\n')
        settings = dict(playlist_ids='ids.txt', acquisition_enabled=True,
                        limits=dict(acquisitions=2, free_bytes=0), navidrome=dict(music_root='library'))
        client = self.client([track('good'), track('bad', title='Other')])
        def publish(snapshot, source, config, **kwargs):
            with history.connect_db(config.db_path) as imports:
                for song in snapshot.tracks:
                    history.mark_pending(imports, song['videoId'], 'Air', song['title'])
                    if song['videoId'] == 'bad':
                        history.mark_error(imports, 'bad', RuntimeError('unavailable'))
                    else:
                        path = config.library_dir / 'good.m4a'
                        path.touch()
                        history.mark_done(imports, 'good', path)
                        self.api.files[path] = 'real-id'
        with patch.object(watch.pipeline, 'run_sync', side_effect=publish) as ingest:
            first = watch.cycle(settings, self.root, self.config, self.db, client, self.api, apply=True, now=100)
            second = watch.cycle(settings, self.root, self.config, self.db, client, self.api, apply=True, now=101)
        self.assertEqual(ingest.call_count, 1)
        self.assertEqual(first['attempts'], 2)
        self.assertEqual(second['attempts'], 0)
        self.assertEqual(second['playlists'][0]['mirror']['playable'], 1)
        self.assertEqual(second['playlists'][0]['tracks'][1]['status'], 'backoff')
        self.assertFalse(second['playlists'][0]['mirror']['changed'])

    def test_source_failure_never_clears_mirror(self):
        (self.root / 'ids.txt').write_text('PL1234567890\n')
        client = Mock()
        client.get_playlist.side_effect = RuntimeError('provider failed')
        mirror(self.api, self.db, 'youtube:PL1234567890', 'Source', ['a'])
        mutations = self.api.mutations
        report = watch.cycle(dict(playlist_ids='ids.txt', navidrome=dict(music_root='library')),
                             self.root, self.config, self.db, client, self.api, apply=True)
        self.assertEqual(self.api.mutations, mutations)
        self.assertEqual(len(report['errors']), 1)

    def test_url_secrets_and_insecure_remote_refused(self):
        for url in ['http://192.168.1.111:4533', 'https://user:password@example.org', 'https://example.org?key=secret']:
            with self.assertRaises(ValueError):
                Subsonic(url, 'user', 'password')

    def test_credentials_not_in_url_or_exception(self):
        session = Mock()
        session.post.side_effect = __import__('requests').ConnectionError('password')
        api = Subsonic('http://127.0.0.1:4533', 'user', 'password', session=session)
        with self.assertRaises(SubsonicError) as exc:
            api.call('ping')
        self.assertNotIn('password', str(exc.exception))
        args, kwargs = session.post.call_args
        self.assertEqual(args[0], 'http://127.0.0.1:4533/rest/ping')
        self.assertNotIn('password', json.dumps(kwargs))

    def test_virtual_api_paths_use_readonly_wal_catalog_and_only_visible_existing_files(self):
        path = self.root / 'navidrome.db'
        with sqlite3.connect(path) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('CREATE TABLE media_file(id,path,library_id)')
            writer.executemany('INSERT INTO media_file VALUES (?,?,1)',
                              [('visible', 'real.m4a'), ('missing', 'gone.m4a'), ('hidden', 'hidden.m4a')])
            writer.commit()
            (self.root / 'real.m4a').touch()
            (self.root / 'hidden.m4a').touch()
            api = Subsonic('http://127.0.0.1:4533', 'u', 'p', catalog_db=path)
            api.call = Mock(return_value={'searchResult3': {'song': [
                {'id': 'visible', 'path': 'virtual/title.m4a'}, {'id': 'missing', 'path': 'real.m4a'}]}})
            self.assertEqual(api.catalog(self.root), {self.root / 'real.m4a': 'visible'})
            self.assertEqual(writer.execute('SELECT count(*) FROM media_file').fetchone()[0], 3)

    def test_weekly_cache_and_empty_provider_do_not_invent_tracks(self):
        from music_ingest.discovery.core import Candidate
        provider = Mock(name='provider')
        provider.name = 'lastfm'
        provider.candidates.return_value = [Candidate('lastfm', 'Air', 'Song', .8, 'real fixture')]
        settings = {'lastfm': {'enabled': True, 'username': 'user'}}
        with patch.object(watch, 'LastFM', return_value=provider):
            first, errors = watch.recommendation_jobs(settings, self.root, self.db, {}, 100)
            second, errors = watch.recommendation_jobs(settings, self.root, self.db, {}, 101)
        self.assertEqual(first, second)
        self.assertEqual(provider.candidates.call_count, 1)
        self.assertEqual(first[0]['name'], 'Discover Weekly — Last.fm')
        self.assertIsNone(first[0]['tracks'][0].get('videoId'))
        provider.candidates.return_value = []
        with patch.object(watch, 'LastFM', return_value=provider):
            empty, errors = watch.recommendation_jobs(settings, self.root, self.db, {}, 102, force=True)
        self.assertEqual(empty, [])
        self.assertEqual(errors, [{'provider': 'lastfm', 'error': 'NoRecommendations'}])

    def test_budget_is_shared_across_sources(self):
        (self.root / 'ids.txt').write_text('PL1234567890\nPL1234567891\n')
        client = self.client([])
        client.get_playlist.side_effect = [
            dict(title='One', tracks=[track('one'), track('two')]),
            dict(title='Two', tracks=[track('three'), track('four')])]
        settings = dict(playlist_ids='ids.txt', acquisition_enabled=True,
                        limits=dict(acquisitions=2, free_bytes=0), navidrome=dict(music_root='library'))
        with patch.object(watch.pipeline, 'run_sync') as run:
            report = watch.cycle(settings, self.root, self.config, self.db, client, self.api, apply=True)
        self.assertEqual(report['attempts'], 2)
        self.assertEqual([c.args[0].tracks[0]['videoId'] for c in run.call_args_list], ['one', 'three'])
