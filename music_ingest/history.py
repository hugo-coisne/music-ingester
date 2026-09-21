"""SQLite import history; each status change is committed for retry recovery."""

import sqlite3
import fcntl
from contextlib import contextmanager, nullcontext
from pathlib import Path

from .config import DB_PATH

SCHEMA = """
    CREATE TABLE IF NOT EXISTS imports (
        video_id TEXT PRIMARY KEY,
        artist TEXT,
        title TEXT,
        status TEXT NOT NULL,
        local_path TEXT,
        error TEXT,
        imported_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
"""


@contextmanager
def import_lock(db_path: Path, read_only: bool = False):
    """Only one writer may process a database at a time."""
    if read_only:
        with nullcontext():
            yield
        return
    lock_path = db_path.with_suffix(db_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lockfile:
        try:
            fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"another sync is using {db_path}") from exc
        try:
            yield
        finally:
            fcntl.flock(lockfile, fcntl.LOCK_UN)


def connect_db(db_path: Path = DB_PATH, read_only: bool = False) -> sqlite3.Connection:
    """Preview uses an existing DB read-only, or an empty in-memory DB."""
    if read_only and db_path.exists():
        return sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    if read_only:
        db = sqlite3.connect(":memory:")
    else:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(db_path)
    try:
        db.execute(SCHEMA)
        db.commit()
    except Exception:
        db.close()
        raise
    return db


def mark_stage(
    db: sqlite3.Connection, video_id: str, status: str, local_path: Path | None = None,
) -> None:
    """Persist an in-flight stage so recovery can distinguish its last action."""
    if status not in {"downloaded", "processed", "publishing"}:
        raise ValueError(f"invalid import stage: {status}")
    with db:
        db.execute(
            "UPDATE imports SET status = ?, local_path = ? WHERE video_id = ?",
            (status, str(local_path) if local_path else None, video_id),
        )


def recover_published(db: sqlite3.Connection, library_dir: Path) -> int:
    """Reconcile interrupted imports using the video ID embedded in published audio."""
    rows = db.execute(
        "SELECT video_id FROM imports WHERE status IN "
        "('pending', 'downloaded', 'processed', 'publishing', 'error')"
    ).fetchall()
    wanted = {video_id for (video_id,) in rows}
    if not wanted or not library_dir.exists():
        return 0

    from mutagen.mp4 import MP4

    found: dict[str, Path] = {}
    for path in library_dir.rglob("*.m4a"):
        try:
            ids = MP4(path).get("----:com.apple.iTunes:YOUTUBE_VIDEO_ID", [])
            if ids:
                video_id = bytes(ids[0]).decode("utf-8")
                if video_id in wanted and video_id not in found:
                    found[video_id] = path
        except Exception:
            continue
    for video_id, path in found.items():
        mark_done(db, video_id, path)
    return len(found)


def existing_import(db: sqlite3.Connection, video_id: str) -> bool:
    row = db.execute(
        "SELECT status, local_path FROM imports WHERE video_id = ?", (video_id,)
    ).fetchone()
    if not row:
        return False
    status, local_path = row
    return status in ("done", "existing") and bool(local_path) and Path(local_path).is_file()


def mark_existing(
    db: sqlite3.Connection, video_id: str, artist: str, title: str, local_path: Path,
) -> None:
    with db:
        db.execute("""
            INSERT INTO imports (video_id, artist, title, status, local_path)
            VALUES (?, ?, ?, 'existing', ?)
            ON CONFLICT(video_id) DO UPDATE SET
                artist = excluded.artist,
                title = excluded.title,
                status = 'existing',
                local_path = excluded.local_path,
                error = NULL
        """, (video_id, artist, title, str(local_path)))


def mark_pending(db: sqlite3.Connection, video_id: str, artist: str, title: str) -> None:
    with db:
        db.execute("""
            INSERT INTO imports (video_id, artist, title, status)
            VALUES (?, ?, ?, 'pending')
            ON CONFLICT(video_id) DO UPDATE SET
                artist = excluded.artist,
                title = excluded.title,
                status = 'pending',
                local_path = NULL,
                error = NULL
        """, (video_id, artist, title))


def mark_done(db: sqlite3.Connection, video_id: str, path: Path) -> None:
    with db:
        db.execute("""
            UPDATE imports SET status = 'done', local_path = ?, error = NULL,
                imported_at = CURRENT_TIMESTAMP
            WHERE video_id = ?
        """, (str(path), video_id))


def mark_error(db: sqlite3.Connection, video_id: str, error: Exception) -> None:
    with db:
        db.execute("""
            UPDATE imports SET status = 'error', error = ? WHERE video_id = ?
        """, (str(error), video_id))
