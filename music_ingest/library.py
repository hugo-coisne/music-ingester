"""Read audio tags and identify existing recordings conservatively."""

import re
import unicodedata
from pathlib import Path

from mutagen import File as MutagenFile

from .metadata import artist_names
from . import identity
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
        isrc_value = (audio.tags.get('isrc') or [None])[0]
        if isrc_value is None and path.suffix.lower() == '.m4a':
            # EasyMP4 exposes MusicBrainz IDs but not the common freeform ISRC atom.
            from mutagen.mp4 import MP4
            values = MP4(path).get('----:com.apple.iTunes:ISRC', [])
            isrc_value = bytes(values[0]).decode('utf-8', errors='replace') if values else None
        return {
            "path": path,
            "title": titles[0],
            "artists": artists,
            "duration": float(audio.info.length),
            "recording_mbid": identity.mbid((audio.tags.get('musicbrainz_trackid') or [None])[0]),
            "isrc": identity.isrc(isrc_value),
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
    requested_mbid = identity.mbid(track.get('recording_mbid'))
    requested_isrc = identity.isrc(track.get('isrc'))
    if requested_mbid or requested_isrc:
        checked_ids = set()
        for items in library_index.values():
            for item in items:
                if item['path'] in checked_ids or not item['path'].is_file():
                    continue
                checked_ids.add(item['path'])
                # Conflicting recording IDs are stronger evidence than text/ISRC.
                if requested_mbid and item.get('recording_mbid') and requested_mbid != item['recording_mbid']:
                    continue
                strong = (requested_mbid and requested_mbid == item.get('recording_mbid')) or (
                    requested_isrc and requested_isrc == item.get('isrc'))
                if strong:
                    supplied = track.get('duration_seconds')
                    try:
                        delta = abs(float(supplied) - item['duration']) if supplied is not None else 0.0
                    except (ValueError, TypeError):
                        continue
                    if delta <= DURATION_TOLERANCE_SECONDS:
                        return {**item, 'duration_delta': delta}
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
            if requested_mbid and item.get('recording_mbid') and requested_mbid != item['recording_mbid']:
                continue
            if requested_isrc and item.get('isrc') and requested_isrc != item['isrc']:
                continue
            if not artists_match(track, item):
                continue
            delta = abs(item["duration"] - duration)
            if delta <= DURATION_TOLERANCE_SECONDS:
                return {**item, "duration_delta": delta}
    return None
