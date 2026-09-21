"""Regression tests for preview."""

import sqlite3
from unittest.mock import patch
from music_ingest import history, library, pipeline
from music_ingest import download as downloader

from tests.support import TemporaryTest, track


class PreviewTests(TemporaryTest):
    def test_fresh_preview_creates_nothing(self):
        client = self.client([track(), track(), track(video_id=None)])
        with patch.object(downloader, 'download') as download:
            self.assertEqual(pipeline.run_sync(client, 'playlist', self.config, True), 0)
        download.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertIn('new=1', self.output.getvalue())
        self.assertIn('skipped=2', self.output.getvalue())

    def test_existing_database_and_duplicate_preview_remain_unchanged(self):
        db = history.connect_db(self.config.db_path)
        db.close()
        item = self.item()
        index = {}
        library.add_to_library_index(index, item)
        before = self.config.db_path.read_bytes()
        with patch.object(library, 'build_library_index', return_value=index):
            self.assertEqual(pipeline.run_sync(self.client([track()]), 'p', self.config, True), 0)
        self.assertEqual(self.config.db_path.read_bytes(), before)
        self.assertFalse(self.config.staging_dir.exists())
        self.assertIn('existing=1', self.output.getvalue())

    def test_preview_connection_rejects_writes(self):
        history.connect_db(self.config.db_path).close()
        db = history.connect_db(self.config.db_path, read_only=True)
        self.addCleanup(db.close)
        with self.assertRaises(sqlite3.OperationalError):
            history.mark_pending(db, 'video1', 'Air', 'Song')

