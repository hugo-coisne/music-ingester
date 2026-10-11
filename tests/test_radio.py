import json
from unittest.mock import patch

from music_ingest import radio, watch_state
from music_ingest.subsonic import SubsonicError
from tests.support import TemporaryTest
from tests.test_watch import FakeAPI


class RadioAPI(FakeAPI):
    def __init__(self):
        super().__init__()
        self.similarity_down = False
        self.songs = [dict(id='one', title='One', artist='Artist', artistId='artist'),
                      dict(id='two', title='Two', artist='Artist', artistId='artist'),
                      dict(id='missing', title='Missing', artist='Other', artistId='other')]

    def call(self, endpoint, **params):
        if endpoint == 'getSongsByGenre':
            return dict(songsByGenre=dict(song=self.songs + self.songs))
        if endpoint == 'getSimilarSongs2':
            if self.similarity_down:
                raise SubsonicError('Provider unavailable')
            return dict(similarSongs2=dict(song=self.songs))
        if endpoint == 'getArtist':
            return dict(artist=dict(name='Artist', album=[{'id': 'album'}]))
        if endpoint == 'getAlbum':
            return dict(album=dict(song=self.songs))
        if endpoint == 'getSong':
            return dict(song=next(s for s in self.songs if s['id'] == params['id']))
        return super().call(endpoint, **params)


class RadioTests(TemporaryTest):
    def setUp(self):
        super().setUp()
        self.api = RadioAPI()

    def test_genre_excludes_unavailable_deduplicates_and_is_stable(self):
        first = radio.select(self.api, {'one', 'two'}, 'genre', 'Electronic', week='2026-W40')
        second = radio.select(self.api, {'one', 'two'}, 'genre', 'Electronic', week='2026-W40')
        self.assertEqual(first, second)
        self.assertEqual({s['id'] for s in first['tracks']}, {'one', 'two'})
        self.assertFalse(first['acquisition_enabled'])

    def test_song_uses_artist_similarity_and_keeps_seed_first(self):
        result = radio.select(self.api, {'one', 'two'}, 'song', 'one')
        self.assertEqual(result['tracks'][0]['id'], 'one')
        self.assertEqual(result['tracks'][0]['reason'], 'Seed song')
        self.assertEqual(result['tracks'][1]['reason'], 'Navidrome similar artists')

    def test_similarity_failure_falls_back_to_same_artist(self):
        self.api.similarity_down = True
        result = radio.select(self.api, {'one', 'two', 'missing'}, 'artist', 'artist')
        self.assertTrue(result['warnings'])
        self.assertEqual({s['id'] for s in result['tracks']}, {'one', 'two'})
        self.assertTrue(all(s['reason'] == 'Same artist in local library' for s in result['tracks']))

    def test_missing_seed_and_invalid_limits_refused(self):
        with self.assertRaises(ValueError):
            radio.select(self.api, {'one'}, 'song', 'missing')
        for limit in (0, 101):
            with self.assertRaises(ValueError):
                radio.select(self.api, {'one'}, 'genre', 'Electronic', limit=limit)

    def configure(self):
        path = self.root / 'radio.toml'
        path.write_text('state_db="state/watch.db"\n[navidrome]\nenabled=true\n'
                        'url="http://127.0.0.1:15435"\ncredentials_file="creds.json"\n'
                        'catalog_db="data/navidrome.db"\nmusic_root="music"\n')
        creds = self.root / 'creds.json'
        creds.write_text(json.dumps(dict(username='tester', password='not-a-real-secret')))
        creds.chmod(0o600)
        self.api.files = {self.root / 'music/tone.m4a': 'one'}
        return path

    def test_dry_run_no_state_apply_public_idempotent_and_empty_preserves_mirror(self):
        cfg = self.configure()
        with patch.object(radio, 'Subsonic', return_value=self.api):
            preview = radio.run(cfg, 'genre', 'Electronic')
            self.assertFalse((self.root / 'state').exists())
            self.assertEqual(self.api.mutations, 0)
            first = radio.run(cfg, 'genre', 'Electronic', apply=True)
            second = radio.run(cfg, 'genre', 'Electronic', apply=True)
            self.assertFalse(second['mirror']['changed'])
            key = first['mirror']['id']
            self.assertIs(self.api.playlists[key]['public'], True)
            self.api.files = {}
            empty = radio.run(cfg, 'genre', 'Electronic', apply=True)
            self.assertEqual(empty['status'], 'empty')
            self.assertNotIn('mirror', empty)
            self.assertEqual(self.api.playlists[key]['entry'], [{'id': 'one'}])
        self.assertEqual(self.api.playlists['personal']['entry'], [{'id': 'personal-song'}])
        with watch_state.connect(self.root / 'state/watch.db') as db:
            self.assertEqual(db.execute('select count(*) from radio_runs').fetchone()[0], 3)
        db.close()

    def test_radio_refuses_state_inside_music_before_api(self):
        cfg = self.configure()
        cfg.write_text(cfg.read_text().replace('state/watch.db', 'music/watch.db'))
        with patch.object(radio, 'Subsonic') as api:
            with self.assertRaises(ValueError):
                radio.run(cfg, 'genre', 'Electronic', apply=True)
            api.assert_not_called()

    def test_cli_help_is_offline(self):
        with self.assertRaises(SystemExit) as error:
            radio.main(['--help'])
        self.assertEqual(error.exception.code, 0)
