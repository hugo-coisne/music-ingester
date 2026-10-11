#!/usr/bin/env python3
"""Daily stdlib-only backup runner, sharing the watch worker's filesystem lock."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import time
import uuid


@contextmanager
def lock(path, timeout=600):
    deadline = time.monotonic() + timeout
    with path.open('a+b') as stream:
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Music worker still holds the backup lock') from None
                time.sleep(1)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', type=Path, default=Path('backup-settings.json'))
    parser.add_argument('--restore-check', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    config = json.loads(args.settings.read_text())
    # The deployed copy of the existing backup implementation lives beside this
    # script; local development uses the exact same source in music_ingest.
    module_path = Path(__file__).resolve().with_name('backup.py')
    if not module_path.is_file():
        module_path = Path(__file__).resolve().parent.parent / 'music_ingest/backup.py'
    spec = importlib.util.spec_from_file_location('music_backup', module_path)
    backup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backup)
    root = Path(config['destination'])
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < config.get('min_free_bytes', 2 * 1024 ** 3):
        raise RuntimeError('Insufficient backup space')
    name = datetime.now(timezone.utc).strftime('auto-%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8]
    with lock(Path(config['lock_file'])):
        manifest = backup.snapshot(root / name, [Path(p) for p in config['databases']],
                                   [Path(p) for p in config['configs']])
    if args.restore_check:
        backup.restore(root / name, root / (name + '-restore-check'))
    print(json.dumps(dict(backup=str(root / name), verified_files=len(manifest['files']),
                          restore_checked=args.restore_check)))


if __name__ == '__main__':
    main()
