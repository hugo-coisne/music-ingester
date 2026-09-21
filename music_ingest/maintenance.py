"""Read-only checks and conservative staging-artifact cleanup."""

import os
import re
import shutil
import sqlite3
from collections import Counter
from pathlib import Path

from .config import Config

ARTIFACT = re.compile(
    r"^(?P<video_id>[A-Za-z0-9_-]+)\.(?:info\.json|cover(?:-original)?\.jpg|m4a)$"
)


def _records(config: Config) -> list[tuple[str, str, str | None]]:
    if not config.db_path.is_file():
        return []
    with sqlite3.connect(config.db_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        return db.execute("SELECT video_id, status, local_path FROM imports").fetchall()


def status(config: Config) -> int:
    """Report history and missing published files without writing to the database."""
    records = _records(config)
    counts = Counter(row[1] for row in records)
    print(f"Database: {config.db_path}")
    print(f"Library: {config.library_dir}")
    print(f"Staging: {config.staging_dir}")
    print(f"Imports: {sum(counts.values())}")
    for name in ("pending", "downloaded", "processed", "publishing", "done", "existing", "error"):
        if counts[name]:
            print(f"  {name}: {counts[name]}")
    missing = [
        video_id for video_id, state, path in records
        if state in {"done", "existing"} and (not path or not Path(path).is_file())
    ]
    print(f"Missing recorded files: {len(missing)}")
    return 1 if missing else 0


def doctor(config: Config) -> int:
    """Check prerequisites and access without creating application directories."""
    problems = []
    for executable in ("ffmpeg", "ffprobe", "fpcalc"):
        if not shutil.which(executable):
            problems.append(f"{executable} is not on PATH")
    for label, path in (
        ("library", config.library_dir),
        ("staging", config.staging_dir),
        ("database", config.db_path.parent),
    ):
        ancestor = path
        while not ancestor.exists():
            ancestor = ancestor.parent
        if not ancestor.is_dir() or not os.access(ancestor, os.W_OK | os.X_OK):
            problems.append(f"{label} is not writable through {ancestor}")
    if config.db_path.exists():
        try:
            with sqlite3.connect(config.db_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    problems.append("database integrity check failed")
        except sqlite3.DatabaseError as exc:
            problems.append(f"database cannot be read: {exc}")
    print(f"Configuration: library={config.library_dir}, staging={config.staging_dir}, db={config.db_path}")
    for problem in problems:
        print(f"[FAIL] {problem}")
    if not problems:
        print("[OK] prerequisites and paths")
    return 1 if problems else 0


def cleanup(config: Config, *, apply: bool = False, drop_errors: bool = False) -> int:
    """Select known sidecars; never remove unknown or in-flight artifacts."""
    states = {video_id: state for video_id, state, _ in _records(config)}
    selected = []
    if config.staging_dir.is_dir():
        for path in config.staging_dir.iterdir():
            if not path.is_file() or path.is_symlink():
                continue
            match = ARTIFACT.fullmatch(path.name)
            if not match:
                continue
            state = states.get(match.group("video_id"))
            if state in {"done", "existing"}:
                # Completed audio has already moved. Restrict routine cleanup to sidecars.
                if path.suffix == ".m4a":
                    continue
                selected.append(path)
            elif drop_errors and state == "error":
                selected.append(path)
    for path in sorted(selected):
        print(f"{'DELETE' if apply else 'WOULD DELETE'} {path}")
        if apply:
            path.unlink()
    print(f"Artifacts {'removed' if apply else 'eligible'}: {len(selected)}")
    return 0
