"""The package and legacy scripts remain usable from a source checkout."""

import os
import subprocess
import sys
from pathlib import Path

from music_ingest.config import Config
from tests.support import TemporaryTest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class EntrypointTests(TemporaryTest):
    def test_all_commands_offer_help_without_network_or_runtime_files(self):
        commands = [
            [str(PROJECT_ROOT / "sync.py")],
            [str(PROJECT_ROOT / "test_playlist.py")],
            [str(PROJECT_ROOT / "inspect_artwork.py")],
            ["-m", "music_ingest"],
        ]
        environment = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}
        for command in commands:
            with self.subTest(command=command):
                result = subprocess.run(
                    [sys.executable, "-B", *command, "--help"],
                    cwd=self.root, env=environment, capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("playlist_id", result.stdout)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_default_paths_still_point_to_project_root(self):
        defaults = Config()
        self.assertEqual(defaults.library_dir, PROJECT_ROOT / "library")
        self.assertEqual(defaults.staging_dir, PROJECT_ROOT / "staging")
        self.assertEqual(defaults.db_path, PROJECT_ROOT / "state" / "ingest.db")
