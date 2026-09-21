"""Argument parsing and process-level error handling for the sync command."""

import argparse
import os
import shutil
import sqlite3
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


def _add_configuration_options(
    parser: argparse.ArgumentParser, *, sync_command: bool = True,
) -> None:
    parser.add_argument(
        "--config", type=Path,
        help=f"TOML configuration file (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--profile", help="Named profile (default: environment or TOML setting)",
    )
    if sync_command:
        parser.add_argument(
            "--list-only", action="store_true",
            help="Preview without writing files or import history",
        )
    parser.add_argument("--library-dir", type=Path)
    parser.add_argument("--staging-dir", type=Path)
    parser.add_argument("--db-path", type=Path)
    if sync_command:
        parser.add_argument(
            "--reference-library", type=Path, action="append", dest="reference_libraries",
            help="Read-only library to check for duplicates; repeat to replace the profile list",
        )
        parser.add_argument("--download-timeout", type=float, help="Maximum seconds per download")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import a YouTube Music playlist into an M4A library."
    )
    parser.add_argument("playlist_id", help="YouTube Music playlist ID")
    _add_configuration_options(parser)
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
            "reference_libraries": getattr(args, "reference_libraries", None),
            "download_timeout": getattr(args, "download_timeout", None),
        },
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in {"cleanup", "doctor", "status"}:
        from . import maintenance

        command = argv[0]
        parser = argparse.ArgumentParser(prog=f"music_ingest {command}")
        _add_configuration_options(parser, sync_command=False)
        if command == "cleanup":
            parser.add_argument("--apply", action="store_true", help="Actually remove selected artifacts")
            parser.add_argument("--drop-errors", action="store_true", help="Also remove known error artifacts")
        args = parser.parse_args(argv[1:])
        try:
            config = resolve_config(args)
            if command == "cleanup":
                return maintenance.cleanup(config, apply=args.apply, drop_errors=args.drop_errors)
            if command == "doctor":
                return maintenance.doctor(config)
            return maintenance.status(config)
        except (ConfigurationError, OSError, sqlite3.DatabaseError) as exc:
            parser.error(str(exc))

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
