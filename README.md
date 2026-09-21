# Music ingestion MVP

A Python CLI that imports a YouTube Music playlist into a tagged M4A library.
It checks existing audio, downloads missing tracks with yt-dlp, writes metadata
and artwork, and records progress in SQLite.

## Setup

Requires Python 3.10 or newer, plus `ffmpeg` and `ffprobe` on PATH. The dependency
snapshot and tests were verified with Python 3.10.12. Install FFmpeg using your
operating system's package manager if it is absent.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python sync.py --help
```

`requirements.txt` lists the direct dependencies. `requirements.lock` pins both
direct and transitive dependencies from the verified environment; it is a version
snapshot, not a hash-verified lock. When updating dependencies, update both files
and rerun the tests. FFmpeg is installed separately.

## Usage

The existing script command and the package command are equivalent. Run the
package form from this project directory:

```bash
.venv/bin/python -m music_ingest PLAYLIST_ID --list-only
```


```bash
# Preview: reads the playlist, library and existing history without writing them.
.venv/bin/python sync.py PLAYLIST_ID --list-only

# Import into this project's library.
.venv/bin/python sync.py PLAYLIST_ID

# Import with isolated sandbox paths.
.venv/bin/python sync.py PLAYLIST_ID --profile sandbox

# Also check another library for duplicates; it is only read.
.venv/bin/python sync.py PLAYLIST_ID --reference-library /path/to/music
```

Options:

| Option | Default | Purpose |
| --- | --- | --- |
| `--config PATH` | `music-ingest.toml` beside sync.py | TOML file containing named profiles |
| `--profile NAME` | TOML default (`production`) | Configuration profile to use |
| `--library-dir PATH` | Selected profile | Imported music destination |
| `--staging-dir PATH` | Selected profile | Downloads, metadata JSON and artwork |
| `--db-path PATH` | Selected profile | SQLite import history |
| `--reference-library PATH` | None | Additional library to scan; repeatable |
| `--download-timeout SECONDS` | Selected profile | Maximum time per yt-dlp invocation |
| `--list-only` | Off | Read-only preview; still requires playlist network access |

## Configuration profiles

The committed `music-ingest.toml` contains `production` and `sandbox` profiles.
Production is the default and retains the existing `library/`, `staging/`, and
`state/ingest.db` locations. Sandbox data goes under `environments/sandbox/`,
which is ignored by Git. Selecting sandbox therefore cannot change production
music or import history unless a command-line or environment override explicitly
points back to those locations.

```bash
# Uses the default production profile.
.venv/bin/python -m music_ingest PLAYLIST_ID

# Uses isolated sandbox storage.
.venv/bin/python -m music_ingest PLAYLIST_ID --profile sandbox

# Use profiles maintained elsewhere.
.venv/bin/python -m music_ingest PLAYLIST_ID \
  --config /etc/music-ingest.toml --profile production
```

Profile paths are resolved relative to the TOML file. Explicit command-line paths
and environment paths are resolved relative to the current working directory.
Configuration precedence, from highest to lowest, is:

1. Explicit command-line options
2. `MUSIC_INGEST_*` environment variables
3. The selected TOML profile
4. Built-in project defaults when no TOML file exists

Supported environment variables are `MUSIC_INGEST_CONFIG`,
`MUSIC_INGEST_PROFILE`, `MUSIC_INGEST_LIBRARY_DIR`,
`MUSIC_INGEST_STAGING_DIR`, `MUSIC_INGEST_DB_PATH`,
`MUSIC_INGEST_DOWNLOAD_TIMEOUT`, and `MUSIC_INGEST_REFERENCE_LIBRARIES`.
Separate multiple reference-library paths with the operating system path separator
(`:` on Linux and macOS). Repeated `--reference-library` arguments replace the
profile or environment list.

Example profile:

```toml
[settings]
default_profile = "production"

[profiles.production]
library_dir = "library"
staging_dir = "staging"
db_path = "state/ingest.db"
reference_libraries = ["/srv/music/reference"]
download_timeout = 900
```

Existing library files and the database schema require no migration. The previous
machine-specific reference directory is not scanned implicitly. To retain that
scan, add it to the production profile or supply:

```bash
.venv/bin/python sync.py PLAYLIST_ID \
  --reference-library /home/hugow/Downloads/servarr/storage/Completed/Music
```

The client uses unauthenticated YTMusic access. Private playlists requiring an
account are not configured by this project.

## Import behavior

- Tracks already recorded as `done` or `existing` are skipped while their recorded
  file exists. Missing files are eligible for another import.
- Duplicate matching requires a normalized title, at least one complete matching
  artist tag, and a duration within four seconds. Accents and punctuation are
  normalized; parenthesized featured artists may be omitted from titles. Missing
  durations never establish duplicates. Combined artist strings are not split
  heuristically, so ambiguous tags can result in an extra download.
- The index is updated after each import to detect another video ID for that
  recording in the same run. Repeated identical video IDs are processed once.
- AAC/M4A is preferred. Other audio formats are converted to AAC/M4A by FFmpeg;
  this fallback is lossy. Existing M4A audio does not need transcoding. User-wide
  yt-dlp configuration is ignored to keep output predictable.
- Files are organized as `Artist/Album/NN - Title.m4a`, omitting the track number
  when unknown and using `Singles` when no album is available.
- Name collisions add the video ID, then an increasing number. Complete files are
  published using an exclusive hard link from a temporary file in the destination
  directory. This prevents overwrites and partial published copies, including
  collisions between concurrent publishers. The destination filesystem must
  support hard links; unsupported filesystems fail the import without overwriting.
- Album metadata and artwork share a per-run cache, including failed lookups.
  Album artwork is preferred, with track thumbnails as a fallback. Flat sidebars
  can be cropped; original and processed JPEGs remain in staging.
- Artwork failures are warnings. Embedding operates on a temporary audio copy,
  preserving the tagged audio if embedding fails.
- Failed imports retain an error in SQLite and can be retried by running the same
  command again. Staged downloads and diagnostic assets are retained.

The summary distinguishes `imported`, `existing`, `new`, `failed`, `skipped`, and
`artwork_warnings`. `new` counts candidates, not successful downloads. Exit status
is **0** when processing completes without failed tracks, **1** for import/setup
failures, and **2** for invalid command-line arguments. Artwork warnings alone do
not fail a run. Preview cannot determine whether different new video IDs will
produce the same audio, so its candidate count can exceed actual imports.

Use one sync process per staging directory and database. Exclusive publication
protects destination files, but the whole downloader/history workflow is not a
cross-process transaction. A hard interruption can leave temporary files or a
published file whose history update has not completed; the next library scan can
recognize tagged audio through the normal duplicate rules.

## Source layout

`sync.py`, `test_playlist.py`, and `inspect_artwork.py` are thin compatibility
entry points. Application code lives in `music_ingest/`; importing a module does
not start a sync or create runtime directories. No data migration or dependency
changes are required by this layout.

| Module | Responsibility |
| --- | --- |
| `cli.py`, `__main__.py` | Arguments, path resolution, prerequisite checks, process exit status |
| `config.py`, `models.py` | Immutable settings, typed data contracts, summary counters |
| `pipeline.py` | Playlist control flow, per-track preparation, publication and history ordering |
| `catalog.py` | Per-run album cache, including failed lookups |
| `library.py` | Read existing audio tags, normalize identities, match duplicates |
| `download.py` | Invoke yt-dlp, enforce timeout, validate its M4A output |
| `metadata.py` | Build metadata from catalog responses and write M4A tags |
| `artwork.py` | Select, crop, download, and safely embed optional artwork |
| `publishing.py` | Determine filenames and publish complete files without overwriting |
| `history.py` | SQLite schema, read-only preview connections, committed status transitions |
| `diagnostics.py` | Manual playlist and artwork inspection commands |

The dependency flow starts at the CLI and passes through the pipeline to focused
operation modules. Those modules do not import the CLI or pipeline. `MusicClient`
is a small protocol for the playlist and album operations, so tests can substitute
a fake client without subclassing the external library. Flexible API dictionaries
are mapped to explicit internal types in `models.py`.

Metadata construction and artwork selection accept already-fetched album data;
only `AlbumCache` performs album lookups. `ArtworkOutcome` distinguishes absent
artwork, successful embedding, and optional failure. `SyncSummary` owns named
counters and the failure exit code. Filesystem publication and SQLite commits
remain separate operations with the recovery limitations described above.

## Development and validation

```bash
.venv/bin/python -m unittest discover -s tests -v
# Run a focused module while developing:
.venv/bin/python -m unittest tests.test_publishing -v
.venv/bin/python -m pip check
```

Tests are grouped by responsibility under `tests/`; `tests/support.py` provides
shared temporary workspaces and synthetic data. Import the owning module when
extending the application or tests (for example, `music_ingest.publishing`), rather
than importing implementation helpers from `sync.py`. Mock external I/O at its
owning module; keep metadata and matching tests independent of those mocks.

Tests use temporary directories and mocked network access. Audio integration tests
use FFmpeg-generated tones and real Mutagen tagging and yt-dlp conversion; they
are skipped when FFmpeg/ffprobe are missing. Tests do not download music or modify
the existing library or history.

`test_playlist.py PLAYLIST_ID` lists playlist tracks; `inspect_artwork.py
PLAYLIST_ID` inspects artwork sources. Both are manual network diagnostics, not
regression tests, and both support `--help`.

Runtime files and the virtual environment are excluded by `.gitignore`. This
workspace was supplied without usable Git metadata; no repository was initialized.
