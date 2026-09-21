"""Interrupted publication is reconciled using embedded source IDs."""

import shutil
import sqlite3
import subprocess
import unittest

from music_ingest import history, metadata
from tests.support import TemporaryTest, sample_metadata


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
class RecoveryTests(TemporaryTest):
    def test_published_file_completes_interrupted_row(self):
        self.config.library_dir.mkdir()
        audio = self.config.library_dir / "song.m4a"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "sine=duration=1", "-c:a", "aac", str(audio)],
            check=True, capture_output=True,
        )
        metadata.write_metadata(audio, sample_metadata(), "video1")
        db = history.connect_db(self.config.db_path)
        self.addCleanup(db.close)
        history.mark_pending(db, "video1", "Air", "Song")
        history.mark_stage(db, "video1", "publishing", self.root / "lost.m4a")

        self.assertEqual(history.recover_published(db, self.config.library_dir), 1)
        self.assertEqual(history.recover_published(db, self.config.library_dir), 0)
        self.assertEqual(
            db.execute("SELECT status, local_path FROM imports").fetchone(),
            ("done", str(audio)),
        )

    def test_unrelated_file_does_not_complete_row(self):
        self.config.library_dir.mkdir()
        db = history.connect_db(self.config.db_path)
        self.addCleanup(db.close)
        history.mark_pending(db, "video1", "Air", "Song")
        (self.config.library_dir / "unrelated.m4a").write_bytes(b"invalid")
        self.assertEqual(history.recover_published(db, self.config.library_dir), 0)
        self.assertEqual(db.execute("SELECT status FROM imports").fetchone()[0], "pending")

    def test_second_writer_cannot_enter_import_lock(self):
        with history.import_lock(self.config.db_path):
            with self.assertRaisesRegex(RuntimeError, "another sync"):
                with history.import_lock(self.config.db_path):
                    pass
        with history.import_lock(self.config.db_path):
            pass
