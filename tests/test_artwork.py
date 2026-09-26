"""Artwork policy, transient retries, and preservation on embedding failure."""

import io
from unittest.mock import Mock, patch

from PIL import Image
import requests

from music_ingest import artwork
from tests.support import TemporaryTest, track


class ArtworkTests(TemporaryTest):
    @staticmethod
    def image_response(status=200):
        content = io.BytesIO()
        Image.new("RGB", (8, 8), "red").save(content, "JPEG")
        response = requests.Response()
        response.status_code = status
        response._content = content.getvalue()
        response.raw = Mock()
        response.url = "https://example.test/cover.jpg"
        return response

    def test_transient_artwork_failure_is_retried(self):
        source = {"url": "https://example.test/cover.jpg", "source": "test"}
        with (
            patch.object(artwork.requests, "get", side_effect=[
                requests.ConnectionError("temporary DNS failure"), self.image_response(),
            ]) as get,
            patch.object(artwork.time, "sleep") as sleep,
        ):
            cover, original, status = artwork.prepare_artwork("video", source, self.root)
        self.assertTrue(cover.is_file())
        self.assertTrue(original.is_file())
        self.assertEqual(status, "test:square")
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_permanent_artwork_failure_is_not_retried(self):
        response = self.image_response(status=404)
        with (
            patch.object(artwork.requests, "get", return_value=response) as get,
            patch.object(artwork.time, "sleep") as sleep,
            self.assertRaises(requests.HTTPError),
        ):
            artwork.download_artwork("https://example.test/missing.jpg")
        get.assert_called_once()
        sleep.assert_not_called()

    def test_transient_artwork_failure_stops_after_three_attempts(self):
        with (
            patch.object(artwork.requests, "get", side_effect=requests.Timeout("timeout")) as get,
            patch.object(artwork.time, "sleep") as sleep,
            self.assertRaises(requests.Timeout),
        ):
            artwork.download_artwork("https://example.test/cover.jpg")
        self.assertEqual(get.call_count, 3)
        self.assertEqual([call.args for call in sleep.call_args_list], [(1,), (2,)])

    def test_embedding_failure_does_not_damage_original(self):
        audio = self.root / "original.m4a"
        audio.write_bytes(b"original audio")

        def corrupt_then_fail(path, cover):
            path.write_bytes(b"corrupt")
            raise OSError("embedding failed")

        prepared = (self.root / "cover.jpg", None, "square")
        with (
            patch.object(artwork, "choose_artwork", return_value={"url": "cover"}),
            patch.object(artwork, "prepare_artwork", return_value=prepared),
            patch.object(artwork, "embed_artwork", side_effect=corrupt_then_fail),
        ):
            outcome = artwork.apply_artwork(track(), None, audio, self.root)
        self.assertEqual(outcome, artwork.ArtworkOutcome.FAILED)
        self.assertEqual(audio.read_bytes(), b"original audio")
        self.assertEqual(list(self.root.iterdir()), [audio])

    def test_flat_sidebars_are_cropped(self):
        image = Image.new("RGB", (80, 40), "black")
        image.paste("red", (20, 0, 60, 40))
        cropped, status = artwork.crop_artwork(image)
        self.assertEqual(cropped.size, (40, 40))
        self.assertEqual(cropped.getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(status, ":center-crop")

    def test_detailed_sidebars_are_preserved(self):
        image = Image.new("RGB", (80, 40), "black")
        image.paste("white", (0, 0, 80, 20))
        cropped, status = artwork.crop_artwork(image)
        self.assertIs(cropped, image)
        self.assertEqual(status, ":uncropped")

    def test_missing_artwork_does_not_touch_audio(self):
        audio = self.root / "audio.m4a"
        audio.write_bytes(b"audio")
        outcome = artwork.apply_artwork(track(), None, audio, self.root)
        self.assertEqual(outcome, artwork.ArtworkOutcome.UNAVAILABLE)
        self.assertEqual(audio.read_bytes(), b"audio")
