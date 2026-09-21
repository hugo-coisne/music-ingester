"""Manual diagnostic commands share the same catalog helpers as ingestion."""

from unittest.mock import patch

from music_ingest import diagnostics
from tests.support import TemporaryTest, track


class DiagnosticTests(TemporaryTest):
    def test_playlist_listing_handles_missing_artists(self):
        value = track()
        value["artists"] = None
        client = self.client([value])
        with patch.object(diagnostics, "YTMusic", return_value=client):
            diagnostics.playlist_main(["playlist"])
        self.assertIn("video1 |  - Song", self.output.getvalue())

    def test_artwork_inspection_reuses_album_lookup(self):
        values = [track(), track("video2")]
        for value in values:
            value["album"] = {"id": "album1", "name": "Album"}
        client = self.client(values)
        client.get_album.return_value = {"title": "Album", "thumbnails": []}
        with patch.object(diagnostics, "YTMusic", return_value=client):
            diagnostics.artwork_main(["playlist"])
        client.get_album.assert_called_once_with("album1")
        self.assertIn("ALBUM:", self.output.getvalue())
