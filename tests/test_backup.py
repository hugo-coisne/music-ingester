import json
import sqlite3

from music_ingest.backup import snapshot, restore, verify
from tests.support import TemporaryTest


class BackupTests(TemporaryTest):
    def test_live_wal_backup_and_restore_preserve_rows_and_private_config(self):
        db = sqlite3.connect(self.root / 'live.db')
        self.addCleanup(db.close)
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE favorites (id INTEGER)')
        db.execute('INSERT INTO favorites VALUES (42)')
        db.commit()
        config = self.root / 'secret.env'
        config.write_text('PRIVATE=value')
        snapshot(self.root / 'backup', [self.root / 'live.db'], [config])
        restore(self.root / 'backup', self.root / 'restored')
        with sqlite3.connect(self.root / 'restored/000-live.db') as saved:
            self.assertEqual(saved.execute('SELECT * FROM favorites').fetchall(), [(42,)])
        self.assertEqual((self.root / 'restored/001-secret.env').stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            restore(self.root / 'backup', self.root / 'restored')
        with self.assertRaises(FileExistsError):
            snapshot(self.root / 'backup', [], [config])

    def test_corruption_is_rejected_before_restore_creates_directory(self):
        config = self.root / 'config'
        config.write_text('original')
        snapshot(self.root / 'backup', [], [config])
        (self.root / 'backup/000-config').write_text('corrupt')
        with self.assertRaises(ValueError):
            restore(self.root / 'backup', self.root / 'restored')
        self.assertFalse((self.root / 'restored').exists())

    def test_manifest_traversal_and_symlinks_are_rejected(self):
        config = self.root / 'config'
        config.write_text('value')
        snapshot(self.root / 'backup', [], [config])
        manifest = self.root / 'backup/manifest.json'
        data = json.loads(manifest.read_text())
        data['files'][0]['file'] = '../config'
        manifest.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            verify(self.root / 'backup')

    def test_missing_source_creates_no_backup(self):
        with self.assertRaises(ValueError):
            snapshot(self.root / 'backup', [self.root / 'missing.db'], [])
        self.assertFalse((self.root / 'backup').exists())
