"""Shared data contracts; external API dictionaries stay at the boundary."""

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Protocol, TypedDict

# ytmusicapi responses have optional fields that vary with the source content.
APIData = dict[str, Any]


class MusicClient(Protocol):
    def get_playlist(self, playlist_id: str, limit: int | None = None) -> APIData:
        ...

    def get_album(self, album_id: str) -> APIData:
        ...


class TrackMetadata(TypedDict):
    title: str
    artists: list[str]
    album: str | None
    album_id: str | None
    year: str | int | None
    track_number: int | None
    track_total: int | None
    album_artist: str | None


class LibraryItem(TypedDict):
    path: Path
    title: str
    artists: list[str]
    duration: float


class DuplicateMatch(LibraryItem):
    duration_delta: float


class Artwork(TypedDict):
    url: str
    source: str


LibraryIndex = dict[str, list[LibraryItem]]


@dataclass
class SyncSummary:
    imported: int = 0
    existing: int = 0
    new: int = 0
    failed: int = 0
    skipped: int = 0
    artwork_warnings: int = 0

    @property
    def exit_code(self) -> int:
        return 1 if self.failed else 0

    def format(self, preview: bool = False) -> str:
        label = "Preview" if preview else "Summary"
        counts = ", ".join(f"{field.name}={getattr(self, field.name)}" for field in fields(self))
        return f"{label}: {counts}"
