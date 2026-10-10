"""Discovery defaults to simulation; --apply persists suggestions, never downloads."""
import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import sys
import sqlite3

from ..config import load_document
from ..library import build_library_index
from ..history import import_lock
from .core import collect, latest, save
from .providers import LastFM, ListenBrainz, LocalLibrary


def lastfm_key(settings: dict, root: Path) -> str:
    value = os.environ.get('LASTFM_API_KEY', '')
    if value or not settings.get('api_key_file'):
        return value
    path = root / settings['api_key_file']
    if not path.exists():
        return ''
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError('API key file must be a private regular file (0600)')
    if path.stat().st_size > 4096:
        raise ValueError('API key file too large')
    return path.read_text().strip()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('discovery.toml'))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='Persist report in SQLite only')
    mode.add_argument('--dry-run', action='store_true', help='Default: no filesystem writes')
    mode.add_argument('--status', action='store_true', help='Read last report without calling providers')
    args = parser.parse_args(argv)
    try:
        if not args.config.is_file():
            parser.error('Discovery config not found; copy discovery.example.toml')
        config = load_document(args.config)
        if set(config) - {'storage', 'lastfm', 'listenbrainz', 'local', 'ranking'}:
            raise ValueError('Unknown Discovery section')
        root = args.config.resolve().parent
        path = (root / config['storage']['db_path']).resolve()
        if path.name in {'ingest.db', 'navidrome.db'}:
            raise ValueError('Discovery needs its own SQLite database')
        if args.status:
            report = latest(path)
        else:
            libraries = [(root / value).resolve() for value in config['storage'].get('libraries', [])]
            if any(path == p or p in path.parents for p in libraries):
                raise ValueError('Discovery database cannot be inside a music library')
            # Separate cycle lock covers provider reads too, while save() retains
            # its own database lock for callers using the Python API directly.
            with import_lock(path.with_name(path.name + '.cycle'), read_only=not args.apply):
                with redirect_stdout(sys.stderr):
                    index = build_library_index(*libraries)
                providers = []
                lastfm = config.get('lastfm', {})
                if lastfm.get('enabled', False):
                    providers.append(LastFM(lastfm['username'], lastfm_key(lastfm, root)))
                listenbrainz = config.get('listenbrainz', {})
                if listenbrainz.get('enabled', False):
                    providers.append(ListenBrainz(listenbrainz['username']))
                local = config.get('local', {})
                if local.get('enabled', False):
                    providers.append(LocalLibrary(index, local.get('seed_artists', [])))
                ranking = config.get('ranking', {})
                report = collect(providers, index, weights=ranking.get('weights'),
                                 blocked_artists=ranking.get('blocked_artists', []),
                                 blocked_tracks=ranking.get('blocked_tracks', []),
                                 limit=ranking.get('limit', 25))
                if args.apply:
                    save(path, report)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1 if report.get('errors') else 0
    except (ValueError, OSError, KeyError, TypeError, RuntimeError, sqlite3.Error) as exc:
        # Configuration errors should not dump secret-bearing values either.
        parser.exit(2, f'Discovery configuration/state error: {type(exc).__name__}\n')


if __name__ == '__main__':
    raise SystemExit(main())
