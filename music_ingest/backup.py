"""Portable, verified backups. Restore only into a newly created directory.

This module also runs as a standalone stdlib-only script on the server.
Configuration copies can contain secrets: keep the entire backup private.
"""

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def check_database(path: Path) -> None:
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError(f'SQLite integrity failed: {path.name}')


def snapshot(destination: Path, databases: list[Path], configs: list[Path]) -> dict:
    sources = [(p, 'sqlite') for p in databases] + [(p, 'config') for p in configs]
    for source, _ in sources:
        if not source.is_file():
            raise ValueError(f'Missing source: {source}')
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    records = []
    for index, (source, kind) in enumerate(sources):
        name = f'{index:03d}-{source.name}'
        target = destination / name
        # Exclusive creation with private permissions, including during backup.
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        if kind == 'sqlite':
            deadline = time.monotonic() + 60

            def progress(*_):
                if time.monotonic() > deadline:
                    raise TimeoutError('SQLite backup exceeded 60 seconds')

            with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as db:
                with closing(sqlite3.connect(target)) as saved:
                    db.backup(saved, pages=256, progress=progress)
            check_database(target)
        else:
            shutil.copyfile(source, target)
        with target.open('rb') as stream:
            os.fsync(stream.fileno())
        records.append(dict(source=str(source.resolve()), file=name, kind=kind,
                            bytes=target.stat().st_size, sha256=digest(target)))
    manifest = dict(version=1, files=records)
    with (destination / 'manifest.json').open('x') as stream:
        json.dump(manifest, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    verify(destination)
    return manifest


def verify(directory: Path) -> dict:
    manifest = json.loads((directory / 'manifest.json').read_text())
    if manifest.get('version') != 1 or not isinstance(manifest.get('files'), list):
        raise ValueError('Unsupported backup manifest')
    seen = set()
    for record in manifest['files']:
        name = record['file']
        if (not isinstance(name, str) or name in {'', '.', '..', 'manifest.json'}
                or Path(name).name != name or name in seen):
            raise ValueError('Unsafe or duplicate backup filename')
        seen.add(name)
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Backup entry must be a regular file')
        if path.stat().st_size != record['bytes'] or digest(path) != record['sha256']:
            raise ValueError(f'Checksum mismatch: {name}')
        if record['kind'] == 'sqlite':
            check_database(path)
        elif record['kind'] != 'config':
            raise ValueError('Unsupported backup entry')
    return manifest


def restore(source: Path, destination: Path) -> dict:
    manifest = verify(source)
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    # Never use source paths in the manifest as restore destinations.
    for record in manifest['files']:
        target = destination / record['file']
        with target.open('xb') as stream, (source / record['file']).open('rb') as saved:
            os.chmod(target, 0o600)
            shutil.copyfileobj(saved, stream)
            stream.flush()
            os.fsync(stream.fileno())
    with (destination / 'manifest.json').open('x') as stream:
        json.dump(manifest, stream, indent=2)
    return verify(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('create')
    create.add_argument('destination', type=Path)
    create.add_argument('--database', type=Path, action='append', default=[])
    create.add_argument('--config-file', type=Path, action='append', default=[])
    inspect = sub.add_parser('verify')
    inspect.add_argument('source', type=Path)
    recover = sub.add_parser('restore')
    recover.add_argument('source', type=Path)
    recover.add_argument('destination', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'create':
            if not args.database and not args.config_file:
                parser.error('At least one source is required')
            result = snapshot(args.destination, args.database, args.config_file)
        elif args.command == 'verify':
            result = verify(args.source)
        else:
            result = restore(args.source, args.destination)
        print(json.dumps(dict(result='ok', files=len(result['files']))))
        return 0
    except (OSError, ValueError, KeyError, sqlite3.Error, TimeoutError) as exc:
        parser.exit(1, f'Backup failed: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
