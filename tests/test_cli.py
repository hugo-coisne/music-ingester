"""Regression tests for cli."""

from unittest.mock import patch
from music_ingest import cli

from tests.support import TemporaryTest


class CliTests(TemporaryTest):
    def test_cli_passes_custom_paths(self):
        with patch.object(cli, 'YTMusic'), patch.object(cli, 'run_sync', return_value=0) as run:
            result = cli.main(['p', '--list-only', '--library-dir', str(self.root / 'l'),
                '--staging-dir', str(self.root / 's'), '--db-path', str(self.root / 'db'),
                '--reference-library', str(self.root / 'r1'),
                '--reference-library', str(self.root / 'r2'), '--download-timeout', '30'])
        self.assertEqual(result, 0)
        config = run.call_args.args[2]
        self.assertEqual(config.library_dir, self.root / 'l')
        self.assertEqual(config.reference_libraries, (self.root / 'r1', self.root / 'r2'))
        self.assertEqual(config.download_timeout, 30)

    def test_cli_reports_playlist_failure(self):
        with patch.object(cli, 'YTMusic', side_effect=RuntimeError('offline')):
            self.assertEqual(cli.main(['p', '--list-only']), 1)

    def test_profile_can_be_selected_from_cli_or_environment(self):
        parser = cli.build_parser()
        args = parser.parse_args(['p', '--profile', 'sandbox'])
        selected = cli.resolve_config(args, environment={})
        self.assertEqual(
            selected.library_dir,
            cli.DEFAULT_CONFIG_PATH.parent / 'environments/sandbox/library',
        )

        args = parser.parse_args(['p'])
        selected = cli.resolve_config(
            args, environment={'MUSIC_INGEST_PROFILE': 'sandbox'},
        )
        self.assertIn('environments/sandbox', str(selected.db_path))
