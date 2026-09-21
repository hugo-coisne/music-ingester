"""Named profile loading and override precedence."""

import os
from pathlib import Path

from music_ingest import config
from tests.support import TemporaryTest


class ConfigTests(TemporaryTest):
    def document(self):
        return {
            "settings": {"default_profile": "production"},
            "profiles": {
                "production": {
                    "library_dir": "production/library",
                    "staging_dir": "production/staging",
                    "db_path": "production/state.db",
                    "reference_libraries": ["shared", "/absolute/reference"],
                    "download_timeout": 600,
                },
                "sandbox": {
                    "library_dir": "sandbox/library",
                    "staging_dir": "sandbox/staging",
                    "db_path": "sandbox/state.db",
                },
            },
        }

    def test_profile_paths_are_relative_to_config_file(self):
        config_path = self.root / "settings" / "music-ingest.toml"
        result = config.build_config(
            document=self.document(),
            profile="production",
            config_path=config_path,
            environment={},
        )
        self.assertEqual(result.library_dir, self.root / "settings/production/library")
        self.assertEqual(result.staging_dir, self.root / "settings/production/staging")
        self.assertEqual(result.db_path, self.root / "settings/production/state.db")
        self.assertEqual(
            result.reference_libraries,
            (self.root / "settings/shared", Path("/absolute/reference")),
        )
        self.assertEqual(result.download_timeout, 600)

    def test_precedence_is_cli_then_environment_then_profile(self):
        environment = {
            "MUSIC_INGEST_LIBRARY_DIR": str(self.root / "environment/library"),
            "MUSIC_INGEST_DOWNLOAD_TIMEOUT": "120",
            "MUSIC_INGEST_REFERENCE_LIBRARIES": os.pathsep.join(
                [str(self.root / "reference-a"), str(self.root / "reference-b")]
            ),
        }
        result = config.build_config(
            document=self.document(),
            profile="production",
            config_path=self.root / "music-ingest.toml",
            environment=environment,
            cli_values={
                "library_dir": self.root / "cli/library",
                "download_timeout": 30,
            },
        )
        self.assertEqual(result.library_dir, self.root / "cli/library")
        self.assertEqual(result.staging_dir, self.root / "production/staging")
        self.assertEqual(result.download_timeout, 30)
        self.assertEqual(
            result.reference_libraries,
            (self.root / "reference-a", self.root / "reference-b"),
        )

    def test_unknown_profile_and_setting_are_rejected(self):
        with self.assertRaisesRegex(config.ConfigurationError, "was not found"):
            config.build_config(
                document=self.document(), profile="missing",
                config_path=self.root / "config.toml", environment={},
            )
        document = self.document()
        document["profiles"]["sandbox"]["typo"] = True
        with self.assertRaisesRegex(config.ConfigurationError, "unknown settings: typo"):
            config.build_config(
                document=document, profile="sandbox",
                config_path=self.root / "config.toml", environment={},
            )

    def test_invalid_timeout_and_reference_list_are_rejected(self):
        document = self.document()
        document["profiles"]["sandbox"]["download_timeout"] = 0
        with self.assertRaisesRegex(config.ConfigurationError, "greater than zero"):
            config.build_config(
                document=document, profile="sandbox",
                config_path=self.root / "config.toml", environment={},
            )
        document["profiles"]["sandbox"]["download_timeout"] = 10
        document["profiles"]["sandbox"]["reference_libraries"] = "not-an-array"
        with self.assertRaisesRegex(config.ConfigurationError, "array of paths"):
            config.build_config(
                document=document, profile="sandbox",
                config_path=self.root / "config.toml", environment={},
            )

    def test_toml_file_and_default_profile_are_loaded(self):
        path = self.root / "music-ingest.toml"
        path.write_text(
            '[settings]\ndefault_profile = "sandbox"\n'
            '[profiles.sandbox]\nlibrary_dir = "library"\n',
            encoding="utf-8",
        )
        document = config.load_document(path)
        self.assertEqual(config.default_profile(document), "sandbox")
        result = config.build_config(
            document=document, profile="sandbox", config_path=path, environment={},
        )
        self.assertEqual(result.library_dir, self.root / "library")

