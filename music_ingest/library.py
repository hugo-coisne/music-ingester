"""Read audio tags and identify existing recordings conservatively."""

import re
import unicodedata
from pathlib import Path

from mutagen import File as MutagenFile

from .metadata import artist_names
from .models import APIData, DuplicateMatch, LibraryIndex, LibraryItem

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".flac", ".ogg", ".opus", ".wav"}
DURATION_TOLERANCE_SECONDS = 4


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    unaccented = "".join(char for char in decomposed if not unicodedata.combining(char))
    unpunctuated = re.sub(r"[^\w\s]", " ", unaccented.lower())
    return re.sub(r"\s+", " ", unpunctuated).strip()


def title_without_feat(title: str) -> str:
    return re.sub(
        r"\s*[\(\[]\s*(?:feat\.?|ft\.?|featuring)\s+.*?[\)\]]",
        "", title, flags=re.IGNORECASE,
    ).strip()


def title_keys(title: str) -> set[str]:
    return {normalize_text(title), normalize_text(title_without_feat(title))} - {""}


def index_audio_file(path: Path) -> LibraryItem | None:
    """Skip unreadable/untagged files rather than guessing their identity."""
    try:
        audio = MutagenFile(path, easy=True)
        if not audio or not audio.tags or not audio.info:
            return None
        titles = audio.tags.get("title", [])
        artists = audio.tags.get("artist", [])
        if not titles or not artists:
            return None
        return {
            "path": path,
            "title": titles[0],
            "artists": artists,
            "duration": float(audio.info.length),
        }
    except Exception:
        return None


def add_to_library_index(index: LibraryIndex, item: LibraryItem) -> None:
    for key in title_keys(item["title"]):
        index.setdefault(key, []).append(item)


def build_library_index(*roots: Path) -> LibraryIndex:
    index: LibraryIndex = {}
    count = 0
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            item = index_audio_file(path)
            if item:
                add_to_library_index(index, item)
                count += 1
    print(f"Library index: {count} audio files")
    return index


def artists_match(track: APIData, library_item: LibraryItem) -> bool:
    # Whole artist tags only: Air must not match Air Supply.
    requested = {normalize_text(name) for name in artist_names(track)}
    existing = {normalize_text(name) for name in library_item["artists"]}
    return bool((requested & existing) - {""})


def find_existing_track(track: APIData, library_index: LibraryIndex) -> DuplicateMatch | None:
    # Duration is mandatory evidence, even when title and artist match exactly.
    try:
        duration = float(track.get("duration_seconds"))
    except (TypeError, ValueError):
        return None

    checked: set[Path] = set()
    for key in title_keys(track.get("title") or ""):
        for item in library_index.get(key, []):
            path = item["path"]
            if path in checked or not path.is_file():
                continue
            checked.add(path)
            if not artists_match(track, item):
                continue
            delta = abs(item["duration"] - duration)
            if delta <= DURATION_TOLERANCE_SECONDS:
                return {**item, "duration_delta": delta}
    return None
