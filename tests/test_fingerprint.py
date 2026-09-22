"""Chromaprint output handling across host and Debian container builds."""

from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from music_ingest.fingerprint import fingerprint


class FingerprintTests(unittest.TestCase):
    def result(self, code, stdout, stderr=""):
        with patch("music_ingest.fingerprint.shutil.which", return_value="/usr/bin/fpcalc"), \
             patch("music_ingest.fingerprint.subprocess.run", return_value=
                   subprocess.CompletedProcess([], code, stdout, stderr)):
            return fingerprint(Path("audio.m4a"))

    def test_valid_result_with_known_debian_eof_warning(self):
        self.assertEqual(self.result(3, '{"fingerprint": "abc"}',
                                    "ERROR: Error decoding audio frame (End of file)\n"), "abc")

    def test_other_decoder_errors_cannot_match(self):
        self.assertIsNone(self.result(3, '{"fingerprint": "abc"}', "Corrupt input"))
        self.assertIsNone(self.result(1, '{"fingerprint": "abc"}',
                                      "ERROR: Error decoding audio frame (End of file)"))
        self.assertIsNone(self.result(3, "", "ERROR: Error decoding audio frame (End of file)"))

    def test_missing_or_malformed_fingerprint_cannot_match(self):
        for output in ('{}', '{"fingerprint": ""}', '{"fingerprint": 12}', 'not JSON'):
            with self.subTest(output=output):
                self.assertIsNone(self.result(0, output))
