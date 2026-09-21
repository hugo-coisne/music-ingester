"""Regression tests for catalog."""

from unittest.mock import Mock
from music_ingest import artwork, metadata
from music_ingest.catalog import AlbumCache

from tests.support import TemporaryTest, track


class CatalogTests(TemporaryTest):
    def test_album_metadata_and_artwork_share_cache(self):
        client = Mock()
        client.get_album.return_value = dict(year='2026', artists=[{'name': 'Air'}],
            tracks=[{'videoId': 'video1'}], thumbnails=[dict(url='cover', width=50, height=50)])
        value = track()
        value['album'] = dict(id='album1', name='Album')
        cache = AlbumCache(client)
        tags = metadata.build_track_metadata(value, cache.get_for_track(value))
        self.assertEqual(tags['track_number'], 1)
        self.assertEqual(artwork.choose_artwork(value, cache.get_for_track(value))['url'], 'cover')
        artwork.choose_artwork(value, cache.get_for_track(value))
        client.get_album.assert_called_once_with('album1')

    def test_failed_album_lookup_is_cached_and_thumbnail_used(self):
        client = Mock()
        client.get_album.side_effect = RuntimeError('offline')
        value = track()
        value.update(album=dict(id='album1', name='Album'), thumbnails=[dict(url='fallback')])
        cache = AlbumCache(client)
        metadata.build_track_metadata(value, cache.get_for_track(value))
        cover = artwork.choose_artwork(value, cache.get_for_track(value))
        self.assertEqual(cover['url'], 'fallback')
        client.get_album.assert_called_once()

