import json
import sqlite3
from unittest.mock import Mock, patch

from music_ingest import backup, recovery
from tests.support import TemporaryTest


class PlatformRecoveryTests(TemporaryTest):
    def setUp(self):
        super().setUp()
        live = self.root / 'live'
        live.mkdir()
        self.music = self.root / 'music'
        self.music.mkdir()
        (self.music / 'track.m4a').write_bytes(b'synthetic fixture')
        db = sqlite3.connect(live / 'navidrome.db')
        db.executescript('''
            CREATE TABLE library(path); INSERT INTO library VALUES ('/music');
            CREATE TABLE media_file(id,path); INSERT INTO media_file VALUES ('track','track.m4a');
            CREATE TABLE user(id,user_name,password,is_admin); INSERT INTO user VALUES ('u','test','secret',1);
            CREATE TABLE user_props(user_id,key,value);
            CREATE TABLE annotation(id,play_count); INSERT INTO annotation VALUES ('track',7);
            CREATE TABLE playlist(id,name,comment,public,owner_id,rules);
            INSERT INTO playlist VALUES ('p','Personal','keep',0,'u',NULL);
            CREATE TABLE playlist_tracks(playlist_id,media_file_id); INSERT INTO playlist_tracks VALUES ('p','track');
            CREATE TABLE scrobbles(id,media_file_id); INSERT INTO scrobbles VALUES ('s','track');
            CREATE TABLE scrobble_buffer(id,service);
        ''')
        db.close()
        creds = live / 'credentials.json'
        creds.write_text(json.dumps(dict(username='test', password='secret')))
        self.source = self.root / 'backup'
        backup.snapshot(self.source, [live / 'navidrome.db'], [creds])
        self.dest = self.root / 'recovered'
        self.config = self.root / 'recovery.local.json'
        self.config.write_text(json.dumps(dict(backup=str(self.source), destination=str(self.dest),
                                              music=str(self.music), port=15436)))

    def test_preview_never_writes_or_calls_docker(self):
        before = sorted(self.root.rglob('*'))
        with patch.object(recovery.subprocess, 'run') as docker:
            report = recovery.run(self.config)
            docker.assert_not_called()
        self.assertEqual(report['status'], 'preview')
        self.assertEqual(report['catalog_files'], 1)
        self.assertEqual(before, sorted(self.root.rglob('*')))
        self.assertNotIn('secret', json.dumps(report))

    def test_prepare_preserves_all_files_and_protects_originals(self):
        plan = recovery.inspect(self.config)
        recovery.prepare(plan)
        self.assertEqual(recovery.signatures(self.dest / 'data/navidrome.db'), plan['before'])
        self.assertEqual(backup.verify(self.dest / 'archive'), plan['manifest'])
        self.assertEqual((self.dest / 'credentials.json').stat().st_mode & 0o777, 0o600)
        spec = json.loads((self.dest / 'compose.json').read_text())['services']['navidrome']
        self.assertEqual(spec['ports'], ['127.0.0.1:15436:4533'])
        self.assertIs(spec['volumes'][1]['read_only'], True)
        self.assertEqual(spec['environment']['ND_SCANNER_ENABLED'], 'false')
        self.assertEqual(spec['environment']['ND_LASTFM_ENABLED'], 'false')
        with self.assertRaises(ValueError):
            recovery.inspect(self.config)

    def test_missing_audio_and_symlink_escape_refused_before_writes(self):
        (self.music / 'track.m4a').unlink()
        with self.assertRaises(ValueError):
            recovery.run(self.config)
        outside = self.root / 'outside.m4a'
        outside.write_bytes(b'not mounted')
        (self.music / 'track.m4a').symlink_to(outside)
        with self.assertRaises(ValueError):
            recovery.run(self.config)
        self.assertFalse(self.dest.exists())

    def test_overlapping_destination_and_unknown_options_refused(self):
        original = json.loads(self.config.read_text())
        for path in (self.music / 'nested', self.source / 'nested', self.root / 'live/nested'):
            self.config.write_text(json.dumps(dict(original, destination=str(path))))
            with self.assertRaises(ValueError):
                recovery.run(self.config)
            self.assertFalse(path.exists())
        self.config.write_text(json.dumps(dict(original, enable_scrobbling=True)))
        with self.assertRaises(ValueError):
            recovery.run(self.config)

    def test_corruption_and_ambiguous_database_fail_safely(self):
        manifest = backup.verify(self.source)
        database = self.source / manifest['files'][0]['file']
        duplicate = self.source / '002-navidrome.db'
        duplicate.write_bytes(database.read_bytes())
        extra = dict(manifest['files'][0], file=duplicate.name)
        manifest['files'].append(extra)
        (self.source / 'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            recovery.inspect(self.config)
        cfg = json.loads(self.config.read_text())
        self.config.write_text(json.dumps(dict(cfg, database_entry=database.name)))
        recovery.inspect(self.config)
        database.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            recovery.inspect(self.config)
        self.assertFalse(self.dest.exists())

    def test_insufficient_space_does_not_create_destination(self):
        with patch.object(recovery.shutil, 'disk_usage', return_value=Mock(free=1)):
            with self.assertRaises(ValueError):
                recovery.prepare(recovery.inspect(self.config))
        self.assertFalse(self.dest.exists())

    def test_failed_start_stops_only_new_project_keeps_archive_and_no_secrets(self):
        with patch.object(recovery.socket, 'socket'), patch.object(recovery.subprocess, 'run') as execute:
            execute.return_value.returncode = 0
            execute.return_value.stdout = ''
            with patch.object(recovery, 'verify_running', side_effect=ValueError('secret=DO_NOT_PRINT')):
                with self.assertRaises(ValueError):
                    recovery.run(self.config, apply=True)
        calls = [args.args[0] for args in execute.call_args_list]
        self.assertEqual(calls[-1][-1], 'stop')
        self.assertTrue(all(str(self.dest / 'compose.json') in cmd for cmd in calls[1:]))
        self.assertTrue((self.dest / 'archive/manifest.json').exists())
        result = (self.dest / 'recovery-result.json').read_text()
        self.assertNotIn('DO_NOT_PRINT', result)
        self.assertEqual(json.loads(result)['status'], 'failed')

    def test_success_records_verification_and_does_not_enable_worker(self):
        report = dict(status='verified', worker_enabled=False)
        with patch.object(recovery.socket, 'socket'), patch.object(recovery.subprocess, 'run') as execute, \
                patch.object(recovery, 'verify_running', return_value=report):
            execute.return_value.stdout = ''
            self.assertEqual(recovery.run(self.config, apply=True), report)
        self.assertEqual(json.loads((self.dest / 'recovery-result.json').read_text()), report)

    def test_existing_project_is_not_recreated_or_stopped(self):
        with patch.object(recovery.socket, 'socket'), patch.object(recovery.subprocess, 'run') as execute:
            execute.return_value.stdout = 'existing-container\n'
            with self.assertRaises(ValueError):
                recovery.run(self.config, apply=True)
            self.assertEqual(execute.call_count, 1)
        self.assertFalse(self.dest.exists())

    def test_interruption_stops_new_instance_and_retains_recoverable_files(self):
        with patch.object(recovery.socket, 'socket'), patch.object(recovery.subprocess, 'run') as execute:
            execute.return_value.stdout = ''
            execute.return_value.returncode = 0
            with patch.object(recovery, 'verify_running', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    recovery.run(self.config, apply=True)
            self.assertEqual(execute.call_args.args[0][-1], 'stop')
        self.assertTrue((self.dest / 'data/navidrome.db').is_file())
        report = json.loads((self.dest / 'recovery-result.json').read_text())
        self.assertEqual(report['error'], 'KeyboardInterrupt')
        self.assertTrue(report['stopped'])

    def test_cli_help_offline(self):
        with self.assertRaises(SystemExit) as error:
            recovery.main(['--help'])
        self.assertEqual(error.exception.code, 0)
