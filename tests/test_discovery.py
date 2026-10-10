from dataclasses import replace
import io
import json
import sqlite3
from unittest.mock import Mock, MagicMock, patch

import requests

from music_ingest import library
from music_ingest.discovery import core, providers
from music_ingest.discovery.cli import main, lastfm_key
from tests.support import TemporaryTest

MBID = '526bd613-fddd-4bd6-9137-ab709ac74cab'
OTHER = 'a6081bc1-2a76-4984-b21f-38bc3dcca3a5'


class Static:
    def __init__(self, name, items, error=None):
        self.name, self.items, self.error = name, items, error

    def candidates(self):
        yield from self.items
        if self.error:
            raise self.error


class DiscoveryTests(TemporaryTest):
    def test_key_file_requires_private_permissions_and_is_never_a_url_parameter(self):
        path = self.root / 'key'
        path.write_text('private-key\n')
        path.chmod(0o644)
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(ValueError):
                lastfm_key({'api_key_file': 'key'}, self.root)
            path.chmod(0o600)
            self.assertEqual(lastfm_key({'api_key_file': 'key'}, self.root), 'private-key')
    def candidate(self, **kwargs):
        return replace(core.Candidate('one', 'Air', 'Song', 0.8, 'similar to a favorite'), **kwargs)

    def test_partial_failure_does_not_discard_other_results_or_leak_secret(self):
        report = core.collect([Static('one', [self.candidate()]),
                               Static('broken', [], RuntimeError('api_key=SECRET'))], {})
        self.assertEqual(len(report['candidates']), 1)
        self.assertEqual(report['candidates'][0]['status'], 'unavailable')
        self.assertNotIn('SECRET', json.dumps(report))
        self.assertEqual(report['providers']['broken'], 'failed')

    def test_duplicates_across_sources_are_ranked_once_and_explained(self):
        report = core.collect([Static('one', [self.candidate(), self.candidate()]),
                               Static('two', [self.candidate(provider='two', artist='AIR', score=0.6)])],
                              {}, weights={'one': 0.5, 'two': 1})
        self.assertEqual(len(report['candidates']), 1)
        self.assertEqual(report['candidates'][0]['score'], 1.0)
        self.assertEqual(report['candidates'][0]['score_terms'], {'one': 0.4, 'two': 0.6})

    def test_matching_requires_real_file_and_duration_or_strong_identity(self):
        item = self.item()
        index = {}
        library.add_to_library_index(index, item)
        candidate = self.candidate(duration=item['duration'])
        report = core.collect([Static('one', [candidate])], index)
        self.assertEqual(report['candidates'][0]['status'], 'available')
        path = self.root / 'discovery.db'
        core.save(path, report)
        item['path'].unlink()
        self.assertEqual(core.latest(path)['candidates'][0]['status'], 'unavailable')
        report = core.collect([Static('one', [self.candidate()])], index)
        self.assertEqual(report['candidates'][0]['status'], 'unavailable')

    def test_recording_versions_and_conflicting_duration_are_not_false_matches(self):
        candidates = [self.candidate(recording_mbid=MBID), self.candidate(recording_mbid=OTHER)]
        report = core.collect([Static('one', candidates)], {})
        self.assertEqual(len(report['candidates']), 2)
        report = core.collect([Static('one', [self.candidate(duration=100), self.candidate(duration=200)])], {})
        self.assertEqual(len(report['candidates']), 1)
        self.assertEqual(report['candidates'][0]['status'], 'ambiguous')
        self.assertIsNone(report['candidates'][0]['local_path'])

    def test_exclusions_and_empty_provider_do_not_invent_results(self):
        report = core.collect([Static('one', [self.candidate()]), Static('empty', [])], {},
                              blocked_artists=['AIR'])
        self.assertEqual(report['candidates'], [])
        self.assertEqual(report['providers']['empty'], 'empty')

    def test_cycle_lock_blocks_a_second_writer_before_provider_call(self):
        from music_ingest.history import import_lock
        config = self.root / 'discovery.toml'
        config.write_text('[storage]\ndb_path="discovery.db"\nlibraries=[]\n')
        with import_lock(self.root / 'discovery.db.cycle'):
            with patch('music_ingest.discovery.cli.collect') as call:
                with self.assertRaises(SystemExit) as error:
                    main(['--config', str(config), '--apply'])
                self.assertEqual(error.exception.code, 2)
                call.assert_not_called()

    def test_rerun_is_idempotent_and_foreign_database_is_untouched(self):
        path = self.root / 'state/discovery.db'
        report = core.collect([Static('one', [self.candidate()])], {})
        core.save(path, report)
        core.save(path, report)
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute('select count(*) from candidates').fetchone()[0], 1)
            self.assertEqual(db.execute('select count(*) from runs').fetchone()[0], 2)
        foreign = self.root / 'foreign.db'
        with sqlite3.connect(foreign) as db:
            db.execute('create table private(value)')
        before = foreign.read_bytes()
        with self.assertRaises(ValueError):
            core.save(foreign, report)
        self.assertEqual(before, foreign.read_bytes())

    def test_cli_default_is_read_only_and_missing_credentials_are_explicit(self):
        config = self.root / 'discovery.toml'
        config.write_text('[storage]\ndb_path="state/discovery.db"\nlibraries=[]\n'
                          '[lastfm]\nenabled=true\nusername="test"\n')
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(main(['--config', str(config)]), 1)
        self.assertFalse((self.root / 'state').exists())
        self.assertIn('ProviderError', self.output.getvalue())


class AdapterTests(TemporaryTest):
    def test_lastfm_falls_back_to_full_history_when_recent_chart_is_empty(self):
        transport = Mock()
        transport.json.side_effect = [
            {'toptracks': {'track': []}},
            {'lovedtracks': {'track': []}},
            {'toptracks': {'track': [{'artist': {'name': 'Seed'}, 'name': 'Old Favorite'}]}},
            {'similartracks': {'track': [{'artist': {'name': 'Air'}, 'name': 'Song', 'match': '0.8'}]}},
        ]
        result = list(providers.LastFM('user', 'secret', transport).candidates())
        self.assertEqual(len(result), 1)
        self.assertIn('period=overall', result[0].reason)
        self.assertEqual(transport.json.call_args_list[2].kwargs['data']['period'], 'overall')

    def test_lastfm_without_any_listening_history_does_not_invent_seeds(self):
        transport = Mock()
        transport.json.side_effect = [
            {'toptracks': {'track': []}}, {'lovedtracks': {'track': []}},
            {'toptracks': {'track': []}},
        ]
        self.assertEqual(list(providers.LastFM('user', 'secret', transport).candidates()), [])
        self.assertEqual(transport.json.call_count, 3)

    def test_lastfm_api_failure_does_not_trigger_history_fallback(self):
        transport = Mock()
        transport.json.return_value = {'error': 10, 'message': 'untrusted response SECRET'}
        report = core.collect([providers.LastFM('user', 'secret', transport)], {})
        self.assertEqual(report['providers']['lastfm'], 'failed')
        self.assertNotIn('SECRET', json.dumps(report))
        self.assertEqual(transport.json.call_count, 1)

    def test_lastfm_uses_user_seeds_and_post_body_credentials(self):
        transport = Mock()
        transport.json.side_effect = [
            {'toptracks': {'track': [{'artist': {'name': 'Seed'}, 'name': 'Favorite'}]}},
            {'lovedtracks': {'track': []}},
            {'similartracks': {'track': [{'artist': {'name': 'Air'}, 'name': 'Song',
                                          'mbid': MBID, 'match': '0.8'}]}},
        ]
        result = list(providers.LastFM('user', 'secret', transport).candidates())
        self.assertEqual(result[0].recording_mbid, MBID)
        self.assertEqual(transport.json.call_count, 3)  # no overall lookup when recent seeds exist
        self.assertIn('period=3month', result[0].reason)
        for call in transport.json.call_args_list:
            self.assertEqual(call.args[0], 'POST')
            self.assertNotIn('secret', call.args[1])
            self.assertEqual(call.kwargs['data']['api_key'], 'secret')

    def test_listenbrainz_uses_createdfor_weekly_playlists_and_milliseconds(self):
        transport = Mock()
        transport.json.side_effect = [
            {'playlists': [{'playlist': {'title': 'Weekly Exploration', 'date': '2026-10-05',
                                         'identifier': 'https://listenbrainz.org/playlist/' + MBID}}]},
            {'playlist': {'track': [{'creator': 'Air', 'title': 'Song', 'duration': 180000,
                                     'identifier': ['https://musicbrainz.org/recording/' + OTHER]}]}},
        ]
        result = list(providers.ListenBrainz('user', transport).candidates())
        self.assertEqual(result[0].duration, 180)
        self.assertEqual(result[0].recording_mbid, OTHER)
        self.assertEqual(len(result), 1)

    def test_no_weekly_results_are_empty_and_schema_errors_are_visible(self):
        transport = Mock()
        transport.json.return_value = {'playlists': []}
        self.assertEqual(list(providers.ListenBrainz('user', transport).candidates()), [])
        transport.json.return_value = {'unexpected': 'changed API'}
        # Last.fm required schema is explicit and collected as a provider error.
        report = core.collect([providers.LastFM('user', 'key', transport)], {})
        self.assertTrue(report['errors'])

    def test_transport_retry_is_bounded_and_does_not_leak_http_exception(self):
        session = Mock()
        session.request.side_effect = requests.Timeout('https://example/?token=SECRET')
        with self.assertRaises(providers.ProviderError) as caught:
            providers.Transport(session, sleep=lambda _: None).json('GET', 'https://example/')
        self.assertEqual(session.request.call_count, 3)
        self.assertNotIn('SECRET', str(caught.exception))
        self.assertEqual(session.request.call_args.kwargs['timeout'], (3, 15))
        self.assertFalse(session.request.call_args.kwargs['allow_redirects'])

    def test_transport_rejects_redirect_and_oversized_body(self):
        session = MagicMock()
        response = session.request.return_value.__enter__.return_value = Mock()
        response.status_code = 302
        with self.assertRaises(providers.ProviderError):
            providers.Transport(session, sleep=lambda _: None).json('POST', 'https://example/', data={'key': 'x'})
        self.assertEqual(session.request.call_count, 1)
        response.status_code = 200
        response.iter_content.return_value = [b'x' * (2 * 1024 * 1024 + 1)]
        with self.assertRaises(providers.ProviderError):
            providers.Transport(session, sleep=lambda _: None).json('GET', 'https://example/')
