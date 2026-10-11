"""Create a local, synthetic-only Navidrome lab; never mount existing media."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from music_ingest import watch_state
from music_ingest.subsonic import Subsonic, credentials, mirror
from music_ingest.radio import run as radio

IMAGE = 'deluan/navidrome:0.64.0@sha256:a384948b81bd1529986c5960169e7fc4fa00f46bde6bd517971a4c36671db2af'


def prepare(root, port):
    if not 1024 <= port <= 65535:
        raise ValueError('Invalid lab port')
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    for folder in ('data', 'music', 'state'):
        (root / folder).mkdir(mode=0o700)
    (root / 'music/Managed Singles').mkdir()
    (root / 'credentials.json').write_text(json.dumps(dict(username='lab', password=secrets.token_urlsafe(32))))
    (root / 'credentials.json').chmod(0o600)
    spec = dict(name='home-music-lab-' + hashlib.sha256(str(root).encode()).hexdigest()[:10],
                services={'navidrome': dict(image=IMAGE, user=f'{os.getuid()}:{os.getgid()}',
                    restart='no', read_only=True, cap_drop=['ALL'],
                    security_opt=['no-new-privileges:true'], mem_limit='384m', cpus=0.75,
                    ports=[f'127.0.0.1:{port}:4533'],
                    environment=dict(ND_MUSICFOLDER='/music', ND_DATAFOLDER='/data',
                        ND_ENABLEEXTERNALSERVICES='false', ND_LASTFM_ENABLED='false',
                        ND_LISTENBRAINZ_ENABLED='false', ND_ENABLEINSIGHTSCOLLECTOR='false',
                        ND_PLUGINS_ENABLED='false', ND_ENABLESHARING='false', ND_ENABLEGRAVATAR='false',
                        ND_SCANNER_ENABLED='true', ND_SCANSCHEDULE='0', ND_ENABLELOGREDACTING='true'),
                    volumes=[dict(type='bind', source=str(root / folder), target='/' + folder,
                                  read_only=folder == 'music', bind={'create_host_path': False})
                             for folder in ('data', 'music')], tmpfs=['/tmp:size=64m'],
                    logging=dict(driver='json-file', options={'max-size': '2m', 'max-file': '2'}))})
    (root / 'compose.json').write_text(json.dumps(spec, indent=2))
    for number in range(4):
        subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-n',
                        '-f', 'lavfi', '-i', f'sine=frequency={330 + 110 * number}:duration=8',
                        '-c:a', 'aac', '-metadata', f'title=Lab tone {number + 1}',
                        '-metadata', 'artist=Lab Artist' if number < 3 else 'artist=Other Artist',
                        '-metadata', 'album=Synthetic Lab', '-metadata',
                        'genre=Electronic' if number < 3 else 'genre=Jazz',
                        str(root / 'music' / ('Managed Singles' if number == 0 else '')
                            / f'tone-{number + 1}.m4a')], check=True)
    (root / 'watch.toml').write_text('state_db="state/watch.db"\n[navidrome]\nenabled=true\n'
        f'url="http://127.0.0.1:{port}"\ncredentials_file="credentials.json"\n'
        'music_root="music"\ncatalog_db="data/navidrome.db"\nlibrary_id=1\n')
    (root / 'lab.json').write_text(json.dumps(dict(version=1, root=str(root), port=port)))


def check(root, port):
    url = f'http://127.0.0.1:{port}'
    session = requests.Session()
    session.trust_env = False
    auth = credentials(root / 'credentials.json')
    api = Subsonic(url, **auth, session=session, catalog_db=root / 'data/navidrome.db')
    deadline = time.monotonic() + 45
    while True:
        try:
            if session.get(url + '/ping', timeout=2).status_code == 200:
                break
        except requests.RequestException:
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError('Lab startup timeout')
        time.sleep(1)
    # Version-specific bootstrap endpoint isolated to a fresh synthetic lab.
    response = session.post(url + '/auth/login', json=auth, timeout=10)
    if response.status_code != 200:
        response = session.post(url + '/auth/createAdmin', json=auth, timeout=10)
    if response.status_code != 200:
        raise RuntimeError('Lab account bootstrap failed')
    api.call('startScan')
    deadline = time.monotonic() + 45
    while True:
        files = api.catalog(root / 'music')
        if len(files) == 4:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError('Synthetic catalog did not finish scanning')
        time.sleep(1)
    with watch_state.connect(root / 'state/watch.db') as db:
        ids = list(files.values())
        first = mirror(api, db, 'lab:public', 'Lab Public Mirror', ids)
        pid = first['id']
        api.call('updatePlaylist', playlistId=pid, public='false')
        assert api.call('getPlaylist', id=pid)['playlist'].get('public', False) is False
        repaired = mirror(api, db, 'lab:public', 'Lab Public Mirror', ids)
        assert repaired['changed']
        assert api.call('getPlaylist', id=pid)['playlist']['public'] is True
        assert not mirror(api, db, 'lab:public', 'Lab Public Mirror', ids)['changed']
    db.close()
    smart = check_smart_playlists(api, root, files)
    seed_song = api.call('getSong', id=ids[0])['song']
    radios = {}
    for kind, seed in [('genre', 'Electronic'), ('artist', seed_song['artistId']), ('song', ids[0])]:
        first_radio = radio(root / 'watch.toml', kind, seed, apply=True)
        second_radio = radio(root / 'watch.toml', kind, seed, apply=True)
        assert first_radio['tracks'] and not second_radio['mirror']['changed']
        radios[kind] = len(first_radio['tracks'])
    path, sid = next(iter(files.items()))
    salt = secrets.token_hex(16)
    token = hashlib.md5((auth['password'] + salt).encode()).hexdigest()
    with session.post(url + '/rest/stream', data=dict(u=auth['username'], t=token, s=salt,
                      v='1.16.1', c='home-music-lab', id=sid, format='raw'), timeout=15) as response:
        assert response.status_code == 200
        assert response.content == path.read_bytes()
    proof = dict(url=url, tracks=len(files), public_mirror=True, repaired_private=True,
                 idempotent=True, streaming_bytes_verified=True, smart_playlists=smart, radios=radios)
    (root / 'proof.json').write_text(json.dumps(proof, indent=2))
    print(json.dumps(proof))


def check_smart_playlists(api, root, files):
    ids = list(files.values())
    api.call('star', id=ids[0])
    # Only synthetic listening history; all external scrobblers are disabled.
    api.call('scrobble', id=ids[1], time=int((time.time() - 100 * 86400) * 1000), submission='true')
    folder = root / 'music' / 'playlists'
    folder.mkdir(exist_ok=True)
    templates = Path(__file__).resolve().parents[1] / 'config/navidrome/playlists'
    expected = {}
    for source in templates.glob('*.nsp'):
        text = source.read_text()
        target = folder / source.name
        if target.exists():
            if target.read_text() != text:
                raise ValueError('Lab playlist template changed; use a fresh lab')
        else:
            with target.open('x') as stream:
                stream.write(text)
        expected[json.loads(text)['name']] = source.name
    api.call('startScan')
    deadline = time.monotonic() + 45
    while True:
        playlists = api.call('getPlaylists').get('playlists', {}).get('playlist', [])
        found = {p['name']: p for p in playlists if p['name'] in expected}
        if len(found) == len(expected):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError('Smart playlists not imported')
        time.sleep(1)
    result = {}
    for name, p in found.items():
        detail = api.call('getPlaylist', id=p['id'])['playlist']
        assert detail.get('public') is True
        members = [s['id'] for s in detail.get('entry', [])]
        assert len(members) == len(set(members))
        assert set(members) <= set(ids)
        result[name] = len(members)
        if name == 'Favorites':
            assert ids[0] in members
        if name == 'Recently Added':
            assert len(members) == 4
        if name == 'Fresh Discoveries':
            assert len(members) == 1
        if name == 'Weekly Mix':
            assert members
            assert members == [s['id'] for s in api.call('getPlaylist', id=p['id'])['playlist'].get('entry', [])]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['up', 'check', 'stop'])
    parser.add_argument('--root', type=Path, default=Path('artifacts/navidrome-lab-v2'))
    parser.add_argument('--port', type=int, default=15435)
    args = parser.parse_args()
    root = args.root.resolve()
    os.umask(0o077)
    if not root.exists() and args.action == 'up':
        prepare(root, args.port)
    state = json.loads((root / 'lab.json').read_text())
    if state.get('version') != 1 or state.get('root') != str(root):
        raise ValueError('Not a recognized lab directory')
    compose = ['docker', 'compose', '-f', str(root / 'compose.json')]
    if args.action == 'stop':
        subprocess.run(compose + ['stop'], check=True)
        return
    if args.action == 'up':
        subprocess.run(compose + ['up', '-d', '--pull', 'missing'], check=True)
    check(root, state['port'])


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Lab failed: ' + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
