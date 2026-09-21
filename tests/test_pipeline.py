"""Regression tests for pipeline."""

import sqlite3
from unittest.mock import patch
from music_ingest import pipeline
from music_ingest import download as downloader

from tests.support import TemporaryTest, track


class PipelineTests(TemporaryTest):
    def test_download_failure_is_recorded_and_processing_continues(self):
        client = self.client([track(), track('video2')])
        with patch.object(downloader, 'download', side_effect=RuntimeError('unavailable')) as download:
            self.assertEqual(pipeline.run_sync(client, 'p', self.config), 1)
        self.assertEqual(download.call_count, 2)
        with sqlite3.connect(self.config.db_path) as db:
            self.assertEqual(db.execute('select status,error from imports').fetchall(),
                             [('error', 'unavailable'), ('error', 'unavailable')])
        self.assertIn('imported=0', self.output.getvalue())
        self.assertIn('failed=2', self.output.getvalue())

