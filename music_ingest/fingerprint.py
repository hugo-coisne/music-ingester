"""Conservative local Chromaprint matching after download.

An exact fingerprint match can catch a recording whose title or artist tags differ.
No external AcoustID service or API key is required.
"""

import json
import shutil
import subprocess
from pathlib import Path

from .models import LibraryIndex


def fingerprint(path: Path) -> str | None:
    if not shutil.which("fpcalc"):
        return None
    try:
        result = subprocess.run(
            ["fpcalc", "-json", "-length", "120", str(path)],
            capture_output=True, text=True, check=True, timeout=60,
        )
        value = json.loads(result.stdout).get("fingerprint")
        return value if isinstance(value, str) and value else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


class FingerprintMatcher:
    """Index candidate paths once and calculate their fingerprints on demand."""

    def __init__(self, library_index: LibraryIndex):
        self._candidates: dict[Path, float] = {}
        self._cache: dict[Path, str | None] = {}
        for items in library_index.values():
            for item in items:
                self._candidates[item["path"]] = item["duration"]

    def add(self, path: Path, duration: float, value: str | None = None) -> None:
        self._candidates[path] = duration
        if value is not None:
            self._cache[path] = value

    def value_for(self, path: Path) -> str | None:
        if path not in self._cache:
            self._cache[path] = fingerprint(path)
        return self._cache[path]

    def find(self, filepath: Path, duration: float) -> Path | None:
        if not shutil.which("fpcalc"):
            return None
        target = self.value_for(filepath)
        if not target:
            return None
        for path, candidate_duration in self._candidates.items():
            if path == filepath or not path.is_file() or abs(candidate_duration - duration) > 4:
                continue
            if self.value_for(path) == target:
                return path
        return None
