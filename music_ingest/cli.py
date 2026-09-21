"""Argument parsing and process-level error handling for the sync command."""

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Mapping

from ytmusicapi import YTMusic

from .config import (
    DEFAULT_CONFIG_PATH,
    ENV_PREFIX,
    ConfigurationError,
    build_config,
    default_profile,
    load_document,
)
from .pipeline import run_sync


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import a YouTube Music playlist into an M4A library."
    )
    parser.add_argument("playlist_id", help="YouTube Music playlist ID")
    parser.add_argument(
        "--config", type=Path,
        help=f"TOML configuration file (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--profile", help="Named profile (default: environment or TOML setting)",
    )
    parser.add_argument(
        "--list-only", action="store_true", help="Preview without writing files or import history",
    )
    parser.add_argument("--library-dir", type=Path)
    parser.add_argument("--staging-dir", type=Path)
    parser.add_argument("--db-path", type=Path)
    parser.add_argument(
        "--reference-library", type=Path, action="append", dest="reference_libraries",
        help="Read-only library to check for duplicates; repeat to replace the profile list",
    )
    parser.add_argument("--download-timeout", type=float, help="Maximum seconds per download")
    return parser


def resolve_config(
    args: argparse.Namespace, environment: Mapping[str, str] | None = None,
):
    environment = os.environ if environment is None else environment
    configured_path = args.config or environment.get(f"{ENV_PREFIX}CONFIG")
    config_path = Path(configured_path or DEFAULT_CONFIG_PATH).expanduser().resolve()
    if configured_path and not config_path.is_file():
        raise ConfigurationError(f"configuration file does not exist: {config_path}")
    document = load_document(config_path)
    profile = args.profile or environment.get(f"{ENV_PREFIX}PROFILE")
    if profile is None:
        profile = default_profile(document) if document else "default"
    return build_config(
        document=document,
        profile=profile,
        config_path=config_path,
        environment=environment,
        cli_values={
            "library_dir": args.library_dir,
            "staging_dir": args.staging_dir,
            "db_path": args.db_path,
            "reference_libraries": args.reference_libraries,
            "download_timeout": args.download_timeout,
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = resolve_config(args)
    except ConfigurationError as exc:
        parser.error(str(exc))
    if not args.list_only and not shutil.which("ffmpeg"):
        print("[ERR] FFmpeg is required on PATH", file=sys.stderr)
        return 1
    try:
        return run_sync(YTMusic(), args.playlist_id, config, args.list_only)
    except Exception as exc:
        print(f"[ERR] {exc}", file=sys.stderr)
        return 1
