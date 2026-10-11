"""Restore Navidrome into a new isolated Compose project from a verified backup."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import time

import requests

from . import backup
from .subsonic import Subsonic, credentials

IMAGE = 'deluan/navidrome:0.64.0@sha256:a384948b81bd1529986c5960169e7fc4fa00f46bde6bd517971a4c36671db2af'
PRESERVED = {'user': 'id,user_name,password,is_admin', 'user_props': '*',
             'annotation': '*', 'playlist': 'id,name,comment,public,owner_id,rules',
             'playlist_tracks': '*', 'media_file': 'id,path',
             'scrobbles': '*', 'scrobble_buffer': '*'}


def signatures(path):
    """Compare persistent identity/content, excluding login and evaluation timestamps."""
    result = {}
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        for table, fields in PRESERVED.items():
            cursor = db.execute(f'SELECT {fields} FROM {table}')
            count = len(cursor.description)
            digest, rows = hashlib.sha256(), 0
            for row in db.execute(f'SELECT {fields} FROM {table} ORDER BY ' +
                                  ','.join(str(i + 1) for i in range(count))):
                values = [v.hex() if isinstance(v, bytes) else v for v in row]
                digest.update((json.dumps(values, ensure_ascii=True) + '\n').encode())
                rows += 1
            result[table] = dict(rows=rows, sha256=digest.hexdigest())
    return result


def choose(manifest, explicit, names, kind):
    records = [r for r in manifest['files'] if r['kind'] == kind and
               (r['file'] == explicit if explicit else Path(r['source']).name in names)]
    if len(records) != 1:
        raise ValueError('Backup entry missing or ambiguous; select its exact manifest filename')
    return records[0]


def inspect(config_path):
    cfg = json.loads(config_path.read_text())
    if set(cfg) - {'backup', 'destination', 'music', 'port', 'database_entry', 'credentials_entry'}:
        raise ValueError('Unknown recovery setting')
    root = config_path.resolve().parent
    paths = {k: (root / cfg[k]).resolve() for k in ('backup', 'destination', 'music')}
    source, dest, music = (paths[k] for k in ('backup', 'destination', 'music'))
    port = cfg.get('port', 15436)
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('Invalid local port')
    if dest.exists() or (root / cfg['destination']).is_symlink():
        raise ValueError('Recovery requires a new destination')
    for protected in (source, music):
        if protected == dest or protected in dest.parents or dest in protected.parents:
            raise ValueError('Recovery destination overlaps backup or music')
    if not music.is_dir():
        raise ValueError('Music directory is unavailable; audio is not included in database backups')
    manifest = backup.verify(source)
    database = choose(manifest, cfg.get('database_entry'), {'navidrome.db'}, 'sqlite')
    credential = choose(manifest, cfg.get('credentials_entry'),
                        {'navidrome-credentials.json', 'credentials.json'}, 'config')
    # Validate shape and private permissions without exposing credentials.
    credentials(source / credential['file'])
    original_data = Path(database['source']).parent
    if original_data == dest or original_data in dest.parents or dest in original_data.parents:
        raise ValueError('Recovery destination overlaps original Navidrome data')
    available = 0
    with closing(sqlite3.connect((source / database['file']).as_uri() + '?mode=ro')) as db:
        libraries = db.execute('SELECT path FROM library').fetchall()
        if libraries != [('/music',)]:
            raise ValueError('This recovery supports one library mounted at /music')
        for (relative,) in db.execute('SELECT path FROM media_file'):
            path = Path(relative)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('Unsupported or unsafe stored music path')
            target = (music / path).resolve()
            if music not in target.parents or not target.is_file():
                raise ValueError('A catalog file is missing or outside the music root')
            available += 1
    before = signatures(source / database['file'])
    return dict(paths=paths, port=port, manifest=manifest, database=database,
                credential=credential, before=before, available=available)


def compose_spec(dest, music, port):
    return dict(name='home-music-recovery-' + hashlib.sha256(str(dest).encode()).hexdigest()[:10],
        services={'navidrome': dict(image=IMAGE, user=f'{os.getuid()}:{os.getgid()}', restart='no',
            read_only=True, cap_drop=['ALL'], security_opt=['no-new-privileges:true'],
            mem_limit='768m', cpus=1.0, pids_limit=128,
            ports=[f'127.0.0.1:{port}:4533'], tmpfs=['/tmp:size=128m'],
            environment=dict(ND_DATAFOLDER='/data', ND_MUSICFOLDER='/music',
                ND_CONFIGFILE='/data/recovery.toml', ND_SCANNER_ENABLED='false',
                ND_ENABLEEXTERNALSERVICES='false', ND_LASTFM_ENABLED='false',
                ND_LISTENBRAINZ_ENABLED='false', ND_PLUGINS_ENABLED='false',
                ND_ENABLEINSIGHTSCOLLECTOR='false', ND_ENABLEGRAVATAR='false',
                ND_ENABLESHARING='false', ND_ENABLELOGREDACTING='true'),
            volumes=[dict(type='bind', source=str(dest / 'data').replace('$', '$$'), target='/data',
                          bind={'create_host_path': False}),
                     dict(type='bind', source=str(music).replace('$', '$$'), target='/music', read_only=True,
                          bind={'create_host_path': False})],
            logging=dict(driver='json-file', options={'max-size': '5m', 'max-file': '2'}))})


def write_private(path, value):
    with path.open('x') as stream:
        os.chmod(path, 0o600)
        stream.write(value)


def prepare(plan):
    paths = plan['paths']
    dest = paths['destination']
    # Reserve space for archive, working database, WAL and temporary startup writes.
    ancestor = dest.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    required = sum(r['bytes'] for r in plan['manifest']['files']) + plan['database']['bytes'] + 512 * 1024 ** 2
    if shutil.disk_usage(ancestor).free < required:
        raise ValueError('Insufficient recovery disk space')
    dest.mkdir(mode=0o700, parents=True, exist_ok=False)
    backup.restore(paths['backup'], dest / 'archive')
    (dest / 'data').mkdir(mode=0o700)
    for name, record in [('navidrome.db', plan['database']), ('credentials.json', plan['credential'])]:
        target = dest / 'data/navidrome.db' if name == 'navidrome.db' else dest / name
        with target.open('xb') as out, (dest / 'archive' / record['file']).open('rb') as saved:
            os.chmod(target, 0o600)
            shutil.copyfileobj(saved, out)
        if backup.digest(target) != record['sha256']:
            raise ValueError('Recovered file differs from verified archive')
    # Retain old configurations in archive; do not execute their network/plugin settings.
    write_private(dest / 'data/recovery.toml', '# Isolated recovery; settings supplied by Compose.\n')
    write_private(dest / 'compose.json', json.dumps(compose_spec(dest, paths['music'], plan['port']), indent=2))
    write_private(dest / 'recovery-plan.json', json.dumps(dict(image=IMAGE, port=plan['port'],
        music=str(paths['music']), preserved=plan['before'], backup_files=len(plan['manifest']['files'])), indent=2))
    return dest


def verify_running(plan, dest):
    url = f"http://127.0.0.1:{plan['port']}"
    session = requests.Session()
    session.trust_env = False
    deadline = time.monotonic() + 45
    while True:
        try:
            if session.get(url + '/ping', timeout=2).status_code == 200:
                break
        except requests.RequestException:
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError('Recovered instance did not become ready')
        time.sleep(1)
    backup.check_database(dest / 'data/navidrome.db')
    if signatures(dest / 'data/navidrome.db') != plan['before']:
        raise ValueError('Preserved accounts, annotations, playlists or catalog differ after startup')
    auth = credentials(dest / 'credentials.json')
    api = Subsonic(url, **auth, session=session, catalog_db=dest / 'data/navidrome.db')
    api.call('ping')
    files = api.catalog(plan['paths']['music'])
    if not files:
        raise ValueError('No playable file accessible to the validation account')
    path, sid = next(iter(files.items()))
    salt = secrets.token_hex(16)
    token = hashlib.md5((auth['password'] + salt).encode()).hexdigest()
    with session.post(url + '/rest/stream', data=dict(u=auth['username'], t=token, s=salt,
            v='1.16.1', c='home-music-recovery', id=sid, format='raw'), timeout=(5, 20),
            allow_redirects=False, stream=True) as response:
        if response.status_code != 200:
            raise RuntimeError('Recovered audio stream unavailable')
        block = next(response.iter_content(16384), b'')
        with path.open('rb') as original:
            if not block or block != original.read(len(block)):
                raise ValueError('Recovered stream differs from source file')
    return dict(status='verified', url=url, backup_files=len(plan['manifest']['files']),
                catalog_files=plan['available'], api_visible_files=len(files), stream_verified=True,
                preserved_rows={k: v['rows'] for k, v in plan['before'].items()},
                worker_enabled=False, external_services_enabled=False)


def run(config_path, apply=False):
    plan = inspect(config_path)
    if not apply:
        return dict(status='preview', catalog_files=plan['available'],
                    backup_files=len(plan['manifest']['files']), port=plan['port'], image=IMAGE)
    # Fail before creating state for a port already in use. Compose also detects races.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', plan['port']))
    project = compose_spec(plan['paths']['destination'], plan['paths']['music'], plan['port'])['name']
    existing = subprocess.run(['docker', 'ps', '-aq', '--filter',
                               'label=com.docker.compose.project=' + project],
                              check=True, timeout=30, capture_output=True, text=True)
    if existing.stdout.strip():
        raise ValueError('A container already belongs to this recovery project')
    dest = prepare(plan)
    command = ['docker', 'compose', '-f', str(dest / 'compose.json')]
    try:
        subprocess.run(command + ['config', '--quiet'], check=True, timeout=30)
        subprocess.run(command + ['up', '-d', '--pull', 'missing'], check=True, timeout=180)
        report = verify_running(plan, dest)
    except (Exception, KeyboardInterrupt) as exc:
        # Stop only this new recovery project; retain every restored file for diagnosis.
        stopped = False
        try:
            stopped = subprocess.run(command + ['stop'], timeout=30, check=False).returncode == 0
        except (OSError, subprocess.SubprocessError):
            pass
        write_private(dest / 'recovery-result.json', json.dumps(dict(status='failed',
                      error=type(exc).__name__, stopped=stopped)))
        raise
    write_private(dest / 'recovery-result.json', json.dumps(report, indent=2))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run(args.config, args.apply), indent=2))
        return 0
    except Exception as exc:
        parser.exit(2, 'Recovery failed: ' + type(exc).__name__ + '\n')
