"""Artwork policy and preservation of audio when optional embedding fails."""

from unittest.mock import patch

from PIL import Image

from music_ingest import artwork
from tests.support import TemporaryTest, track


class ArtworkTests(TemporaryTest):
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
