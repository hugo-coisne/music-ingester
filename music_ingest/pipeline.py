"""Coordinate one playlist run; domain modules own the individual operations."""

import re
import sys
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from mutagen import File as MutagenFile

from . import artwork, download, history, library, metadata, publishing
from .catalog import AlbumCache
from .config import Config
from .fingerprint import FingerprintMatcher
from .models import APIData, MusicClient, SyncSummary, TrackMetadata


@dataclass(frozen=True)
class PreparedTrack:
    filepath: Path
    tags: TrackMetadata
    artwork_failed: bool


def prepare_track(
    track: APIData, filepath: Path, config: Config, albums: AlbumCache,
) -> PreparedTrack:
    """Tag downloaded audio; the caller validates and publishes it."""
    video_id = track["videoId"]
    album_info = albums.get_for_track(track)
    tags = metadata.build_track_metadata(track, album_info)
    metadata.write_metadata(filepath, tags, video_id)
    outcome = artwork.apply_artwork(track, album_info, filepath, config.staging_dir)

    return PreparedTrack(filepath, tags, artwork_failed=outcome is artwork.ArtworkOutcome.FAILED)


def run_sync(client: MusicClient, playlist_id: str, config: Config, list_only: bool = False) -> int:
    """Process a playlist, report counts, and return a shell-compatible exit code."""
    summary = SyncSummary()
    albums = AlbumCache(client)
    playlist = client.get_playlist(playlist_id, limit=None)
    tracks = playlist.get("tracks") or []
    library_index = library.build_library_index(*config.reference_libraries, config.library_dir)
    fingerprints = FingerprintMatcher(library_index)
    if not list_only:
        config.staging_dir.mkdir(parents=True, exist_ok=True)
        config.library_dir.mkdir(parents=True, exist_ok=True)

    print(f"Playlist: {playlist.get('title')} ({len(tracks)} tracks)")
    seen: set[str] = set()
    with history.import_lock(config.db_path, read_only=list_only), closing(
        history.connect_db(config.db_path, read_only=list_only)
    ) as db:
        if not list_only:
            recovered = history.recover_published(db, config.library_dir)
            if recovered:
                print(f"Recovered {recovered} published import(s) from interrupted runs")
        for track in tracks:
            video_id = track.get("videoId")
            if not video_id or not re.fullmatch(r"[A-Za-z0-9_-]+", video_id):
                summary.skipped += 1
                print(f"[SKIP] Missing or invalid videoId: {track.get('title')}")
                continue
            if video_id in seen:
                summary.skipped += 1
                continue
            seen.add(video_id)
            artist = metadata.artist_string(track)
            title = track.get("title") or "Unknown"
            display = f"{artist} - {title}"
            try:
                if history.existing_import(db, video_id):
                    summary.existing += 1
                    print(f"[OK]   {display}")
                    continue
                duplicate = library.find_existing_track(track, library_index)
                if duplicate:
                    if not list_only:
                        history.mark_existing(db, video_id, artist, title, duplicate["path"])
                    summary.existing += 1
                    print(f"[HAVE] {display} -> {duplicate['path']}")
                    continue
                summary.new += 1
                if list_only:
                    print(f"[NEW]  {display}")
                    continue

                print(f"[GET]  {display}")
                history.mark_pending(db, video_id, artist, title)
                filepath = download.resumable_download(video_id, config.staging_dir)
                if filepath:
                    print(f"[RESUME] {display} -> {filepath}")
                else:
                    filepath = download.download(
                        video_id, config.staging_dir, config.download_timeout,
                    )
                history.mark_stage(db, video_id, "downloaded", filepath)
                audio = MutagenFile(filepath)
                if not audio or not audio.info:
                    raise RuntimeError("Downloaded audio has no readable duration")
                duration = float(audio.info.length)
                acoustic_match = fingerprints.find(filepath, duration)
                if acoustic_match:
                    history.mark_existing(db, video_id, artist, title, acoustic_match)
                    filepath.unlink()
                    summary.existing += 1
                    print(f"[HAVE AUDIO] {display} -> {acoustic_match}")
                    continue
                source_fingerprint = fingerprints.value_for(filepath)
                result = prepare_track(track, filepath, config, albums)
                history.mark_stage(db, video_id, "processed", result.filepath)
                summary.artwork_warnings += int(result.artwork_failed)
                # Use actual tags/duration so in-run matches agree with future scans.
                item = library.index_audio_file(result.filepath)
                if not item:
                    raise RuntimeError("Downloaded audio could not be indexed after tagging")
                history.mark_stage(db, video_id, "publishing", result.filepath)
                item["path"] = publishing.move_to_library(
                    result.filepath, result.tags, video_id, config.library_dir,
                )
                library.add_to_library_index(library_index, item)
                fingerprints.add(item["path"], item["duration"], source_fingerprint)
                history.mark_done(db, video_id, item["path"])
                summary.imported += 1
                print(f"       -> {item['path']}")
            except Exception as exc:
                summary.failed += 1
                if not list_only:
                    history.mark_error(db, video_id, exc)
                print(f"[ERR]  {display}: {exc}", file=sys.stderr)

    print(summary.format(preview=list_only))
    return summary.exit_code
