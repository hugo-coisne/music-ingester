#!/usr/bin/env python3
"""Compatibility entry point; implementation lives in music_ingest."""

from music_ingest.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
