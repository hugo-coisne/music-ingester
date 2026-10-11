"""Private orchestration journal and incremental tag cache; no audio deletion."""
import json
from pathlib import Path
import sqlite3

from . import library

APPLICATION_ID = 0x484D5731


def connect(path, readonly=False):
    if readonly:
        db = sqlite3.connect(':memory:')
        if path.is_file():
            source = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
            try:
                source.backup(db)
            finally:
                source.close()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path)
    if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone() and (
        db.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID
    ):
        db.close()
        raise ValueError('Not a watch database')
    db.execute(f'PRAGMA application_id={APPLICATION_ID}')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS mirrors(source TEXT PRIMARY KEY, token TEXT NOT NULL,
                                          playlist_id TEXT);
        CREATE TABLE IF NOT EXISTS playlist_backups(id INTEGER PRIMARY KEY,
            source TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS cache(path TEXT PRIMARY KEY,signature TEXT,payload TEXT);
        CREATE TABLE IF NOT EXISTS recommendation_http_cache(
            key TEXT PRIMARY KEY, stored REAL NOT NULL, payload TEXT NOT NULL, bytes INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs(source TEXT PRIMARY KEY,payload TEXT,updated REAL);
        CREATE TABLE IF NOT EXISTS queue(key TEXT PRIMARY KEY,track TEXT,attempts INTEGER DEFAULT 0,
            next_at REAL DEFAULT 0,status TEXT);
        CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY,report TEXT,
                                       created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    ''')
    return db


def cached_index(db, roots):
    index, seen = {}, set()
    for root in roots:
        if not root.is_dir():
            raise ValueError('Configured library is unavailable')
        for path in root.rglob('*'):
            if path.suffix.lower() not in library.AUDIO_EXTENSIONS or not path.is_file():
                continue
            path = path.resolve()
            if path in seen:
                continue
            seen.add(path)
            stat = path.stat()
            signature = f'{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}'
            row = db.execute('SELECT signature,payload FROM cache WHERE path=?', (str(path),)).fetchone()
            if row and row[0] == signature:
                item = json.loads(row[1])
                if item:
                    item['path'] = Path(item['path'])
            else:
                item = library.index_audio_file(path)
                db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)',
                           (str(path), signature, json.dumps(item, default=str)))
            if item:
                library.add_to_library_index(index, item)
    db.commit()
    return index
