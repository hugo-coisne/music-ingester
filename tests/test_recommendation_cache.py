from unittest.mock import Mock, patch

from music_ingest import watch, watch_state
from music_ingest.discovery import cache
from music_ingest.discovery.core import ProviderError
from tests.support import TemporaryTest


class RecommendationCacheTests(TemporaryTest):
    def setUp(self):
        super().setUp()
        self.path = self.root / 'watch.db'
        self.db = watch_state.connect(self.path)
        self.addCleanup(self.db.close)
        self.upstream = Mock()
        self.upstream.json.return_value = {'toptracks': {'track': []}}
        self.now = 100

    def transport(self, **kwargs):
        return cache.CachedTransport(self.db, self.upstream, clock=lambda: self.now, **kwargs)

    def fetch(self, transport, user='one', key='SECRET_API_KEY'):
        return transport.json('POST', 'https://ws.audioscrobbler.com/2.0/',
                              data={'method': 'user.getTopTracks', 'user': user, 'api_key': key})

    def test_hits_expiry_force_and_credential_isolation(self):
        transport = self.transport(ttl_seconds=10)
        self.assertEqual(self.fetch(transport), self.fetch(transport))
        self.assertEqual(self.upstream.json.call_count, 1)
        self.fetch(transport, user='two')
        self.fetch(transport, key='ROTATED_KEY')
        self.assertEqual(self.upstream.json.call_count, 3)
        self.now = 110
        self.fetch(transport)
        self.assertEqual(self.upstream.json.call_count, 4)
        self.fetch(self.transport(force=True))
        self.assertEqual(self.upstream.json.call_count, 5)
        dump = '\n'.join(self.db.iterdump())
        self.assertNotIn('SECRET_API_KEY', dump)
        self.assertNotIn('ROTATED_KEY', dump)
        self.assertNotIn('audioscrobbler.com', dump)

    def test_failure_is_not_cached_or_hidden_by_expired_value(self):
        transport = self.transport(ttl_seconds=10)
        self.fetch(transport)
        self.now = 110
        self.upstream.json.side_effect = ProviderError('Provider unavailable')
        with self.assertRaises(ProviderError):
            self.fetch(transport)
        self.upstream.json.side_effect = None
        self.upstream.json.return_value = {'error': 9}
        self.fetch(transport)
        self.fetch(transport)
        self.assertEqual(self.upstream.json.call_count, 4)

    def test_unknown_methods_malformed_and_secret_echo_are_never_stored(self):
        transport = self.transport()
        for result in ({}, {'toptracks': {'echo': 'SECRET_API_KEY'}}):
            self.upstream.json.return_value = result
            self.fetch(transport)
        transport.json('POST', 'https://ws.audioscrobbler.com/2.0/',
                       data={'method': 'track.scrobble'})
        self.assertEqual(self.db.execute('SELECT count(*) FROM recommendation_http_cache').fetchone()[0], 0)

    def test_limits_and_corrupt_entry_recovery(self):
        transport = self.transport(max_entries=2, max_bytes=1024)
        self.upstream.json.return_value = {'toptracks': {'track': ['x' * 600]}}
        self.fetch(transport, user='one')
        self.now += 1
        self.fetch(transport, user='two')
        self.assertEqual(self.db.execute('SELECT count(*) FROM recommendation_http_cache').fetchone()[0], 1)
        self.db.execute("UPDATE recommendation_http_cache SET payload='broken'")
        self.db.commit()
        self.fetch(transport, user='two')
        self.assertEqual(self.upstream.json.call_count, 3)
        self.upstream.json.return_value = {'toptracks': {'track': []}}
        for user in ('three', 'four', 'five'):
            self.now += 1
            self.fetch(transport, user=user)
        count, size = self.db.execute('SELECT count(*),sum(bytes) FROM recommendation_http_cache').fetchone()
        self.assertEqual(count, 2)
        self.assertLessEqual(size, 1024)
        self.upstream.json.return_value = {'toptracks': {'track': ['x' * 2000]}}
        self.fetch(transport, user='oversized')
        self.assertEqual(self.db.execute('SELECT count(*) FROM recommendation_http_cache').fetchone()[0], 2)

    def test_dry_run_uses_memory_and_existing_database_is_unchanged(self):
        self.fetch(self.transport())
        original = self.path.read_bytes()
        with watch_state.connect(self.path, readonly=True) as memory:
            transport = cache.CachedTransport(memory, self.upstream, clock=lambda: self.now)
            self.fetch(transport)
            self.fetch(transport, user='two')
        memory.close()
        self.assertEqual(self.path.read_bytes(), original)
        absent = self.root / 'absent/watch.db'
        memory = watch_state.connect(absent, readonly=True)
        try:
            self.fetch(cache.CachedTransport(memory, self.upstream))
        finally:
            memory.close()
        self.assertFalse(absent.parent.exists())

    def test_partial_provider_failure_resumes_using_successful_reads(self):
        key = self.root / 'key'
        key.write_text('SECRET_API_KEY')
        key.chmod(0o600)
        config = {'lastfm': {'enabled': True, 'username': 'one', 'api_key_file': 'key'}}
        self.upstream.json.side_effect = [
            {'toptracks': {'track': [{'artist': {'name': 'Seed'}, 'name': 'Favorite'}]}},
            {'lovedtracks': {'track': []}},
            ProviderError('Provider unavailable'),
            {'similartracks': {'track': [{'artist': {'name': 'Air'}, 'name': 'Song', 'match': '0.8'}]}},
        ]
        with patch.object(cache, 'Transport', return_value=self.upstream):
            with patch.dict('os.environ', {}, clear=True):
                jobs, errors = watch.recommendation_jobs(config, self.root, self.db, {}, 100)
                self.assertEqual(jobs, [])
                self.assertTrue(errors)
                jobs, errors = watch.recommendation_jobs(config, self.root, self.db, {}, 101)
        self.assertEqual(errors, [])
        self.assertEqual(jobs[0]['tracks'][0]['title'], 'Song')
        self.assertEqual(self.upstream.json.call_count, 4)

    def test_listenbrainz_empty_results_are_cached_but_204_is_not(self):
        transport = self.transport()
        url = 'https://api.listenbrainz.org/1/user/Someone/playlists/createdfor'
        self.upstream.json.return_value = {'playlists': []}
        for _ in range(2):
            self.assertEqual(transport.json('GET', url), {'playlists': []})
        self.assertEqual(self.upstream.json.call_count, 1)
        self.upstream.json.return_value = {}
        for _ in range(2):
            transport.json('GET', url.replace('Someone', 'Other'))
        self.assertEqual(self.upstream.json.call_count, 3)

    def test_invalid_limits_rejected_and_disabled_cache_does_not_write(self):
        for settings in ({'ttl_seconds': -1}, {'ttl_seconds': True}, {'max_bytes': 0}, {'max_entries': 0}):
            with self.assertRaises(ValueError):
                self.transport(**settings)
        transport = self.transport(ttl_seconds=0)
        self.fetch(transport)
        self.fetch(transport)
        self.assertEqual(self.upstream.json.call_count, 2)
        self.assertEqual(self.db.execute('SELECT count(*) FROM recommendation_http_cache').fetchone()[0], 0)
