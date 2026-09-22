"""Maintenance commands never touch unrecognized or in-flight artifacts."""

import io
import sqlite3
from contextlib import redirect_stdout

from music_ingest import history, maintenance
from tests.support import TemporaryTest


class MaintenanceTests(TemporaryTest):
    def test_cleanup_dry_run_then_apply(self):
        self.config.staging_dir.mkdir()
        db = history.connect_db(self.config.db_path)
        self.addCleanup(db.close)
        history.mark_pending(db, "doneid", "Artist", "Title")
        history.mark_done(db, "doneid", self.root / "song.m4a")
        history.mark_pending(db, "errorid", "Artist", "Title")
        history.mark_error(db, "errorid", RuntimeError("failure"))
        history.mark_pending(db, "pendingid", "Artist", "Title")
        names = [
            "doneid.info.json", "doneid.cover.jpg", "doneid.m4a",
            "errorid.info.json", "errorid.m4a", "pendingid.info.json", "unknown.cover.jpg",
        ]
        for name in names:
            (self.config.staging_dir / name).write_text("artifact")
        maintenance.cleanup(self.config)
        self.assertEqual(len(list(self.config.staging_dir.iterdir())), len(names))
        maintenance.cleanup(self.config, apply=True)
        self.assertEqual(
            {path.name for path in self.config.staging_dir.iterdir()},
            set(names) - {"doneid.info.json", "doneid.cover.jpg"},
        )
        maintenance.cleanup(self.config, apply=True, drop_errors=True)
        self.assertEqual(
            {path.name for path in self.config.staging_dir.iterdir()},
            {"doneid.m4a", "pendingid.info.json", "unknown.cover.jpg"},
        )

    def test_status_is_read_only_for_missing_database(self):
        self.assertEqual(maintenance.status(self.config), 0)
        self.assertFalse(self.config.db_path.exists())

    def test_status_reports_missing_recorded_file(self):
        db = history.connect_db(self.config.db_path)
        self.addCleanup(db.close)
        history.mark_pending(db, "video1", "Artist", "Title")
        history.mark_done(db, "video1", self.root / "missing.m4a")
        self.assertEqual(maintenance.status(self.config), 1)
        self.assertIn("Missing recorded files: 1", self.output.getvalue())

    def test_doctor_does_not_create_runtime_directories(self):
        maintenance.doctor(self.config)
        self.assertFalse(self.config.staging_dir.exists())
        self.assertFalse(self.config.library_dir.exists())

