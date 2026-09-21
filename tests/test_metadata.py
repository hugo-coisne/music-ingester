"""Metadata mapping is a pure transformation of catalog responses."""

from music_ingest.metadata import build_track_metadata
from tests.support import TemporaryTest, track


class MetadataTests(TemporaryTest):
    def test_missing_catalog_fields_have_explicit_defaults(self):
        result = build_track_metadata({}, None)
        self.assertEqual(result["title"], "Unknown")
        self.assertEqual(result["artists"], ["Unknown Artist"])
        self.assertIsNone(result["album"])
        self.assertIsNone(result["track_number"])

    def test_album_enrichment_preserves_playlist_identity(self):
        value = track("video2", title="Playlist title")
        value["album"] = {"id": "album1", "name": "Album"}
        album = {
            "year": "2026",
            "artists": [{"name": "Album artist"}],
            "tracks": [{"videoId": "video1"}, {"videoId": "video2"}],
        }
        result = build_track_metadata(value, album)
        self.assertEqual(result["title"], "Playlist title")
        self.assertEqual(result["artists"], ["Air"])
        self.assertEqual(result["album_artist"], "Album artist")
        self.assertEqual(result["track_number"], 2)
        self.assertEqual(result["track_total"], 2)
        self.assertEqual(result["year"], "2026")
