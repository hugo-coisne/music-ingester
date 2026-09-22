"""The yt-dlp subprocess boundary and validation of its final output."""

import subprocess
import sys
from pathlib import Path

from mutagen.mp4 import MP4

from .config import STAGING_DIR


def download(video_id: str, staging_dir: Path = STAGING_DIR, timeout: float = 900) -> Path:
    """Prefer native AAC; normalize fallback audio to M4A before returning."""
    command = [
        sys.executable, "-m", "yt_dlp",
        "--ignore-config",
        "--no-playlist",
        "--no-simulate",
        "-f", "bestaudio[ext=m4a]/bestaudio",
        "--extract-audio",
        "--audio-format", "m4a",
        "--audio-quality", "0",
        "--embed-metadata",
        "--write-info-json",
        "--no-overwrites",
        "--print", "after_move:filepath",
        "-o", str(staging_dir / "%(id)s.%(ext)s"),
        f"https://music.youtube.com/watch?v={video_id}",
    ]
    result = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())

    output_lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not output_lines:
        raise RuntimeError("yt-dlp did not return an output path")

    filepath = Path(output_lines[-1]).resolve()
    return validate_staged_audio(filepath, staging_dir)


def validate_staged_audio(filepath: Path, staging_dir: Path) -> Path:
    """Accept only a complete M4A inside the configured staging directory."""
    filepath = filepath.resolve()
    if filepath.parent != staging_dir.resolve():
        raise RuntimeError("yt-dlp returned a path outside the staging directory")
    if filepath.suffix.lower() != ".m4a" or not filepath.is_file():
        raise RuntimeError("yt-dlp did not produce an M4A audio file")
    MP4(filepath)  # Reject a corrupt/wrong container before any tagging writes.
    return filepath


def resumable_download(video_id: str, staging_dir: Path) -> Path | None:
    """Reuse completed staging audio left by an interrupted import."""
    filepath = staging_dir / f"{video_id}.m4a"
    if not filepath.is_file():
        return None
    return validate_staged_audio(filepath, staging_dir)
