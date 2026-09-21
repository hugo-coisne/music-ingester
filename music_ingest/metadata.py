"""Translate catalog data into M4A tags, independently of network access."""

from pathlib import Path

from mutagen.mp4 import MP4, MP4FreeForm

from .models import APIData, TrackMetadata


def artist_names(track: APIData) -> list[str]:
    return [artist["name"] for artist in track.get("artists") or [] if artist.get("name")]


def artist_string(track: APIData) -> str:
    return ", ".join(artist_names(track))


def build_track_metadata(track: APIData, album_info: APIData | None) -> TrackMetadata:
    """Use playlist values as the baseline and enrich them with album information."""
    album = track.get("album") or {}
    metadata: TrackMetadata = {
        "title": track.get("title") or "Unknown",
        "artists": artist_names(track) or ["Unknown Artist"],
        "album": album.get("name"),
        "album_id": album.get("id"),
        "year": None,
        "track_number": None,
        "track_total": None,
        "album_artist": None,
    }
    if not album_info:
        return metadata

    metadata["year"] = album_info.get("year")
    album_artists = album_info.get("artists") or []
    if album_artists:
        metadata["album_artist"] = album_artists[0].get("name")

    tracks = album_info.get("tracks") or []
    metadata["track_total"] = len(tracks) or None
    for number, album_track in enumerate(tracks, start=1):
        if album_track.get("videoId") == track.get("videoId"):
            metadata["track_number"] = number
            break
    return metadata


def write_metadata(filepath: Path, metadata: TrackMetadata, video_id: str) -> None:
    audio = MP4(filepath)
    audio["\xa9nam"] = [metadata["title"]]
    audio["\xa9ART"] = metadata["artists"]
    if metadata["album"]:
        audio["\xa9alb"] = [metadata["album"]]
    if metadata["album_artist"]:
        audio["aART"] = [metadata["album_artist"]]
    if metadata["year"]:
        audio["\xa9day"] = [str(metadata["year"])]
    if metadata["track_number"]:
        audio["trkn"] = [(metadata["track_number"], metadata["track_total"] or 0)]
    audio["----:com.apple.iTunes:YOUTUBE_VIDEO_ID"] = [MP4FreeForm(video_id.encode("utf-8"))]
    if metadata["album_id"]:
        audio["----:com.apple.iTunes:YTMUSIC_ALBUM_ID"] = [
            MP4FreeForm(metadata["album_id"].encode("utf-8"))
        ]
    audio.save()
