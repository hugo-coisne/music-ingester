"""Artwork selection, conservative cropping, and optional safe embedding."""

import io
import shutil
import tempfile
import time
from enum import Enum
from pathlib import Path

import requests
from mutagen.mp4 import MP4, MP4Cover
from PIL import Image, ImageStat

from .config import STAGING_DIR
from .models import APIData, Artwork

ARTWORK_TIMEOUT_SECONDS = 30
ARTWORK_DOWNLOAD_ATTEMPTS = 3
ARTWORK_RETRY_BACKOFF_SECONDS = 1
JPEG_QUALITY = 95
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


class ArtworkOutcome(Enum):
    UNAVAILABLE = "unavailable"
    EMBEDDED = "embedded"
    FAILED = "failed"


def best_thumbnail(thumbnails: list[APIData]) -> APIData | None:
    if not thumbnails:
        return None
    square = [
        thumb for thumb in thumbnails
        if thumb.get("width") and thumb.get("height")
        and abs(thumb["width"] - thumb["height"]) <= 2
    ]
    return max(square or thumbnails, key=lambda t: t.get("width", 0) * t.get("height", 0))


def choose_artwork(track: APIData, album_info: APIData | None) -> Artwork | None:
    """Prefer album art over the track's potentially rectangular video thumbnail."""
    if album_info:
        thumbnail = best_thumbnail(album_info.get("thumbnails") or [])
        if thumbnail:
            return {"url": thumbnail["url"], "source": "ytmusic_album"}
    thumbnail = best_thumbnail(track.get("thumbnails") or [])
    if thumbnail:
        return {"url": thumbnail["url"], "source": "youtube_thumbnail"}
    return None


def side_is_flat(image: Image.Image, threshold: float = 20) -> bool:
    return max(ImageStat.Stat(image).stddev) < threshold


def crop_artwork(image: Image.Image) -> tuple[Image.Image, str]:
    """Crop landscape images only when both discarded sidebars look flat."""
    width, height = image.size
    if width == height:
        return image, ":square"
    side_width = (width - height) // 2
    if side_width <= 0:
        return image, ""
    left = image.crop((0, 0, side_width, height))
    right = image.crop((width - side_width, 0, width, height))
    if side_is_flat(left) and side_is_flat(right):
        return image.crop((side_width, 0, side_width + height, height)), ":center-crop"
    return image, ":uncropped"


def download_artwork(url: str) -> bytes:
    """Retry transient transport/server failures without retrying permanent HTTP errors."""
    for attempt in range(ARTWORK_DOWNLOAD_ATTEMPTS):
        try:
            with requests.get(url, timeout=ARTWORK_TIMEOUT_SECONDS) as response:
                response.raise_for_status()
                return response.content
        except requests.RequestException as exc:
            status = exc.response.status_code if exc.response is not None else None
            transient = isinstance(exc, (requests.ConnectionError, requests.Timeout))
            transient = transient or status in RETRYABLE_HTTP_STATUS
            if not transient or attempt == ARTWORK_DOWNLOAD_ATTEMPTS - 1:
                raise
            time.sleep(ARTWORK_RETRY_BACKOFF_SECONDS * 2**attempt)
    raise RuntimeError("artwork retry loop ended unexpectedly")


def prepare_artwork(
    video_id: str, artwork: Artwork, staging_dir: Path = STAGING_DIR,
) -> tuple[Path, Path, str]:
    content = download_artwork(artwork["url"])
    with Image.open(io.BytesIO(content)) as source:
        image = source.convert("RGB")

    original_path = staging_dir / f"{video_id}.cover-original.jpg"
    cover_path = staging_dir / f"{video_id}.cover.jpg"
    image.save(original_path, "JPEG", quality=JPEG_QUALITY)
    processed, crop_status = crop_artwork(image)
    processed.save(cover_path, "JPEG", quality=JPEG_QUALITY)
    return cover_path, original_path, artwork["source"] + crop_status


def embed_artwork(audio_path: Path, cover_path: Path) -> None:
    audio = MP4(audio_path)
    audio["covr"] = [MP4Cover(cover_path.read_bytes(), imageformat=MP4Cover.FORMAT_JPEG)]
    audio.save()


def apply_artwork(
    track: APIData, album_info: APIData | None, filepath: Path, staging_dir: Path,
) -> ArtworkOutcome:
    """An optional artwork failure must never corrupt or reject usable audio."""
    temporary = None
    try:
        artwork = choose_artwork(track, album_info)
        if not artwork:
            return ArtworkOutcome.UNAVAILABLE
        cover_path, _, status = prepare_artwork(track["videoId"], artwork, staging_dir)
        with tempfile.NamedTemporaryFile(dir=staging_dir, suffix=".m4a", delete=False) as output:
            temporary = Path(output.name)
        shutil.copy2(filepath, temporary)
        embed_artwork(temporary, cover_path)
        temporary.replace(filepath)
        print(f"       artwork: {status}")
        return ArtworkOutcome.EMBEDDED
    except Exception as exc:
        print(f"[WARN] artwork skipped: {exc}")
        return ArtworkOutcome.FAILED
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
