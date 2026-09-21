"""Regression tests for audio integration."""

import shutil
import sqlite3
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
from music_ingest import artwork, library, metadata, pipeline
from music_ingest import download as downloader
from mutagen.mp4 import MP4
from PIL import Image

from tests.support import TemporaryTest, sample_metadata, track


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and ffprobe required')
class AudioIntegrationTests(TemporaryTest):
    def setUp(self):
        super().setUp()
        self.fixture = self.root / 'fixture.m4a'
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                        '-i', 'sine=frequency=440:duration=1', '-c:a', 'aac', str(self.fixture)],
                       check=True, capture_output=True, timeout=30)

    def fake_download(self, video_id, staging, timeout):
        path = staging / f'{video_id}.m4a'
        shutil.copyfile(self.fixture, path)
        return path

    def test_import_deduplicates_within_run_and_rerun(self):
        client = self.client([track(), track('video2')])
        with patch.object(downloader, 'download', side_effect=self.fake_download) as download:
            self.assertEqual(pipeline.run_sync(client, 'p', self.config), 0)
            self.assertEqual(pipeline.run_sync(client, 'p', self.config), 0)
        download.assert_called_once()
        files = list(self.config.library_dir.rglob('*.m4a'))
        self.assertEqual(len(files), 1)
        audio = MP4(files[0])
        self.assertEqual(audio['\xa9nam'], ['Song'])
        self.assertEqual(bytes(audio['----:com.apple.iTunes:YOUTUBE_VIDEO_ID'][0]), b'video1')
        with sqlite3.connect(self.config.db_path) as db:
            self.assertEqual(db.execute('select status from imports order by video_id').fetchall(),
                             [('done',), ('existing',)])

    def test_partial_failure_retries_without_redownloading_success(self):
        client = self.client([track(), track('video2', title='Second song')])
        def first_download(video_id, staging, timeout):
            if video_id == 'video1':
                raise subprocess.TimeoutExpired('yt-dlp', timeout)
            return self.fake_download(video_id, staging, timeout)
        with patch.object(downloader, 'download', side_effect=first_download):
            self.assertEqual(pipeline.run_sync(client, 'p', self.config), 1)
        self.assertIn('imported=1', self.output.getvalue())
        self.assertIn('failed=1', self.output.getvalue())
        with patch.object(downloader, 'download', side_effect=self.fake_download) as download:
            self.assertEqual(pipeline.run_sync(client, 'p', self.config), 0)
        download.assert_called_once_with('video1', self.config.staging_dir, 900)
        with sqlite3.connect(self.config.db_path) as db:
            self.assertEqual(db.execute('select status,error from imports').fetchall(),
                             [('done', None), ('done', None)])

    def test_missing_imported_file_is_downloaded_again(self):
        client = self.client([track()])
        with patch.object(downloader, 'download', side_effect=self.fake_download) as download:
            self.assertEqual(pipeline.run_sync(client, 'p', self.config), 0)
            next(self.config.library_dir.rglob('*.m4a')).unlink()
            self.assertEqual(pipeline.run_sync(client, 'p', self.config), 0)
        self.assertEqual(download.call_count, 2)

    def test_artwork_http_failure_does_not_block_import(self):
        value = track()
        value['thumbnails'] = [dict(url='https://example.invalid/cover')]
        with patch.object(downloader, 'download', side_effect=self.fake_download), \
             patch.object(artwork.requests, 'get', side_effect=artwork.requests.Timeout('timeout')):
            self.assertEqual(pipeline.run_sync(self.client([value]), 'p', self.config), 0)
        self.assertEqual(len(list(self.config.library_dir.rglob('*.m4a'))), 1)
        self.assertIn('artwork_warnings=1', self.output.getvalue())
        self.assertIn('imported=1', self.output.getvalue())

    def test_multiple_imports_share_one_album_lookup(self):
        values = [track(), track('video2', title='Second song')]
        for value in values:
            value['album'] = {'id': 'album1', 'name': 'Album'}
        client = self.client(values)
        client.get_album.return_value = {'title': 'Album', 'tracks': values}
        with patch.object(downloader, 'download', side_effect=self.fake_download):
            self.assertEqual(pipeline.run_sync(client, 'p', self.config), 0)
        client.get_album.assert_called_once_with('album1')
        self.assertEqual(len(list(self.config.library_dir.rglob('*.m4a'))), 2)

    def test_artwork_and_metadata_round_trip(self):
        cover = self.root / 'cover.jpg'
        Image.new('RGB', (32, 32), 'red').save(cover)
        metadata.write_metadata(self.fixture, sample_metadata(), 'video1')
        artwork.embed_artwork(self.fixture, cover)
        audio = MP4(self.fixture)
        self.assertEqual(audio['trkn'], [(1, 2)])
        self.assertEqual(audio['\xa9alb'], ['Album'])
        self.assertEqual(bytes(audio['covr'][0]), cover.read_bytes())
        self.assertIsNotNone(library.index_audio_file(self.fixture))

    def test_download_normalization_and_validation(self):
        result = subprocess.CompletedProcess([], 0, str(self.fixture) + '\n', '')
        with patch.object(downloader.subprocess, 'run', return_value=result) as run:
            self.assertEqual(downloader.download('video1', self.root, 30), self.fixture)
        args = run.call_args.args[0]
        self.assertIn('--extract-audio', args)
        self.assertEqual(args[args.index('--audio-format') + 1], 'm4a')
        self.assertEqual(run.call_args.kwargs['timeout'], 30)
        invalid = self.root / 'invalid.webm'
        invalid.write_bytes(b'not mp4')
        result.stdout = str(invalid)
        with patch.object(downloader.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(RuntimeError, 'M4A'):
                downloader.download('video1', self.root)

    def test_real_opus_fallback_converts_to_m4a(self):
        from yt_dlp import YoutubeDL
        from yt_dlp.postprocessor.ffmpeg import FFmpegExtractAudioPP
        opus = self.root / 'fallback.webm'
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-i', str(self.fixture),
                        '-c:a', 'libopus', str(opus)], check=True, capture_output=True, timeout=30)
        with YoutubeDL({'quiet': True}) as downloader:
            processor = FFmpegExtractAudioPP(downloader, preferredcodec='m4a', preferredquality='0')
            _, info = processor.run(dict(filepath=str(opus), ext='webm'))
        self.assertEqual(Path(info['filepath']).suffix, '.m4a')
        self.assertGreater(MP4(info['filepath']).info.length, 0)

