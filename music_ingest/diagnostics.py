"""Manual read-only commands for inspecting playlist metadata and artwork."""

import argparse

from ytmusicapi import YTMusic

from .catalog import AlbumCache
from .metadata import artist_string
from .models import APIData


def _playlist_id(description: str, argv: list[str] | None) -> str:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("playlist_id")
    return parser.parse_args(argv).playlist_id


def playlist_main(argv: list[str] | None = None) -> None:
    playlist_id = _playlist_id("List tracks in a YouTube Music playlist.", argv)
    playlist = YTMusic().get_playlist(playlist_id, limit=None)
    tracks = playlist.get("tracks") or []
    print(f"Playlist: {playlist.get('title')}")
    print(f"{len(tracks)} tracks\n")
    for track in tracks:
        print(f"{track.get('videoId')} | {artist_string(track)} - {track.get('title')}")


def _print_thumbnails(thumbnails: list[APIData]) -> None:
    for thumbnail in thumbnails:
        print(f"  {thumbnail.get('width')}x{thumbnail.get('height')} {thumbnail.get('url')}")


def artwork_main(argv: list[str] | None = None) -> None:
    playlist_id = _playlist_id("Inspect playlist artwork sources.", argv)
    client = YTMusic()
    albums = AlbumCache(client)
    playlist = client.get_playlist(playlist_id, limit=None)
    for track in playlist.get("tracks") or []:
        print("\n" + "=" * 80)
        print(artist_string(track), "-", track.get("title"))
        print("videoId:", track.get("videoId"))
        print("album:", track.get("album"))
        print("\nTRACK THUMBNAILS:")
        _print_thumbnails(track.get("thumbnails") or [])
        album_info = albums.get_for_track(track)
        if album_info:
            print("\nALBUM:", album_info.get("title"))
            print("\nALBUM THUMBNAILS:")
            _print_thumbnails(album_info.get("thumbnails") or [])
