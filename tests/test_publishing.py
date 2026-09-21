"""Regression tests for publishing."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from music_ingest import publishing

from tests.support import TemporaryTest, sample_metadata


class PublishingTests(TemporaryTest):
    def source(self, name, content=b'new'):
        path = self.root / name
        path.write_bytes(content)
        return path

    def test_repeated_collisions_preserve_every_file(self):
        paths = []
        for i in range(4):
            source = self.source(f'{i}.m4a', str(i).encode())
            destination = publishing.move_to_library(
                source, sample_metadata(), 'video1', self.config.library_dir,
            )
            paths.append(destination)
            self.assertFalse(source.exists())
        self.assertEqual(len(set(paths)), 4)
        self.assertEqual([p.read_bytes() for p in paths], [b'0', b'1', b'2', b'3'])
        self.assertTrue(all(p.name.startswith('01 - Song') for p in paths))

    def test_concurrent_publication_is_exclusive(self):
        sources = [self.source(f'{i}.m4a', str(i).encode()) for i in range(8)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            paths = list(pool.map(lambda p: publishing.move_to_library(
                p, sample_metadata(), 'video1', self.config.library_dir), sources))
        self.assertEqual(len(set(paths)), 8)
        self.assertEqual({p.read_bytes() for p in paths}, {str(i).encode() for i in range(8)})
        self.assertFalse(list(self.config.library_dir.rglob('.ingest-*')))

    def test_publication_preserves_source_permissions(self):
        source = self.source('source.m4a')
        source.chmod(0o640)
        destination = publishing.move_to_library(
            source, sample_metadata(), 'video1', self.config.library_dir,
        )
        self.assertEqual(destination.stat().st_mode & 0o777, 0o640)

    def test_copy_failure_preserves_source_and_cleans_partial_file(self):
        source = self.source('source.m4a')
        with patch.object(publishing.shutil, 'copyfileobj', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                publishing.move_to_library(source, sample_metadata(), 'video1', self.config.library_dir)
        self.assertEqual(source.read_bytes(), b'new')
        self.assertFalse([p for p in self.config.library_dir.rglob('*') if p.is_file()])

