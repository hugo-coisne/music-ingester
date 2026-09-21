"""Server-side release management using only the Python standard library.

The workstation sends this module over SSH. The timer uses the copy saved in
the active release. All managed commands share an exclusive host-side lock.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import uuid


IMAGE = re.compile(r"ghcr\.io/[a-z0-9._/-]+@sha256:[a-f0-9]{64}")
RELEASE = re.compile(r"[0-9]{8}T[0-9]{6}Z-[a-f0-9]{12}")
STORAGE_FIELDS = ("root", "library", "uid", "gid")


def validate_settings(settings: dict) -> None:
    expected = {*STORAGE_FIELDS, "playlist_id", "download_timeout"}
    if set(settings) != expected:
        raise ValueError(f"deployment settings must contain exactly: {sorted(expected)}")
    for field in ("root", "library"):
        value = settings[field]
        if not isinstance(value, str) or not value.startswith("/"):
            raise ValueError(f"{field} must be an absolute path")
        if Path(value) == Path("/") or any(c in value for c in "\n\r\0$"):
            raise ValueError(f"unsafe {field} path")
    root, library = (Path(settings[field]).resolve() for field in ("root", "library"))
    if root == library or root in library.parents or library in root.parents:
        raise ValueError("deployment root and library must be separate directories")
    for field in ("uid", "gid"):
        if type(settings[field]) is not int or settings[field] <= 0:
            raise ValueError(f"{field} must be a non-root numeric ID")
    playlist = settings["playlist_id"]
    if not isinstance(playlist, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", playlist):
        raise ValueError("playlist_id must be a playlist ID, not a URL")
    if playlist.startswith("REPLACE_"):
        raise ValueError("replace the example playlist_id")
    timeout = settings["download_timeout"]
    if type(timeout) not in (int, float) or not 0 < timeout <= 86400:
        raise ValueError("download_timeout must be between 0 and 86400 seconds")


def execute(args: list[str], *, capture: bool = False, timeout: int = 120):
    return subprocess.run(
        args, check=True, text=True, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None, timeout=timeout,
    )


def durable_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_file(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8") as destination:
        destination.write(text)
        destination.flush()
        os.fsync(destination.fileno())


@contextmanager
def exclusive(path: Path):
    with path.open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"another operation holds {path}; retry after it finishes") from exc
        yield


def active_release(root: Path) -> Path | None:
    current = root / "current"
    if not current.is_symlink():
        if current.exists():
            raise ValueError("current must be a managed release symlink")
        return None
    return release_path(root, current.resolve().name)


def release_path(root: Path, name: str) -> Path:
    if not RELEASE.fullmatch(name):
        raise ValueError("invalid release ID")
    release = root / "releases" / name
    if release.is_symlink() or not (release / "ready").is_file():
        raise ValueError(f"release is missing or was not validated: {name}")
    return release


def manifest(release: Path) -> dict:
    return json.loads((release / "manifest.json").read_text())


def compose(release: Path) -> list[str]:
    # An explicit empty env file prevents a server-side .env overriding a release.
    return ["docker", "compose", "--env-file", "/dev/null", "--project-name",
            "music-ingest", "--file", str(release / "compose.json")]


def job_name(root: Path) -> str:
    return "music-ingest-" + hashlib.sha256(str(root).encode()).hexdigest()[:12]


def ensure_idle(root: Path) -> None:
    # A disconnected SSH client can leave a container running. Never deploy over it.
    output = execute(
        ["docker", "ps", "-aq", "--filter", f"name=^/{job_name(root)}$"], capture=True,
    ).stdout.strip()
    if output:
        raise RuntimeError(f"container {job_name(root)} still exists; inspect it before retrying")


def container(root: Path, release: Path, command: list[str], *, entrypoint: str | None = None):
    args = compose(release) + ["run", "--rm", "--no-deps", "-T", "--pull", "never",
                               "--name", job_name(root)]
    if entrypoint:
        args += ["--entrypoint", entrypoint]
    execute(args + ["music-ingest"] + command, timeout=21600)


# Probe from the actual container UID. It exercises hard-link publication support
# and SQLite writes using disposable files, without opening production history RW.
PROBE = """
import os, pathlib, sqlite3, tempfile
for directory in ('/music', '/staging', '/state'):
    with tempfile.TemporaryDirectory(prefix='.ingest-probe-', dir=directory) as tmp:
        source = pathlib.Path(tmp) / 'source'
        source.write_bytes(b'probe')
        os.link(source, pathlib.Path(tmp) / 'linked')
        assert (pathlib.Path(tmp) / 'linked').read_bytes() == b'probe'
with tempfile.TemporaryDirectory(prefix='.ingest-probe-', dir='/state') as tmp:
    with sqlite3.connect(str(pathlib.Path(tmp) / 'probe.db')) as db:
        db.execute('CREATE TABLE probe (value INTEGER)')
        db.execute('INSERT INTO probe VALUES (1)')
        db.commit()
print('[OK] container write, hard-link and SQLite probes')
"""


def check_candidate(root: Path, release: Path) -> None:
    image = manifest(release)["image"]
    inspect = ["docker", "image", "inspect", "--format",
               '{{index .Config.Labels "io.music-ingest.state-format"}}', image]
    try:
        result = execute(inspect, capture=True)
    except subprocess.CalledProcessError:
        execute(["docker", "pull", image], timeout=900)
        result = execute(inspect, capture=True)
    label = result.stdout.strip()
    if label != "1":
        raise ValueError("unsupported state format; an explicit migration procedure is required")
    execute(compose(release) + ["config", "--quiet"])
    container(root, release, ["-c", PROBE], entrypoint="python")
    container(root, release, ["doctor"])
    container(root, release, ["status"])


def snapshot(root: Path, name: str) -> None:
    backup = root / "backups" / name
    backup.mkdir(parents=True)
    current = active_release(root)
    write_file(backup / "release.json", json.dumps(
        manifest(current) if current else {"current": None}, indent=2,
    ) + "\n")
    source = root / "state" / "ingest.db"
    if source.exists():
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as db:
            with sqlite3.connect(backup / "ingest.db") as target:
                db.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("SQLite backup integrity check failed")
        with (backup / "ingest.db").open("rb") as saved:
            os.fsync(saved.fileno())
    durable_directory(backup)


def activate(root: Path, release: Path) -> None:
    temporary = root / (".current-" + uuid.uuid4().hex)
    temporary.symlink_to(Path("releases") / release.name)
    os.replace(temporary, root / "current")
    durable_directory(root)


def configuration(settings: dict) -> str:
    return ('[settings]\ndefault_profile = "production"\n\n'
            '[profiles.production]\nlibrary_dir = "/music"\n'
            'staging_dir = "/staging"\ndb_path = "/state/ingest.db"\n'
            'reference_libraries = []\n'
            f'download_timeout = {settings["download_timeout"]}\n')


def prepare_release(root: Path, request: dict, current: Path | None) -> Path:
    settings = request["settings"]
    source = None
    if request["action"] == "rollback":
        if not current:
            raise ValueError("no active release to roll back")
        name = request.get("release") or manifest(current).get("previous")
        if not name:
            raise ValueError("no previous release; select one explicitly")
        source = release_path(root, name)
        data = manifest(source)
        settings, image = data["settings"], data["image"]
    else:
        image = request["image"]
    validate_settings(settings)
    if not IMAGE.fullmatch(image):
        raise ValueError("image must be a GHCR reference pinned by sha256 digest")
    if current and any(
        settings[key] != manifest(current)["settings"][key] for key in STORAGE_FIELDS
    ):
        raise ValueError("storage paths and UID/GID cannot change during deployment or rollback")
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12]
    release = root / "releases" / name
    release.mkdir(parents=True)
    data = dict(image=image, settings=settings, previous=current.name if current else None,
                action=request["action"], rollback_of=source.name if source else None)
    write_file(release / "manifest.json", json.dumps(data, indent=2) + "\n")
    if source:
        # Use the exact Compose/config/controller snapshot of the selected release.
        spec = json.loads((source / "compose.json").read_text())
        for mount in spec["services"]["music-ingest"]["volumes"]:
            if mount["target"] == "/config/music-ingest.toml":
                mount["source"] = str(release / "music-ingest.toml")
        config_text = (source / "music-ingest.toml").read_text()
        controller = (source / "controller.py").read_text()
    else:
        spec = request["compose"]
        service = spec["services"]["music-ingest"]
        service["image"] = image
        service["user"] = f'{settings["uid"]}:{settings["gid"]}'
        service["volumes"] = [
            {"type": "bind", "source": str(path), "target": target,
             "read_only": readonly, "bind": {"create_host_path": False}}
            for path, target, readonly in (
                (settings["library"], "/music", False),
                (root / "staging", "/staging", False),
                (root / "state", "/state", False),
                (release / "music-ingest.toml", "/config/music-ingest.toml", True),
            )
        ]
        config_text = configuration(settings)
        controller = request["controller"]
    write_file(release / "compose.json", json.dumps(spec, indent=2) + "\n")
    write_file(release / "music-ingest.toml", config_text)
    write_file(release / "controller.py", controller)
    durable_directory(release)
    return release


def audit(root: Path, action: str, result: str, **details) -> None:
    event = dict(time=datetime.now(timezone.utc).isoformat(), action=action,
                 result=result, **details)
    with (root / "operations.jsonl").open("a") as log:
        log.write(json.dumps(event) + "\n")
        log.flush()
        os.fsync(log.fileno())


def handle(request: dict) -> None:
    settings = request["settings"]
    validate_settings(settings)
    root = Path(settings["root"]).resolve()
    if not root.is_dir() or not Path(settings["library"]).is_dir():
        raise ValueError("root and library must already exist; check the host paths")
    if os.getuid() != settings["uid"] or settings["gid"] not in {*os.getgroups(), os.getgid()}:
        raise ValueError("SSH user must match the configured UID and belong to the configured GID")
    os.umask(0o027)
    with exclusive(root / "operation.lock"):
        action = request["action"]
        try:
            ensure_idle(root)
            current = active_release(root)
            if action in {"deploy", "rollback"}:
                for directory in ("state", "staging"):
                    (root / directory).mkdir(exist_ok=True)
                # Same inode as /state/ingest.db.lock inside the container.
                with exclusive(root / "state" / "ingest.db.lock"):
                    release = prepare_release(root, request, current)
                    snapshot(root, release.name)
                    check_candidate(root, release)
                    write_file(release / "ready", "validated\n")
                    durable_directory(release)
                    durable_directory(root / "releases")
                    audit(root, action, "validated", release=release.name)
                    activate(root, release)
                    print(f'Active release: {release.name}\nImage: {manifest(release)["image"]}', flush=True)
            else:
                if not current:
                    raise ValueError("no active release; deploy first")
                data = manifest(current)
                print(f'Active release: {current.name}\nImage: {data["image"]}', flush=True)
                if action == "run":
                    container(root, current, [data["settings"]["playlist_id"]])
                elif action == "preview":
                    container(root, current, [data["settings"]["playlist_id"], "--list-only"])
                elif action in {"doctor", "status"}:
                    container(root, current, [action])
                else:
                    raise ValueError(f"unsupported action: {action}")
            audit(root, action, "success", release=active_release(root).name)
        except Exception as exc:
            audit(root, action, "failed", error=str(exc))
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("action", choices=("run", "preview", "doctor", "status", "rollback"))
    parser.add_argument("--release")
    args = parser.parse_args()
    try:
        current = active_release(args.root.resolve())
        if not current:
            raise ValueError("no active release")
        handle(dict(action=args.action, settings=manifest(current)["settings"], release=args.release))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, sqlite3.Error) as exc:
        print(f"[ERR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
