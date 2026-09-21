"""Temporary workspaces and synthetic data shared by regression tests."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from music_ingest import config


def track(video_id='video1', title='Song', artist='Air', duration=1):
    return dict(videoId=video_id, title=title, artists=[{'name': artist}],
                duration_seconds=duration)


def sample_metadata():
    return dict(title='Song', artists=['Air'], album='Album', album_artist=None,
                year='2026', track_number=1, track_total=2, album_id='album1')


class TemporaryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = config.Config(self.root / 'library', self.root / 'staging',
                                  self.root / 'state' / 'ingest.db')
        self.output = io.StringIO()
        self.errors = io.StringIO()
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(contextlib.redirect_stdout(self.output))
        stack.enter_context(contextlib.redirect_stderr(self.errors))

    def client(self, tracks):
        client = Mock()
        client.get_playlist.return_value = dict(title='Test', tracks=tracks)
        return client

    def item(self, artist='Air', duration=1):
        path = self.root / 'existing.m4a'
        path.touch()
        return dict(path=path, title='Song', artists=[artist], duration=duration)

