"""Prepare an isolated Navidrome data directory from a verified backup.

Run on the server from a checkout: python3 scripts/prepare_navidrome.py BACKUP NEW_DATA.
This prepares only files, never starts a service or modifies the source library.
"""
import argparse
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from music_ingest.backup import verify, check_database


def prepare(backup: Path, destination: Path) -> None:
    manifest = verify(backup)
    selected = {}
    for name in ('navidrome.db', 'navidrome.toml'):
        candidates = [r for r in manifest['files'] if Path(r['source']).name == name]
        if len(candidates) != 1:
            raise ValueError(f'Expected exactly one {name} in backup')
        selected[name] = backup / candidates[0]['file']
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, source in selected.items():
        target = destination / name
        with target.open('xb') as saved, source.open('rb') as stream:
            os.chmod(target, 0o600)
            shutil.copyfileobj(stream, saved)
    check_database(destination / 'navidrome.db')
    print('Prepared isolated Navidrome data; live data unchanged')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    prepare(args.backup, args.destination)
