"""Organize completed audio and publish it without replacing existing files."""

import os
import shutil
import tempfile
from itertools import count
from pathlib import Path

from .config import LIBRARY_DIR
from .models import TrackMetadata


def safe_filename(value: str) -> str:
    value = value.replace("/", "／").replace("\0", "")
    return value.strip().strip(".").strip() or "Unknown"


def library_destination(metadata: TrackMetadata, extension: str, library_dir: Path) -> Path:
    """Compute the preferred location without creating directories."""
    artist = metadata["album_artist"] or metadata["artists"][0]
    album = metadata["album"] or "Singles"
    title = safe_filename(metadata["title"])
    number = metadata["track_number"]
    filename = f"{number:02d} - {title}{extension}" if number else f"{title}{extension}"
    return library_dir / safe_filename(artist) / safe_filename(album) / filename


def _claim_destination(temporary: Path, preferred: Path, video_id: str) -> Path:
    """An exclusive hard link arbitrates collisions, including concurrent writers."""
    for attempt in count():
        if attempt == 0:
            destination = preferred
        else:
            counter = "" if attempt == 1 else f" ({attempt})"
            filename = f"{preferred.stem} [{safe_filename(video_id)}]{counter}{preferred.suffix}"
            destination = preferred.with_name(filename)
        try:
            os.link(temporary, destination)
            return destination
        except FileExistsError:
            continue


def move_to_library(
    filepath: Path, metadata: TrackMetadata, video_id: str, library_dir: Path = LIBRARY_DIR,
) -> Path:
    """Publish a complete copy on the destination filesystem, then remove staging."""
    preferred = library_destination(metadata, filepath.suffix, library_dir)
    preferred.parent.mkdir(parents=True, exist_ok=True)

    # Copy on the destination filesystem so publication is atomic even when the
    # staging and library directories reside on different devices.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=preferred.parent, prefix=".ingest-", delete=False,
        ) as output:
            temporary = Path(output.name)
            with filepath.open("rb") as source:
                shutil.copyfileobj(source, output)
            output.flush()
            os.fsync(output.fileno())
        shutil.copystat(filepath, temporary)
        destination = _claim_destination(temporary, preferred, video_id)
        filepath.unlink()
        return destination
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
