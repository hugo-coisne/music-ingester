"""Offline smoke test of the production image with real Compose and bind mounts.

Run from the repository: python3 tests/container_smoke.py --image music-ingester:local
Requires access to a local Docker daemon. Only temporary directories are mounted.
"""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from deploy import controller


IMPORT = """
import hashlib, shutil, sqlite3, subprocess
from pathlib import Path
from unittest.mock import Mock, patch
from mutagen.mp4 import MP4
from music_ingest import cli, pipeline, download
config = cli.resolve_config(cli.build_parser().parse_args(['PLsmoke']))
subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                '-i', 'sine=frequency=440:duration=8', '-c:a', 'aac', '/tmp/tone.m4a'], check=True)
client = Mock()
client.get_playlist.return_value = dict(title='Offline container test', tracks=[dict(
    videoId='smoke1', title='Container smoke', artists=[{'name': 'Test artist'}], duration_seconds=8)])
def fixture(video_id, staging, timeout):
    path = staging / (video_id + '.m4a')
    shutil.copyfile('/tmp/tone.m4a', path)
    return path
with patch.object(download, 'download', side_effect=fixture) as mocked:
    assert pipeline.run_sync(client, 'PLsmoke', config) == 0
    files = list(Path('/music').rglob('*.m4a'))
    assert len(files) == 1
    audio = files[0]
    before = hashlib.sha256(audio.read_bytes()).digest()
    assert MP4(audio)['\\xa9nam'] == ['Container smoke']
    assert pipeline.run_sync(client, 'PLsmoke', config) == 0
    mocked.assert_called_once()
    assert before == hashlib.sha256(audio.read_bytes()).digest()
with sqlite3.connect('/state/ingest.db') as db:
    assert db.execute('SELECT status FROM imports').fetchall() == [('done',)]
print('[OK] offline import, tags, persistent SQLite and idempotent second run')
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="music-ingester:local")
    args = parser.parse_args()
    image_id = controller.execute(
        ["docker", "image", "inspect", "--format", "{{.Id}}", args.image], capture=True,
    ).stdout.strip()
    source = Path(__file__).resolve().parent.parent / "deploy"
    with tempfile.TemporaryDirectory(prefix="music-ingest-smoke-") as temporary:
        base = Path(temporary)
        root, library = base / "deployment", base / "music"
        for directory in (root, library, root / "state", root / "staging"):
            directory.mkdir()
        settings = dict(root=str(root), library=str(library), uid=os.getuid(), gid=os.getgid(),
                        playlist_id="PLsmoke", download_timeout=900)
        request = dict(action="deploy", settings=settings,
                       image="ghcr.io/local/smoke@" + image_id,
                       compose=json.loads((source / "compose.json").read_text()),
                       controller=(source / "controller.py").read_text())
        release = controller.prepare_release(root, request, None)
        # Registry transport is deliberately excluded: execute the exact local
        # image ID under the same runtime settings, with networking disabled.
        spec = json.loads((release / "compose.json").read_text())
        spec["services"]["music-ingest"].update(image=image_id, network_mode="none")
        (release / "compose.json").write_text(json.dumps(spec))
        controller.execute(controller.compose(release) + ["config", "--quiet"])
        controller.container(root, release, ["-c", controller.PROBE], entrypoint="python")
        controller.container(root, release, ["doctor"])
        controller.container(root, release, ["-c", IMPORT], entrypoint="python")
        controller.container(root, release, ["status"])
        assert all(p.stat().st_uid == os.getuid() for p in library.rglob("*"))
        print("[OK] real Compose smoke test; all files owned by the invoking user")


if __name__ == "__main__":
    main()
