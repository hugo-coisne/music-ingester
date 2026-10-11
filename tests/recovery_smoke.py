"""Real recovery exercise using only a recognized synthetic Navidrome lab."""
import argparse
import json
from pathlib import Path
import sys
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from music_ingest import backup, history, recovery


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lab', type=Path, default=Path('artifacts/navidrome-lab-v2'))
    parser.add_argument('--work', type=Path, required=True, help='New exercise folder')
    parser.add_argument('--port', type=int, default=15436)
    args = parser.parse_args()
    lab, work = args.lab.resolve(), args.work.resolve()
    marker = json.loads((lab / 'lab.json').read_text())
    if marker.get('version') != 1 or marker.get('root') != str(lab):
        raise ValueError('Expected synthetic lab marker')
    if lab == work or lab in work.parents or work in lab.parents:
        raise ValueError('Exercise must be separate from lab')
    work.mkdir(parents=True, mode=0o700, exist_ok=False)
    with history.import_lock(lab / 'state/watch.db'):
        backup.snapshot(work / 'backup', [lab / 'data/navidrome.db', lab / 'state/watch.db'],
                        [lab / 'credentials.json', lab / 'watch.toml', lab / 'compose.json']
                        + sorted((lab / 'music/playlists').glob('*.nsp')))
    config = work / 'recovery.local.json'
    config.write_text(json.dumps(dict(backup='backup', destination='restored',
                                     music=str(lab / 'music'), port=args.port), indent=2))
    before = backup.verify(work / 'backup')
    preview = recovery.run(config)
    if (work / 'restored').exists() or preview['status'] != 'preview':
        raise AssertionError('Preview changed filesystem')
    # Exercise the actual one-command CLI, not just its Python implementation.
    subprocess.run([sys.executable, '-m', 'music_ingest', 'recover', '--config',
                    str(config), '--apply'], check=True)
    report = json.loads((work / 'restored/recovery-result.json').read_text())
    if backup.verify(work / 'restored/archive') != before:
        raise AssertionError('Archive changed during restore')
    # Journal ownership tokens survive exactly; no worker is activated on the copy.
    watch = next(r for r in before['files'] if Path(r['source']).name == 'watch.db')
    if backup.digest(work / 'restored/archive' / watch['file']) != watch['sha256']:
        raise AssertionError('Watch ownership journal differs')
    subprocess.run(['docker', 'compose', '-f', str(work / 'restored/compose.json'), 'stop'], check=True)
    print(json.dumps(dict(report, exercise_instance_stopped=True), indent=2))


if __name__ == '__main__':
    main()
