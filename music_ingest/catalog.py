"""Per-run album lookups shared by metadata and artwork processing."""

from .models import APIData, MusicClient


class AlbumCache:
    """Cache unsuccessful lookups too, so one unavailable album is requested once."""

    def __init__(self, client: MusicClient):
        self.client = client
        self._albums: dict[str, APIData | None] = {}

    def get_for_track(self, track: APIData) -> APIData | None:
        album_id = (track.get("album") or {}).get("id")
        if not album_id:
            return None
        if album_id not in self._albums:
            try:
                self._albums[album_id] = self.client.get_album(album_id)
            except Exception as exc:
                print(f"[WARN] album metadata: {exc}")
                self._albums[album_id] = None
        return self._albums[album_id]
