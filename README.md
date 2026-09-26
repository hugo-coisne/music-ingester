# Music ingestion

A Python CLI that imports a YouTube Music playlist into a tagged M4A library.
It checks existing audio, downloads missing tracks with yt-dlp, writes metadata
and artwork, and records progress in SQLite.

## Server deployment

The [deployment guide](deploy/README.md) covers Docker, GitHub Actions publication
on `main`, SSH deployment from a workstation, configuration snapshots, rollback,
SQLite backups and an optional systemd timer. Automatic server deployment is
opt-in; the committed application profiles continue to use local directories.

```bash
docker build --target production -t music-ingester:local .
.venv/bin/python tests/container_smoke.py --image music-ingester:local
```

The production image build runs the regression suite. The separate offline
Compose smoke test verifies volume permissions, publication and idempotence.

## Setup

Requires Python 3.10 or newer, plus `ffmpeg`, `ffprobe` and Deno 2.3+ on PATH.
The dependency snapshot and tests were verified with Python 3.10.12. Deno and the
matching `yt-dlp-ejs` package solve the JavaScript challenges required by current
YouTube extraction. Install `fpcalc` (Chromaprint) for the optional third level of
audio duplicate detection; `doctor` checks all of these prerequisites. The Docker
image supplies Deno, FFmpeg, fpcalc and the Python dependencies itself.

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

# Inspect the selected sandbox environment before a live test.
.venv/bin/python -m music_ingest doctor --profile sandbox
.venv/bin/python -m music_ingest status --profile sandbox

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
- After a new download, `fpcalc` computes a Chromaprint fingerprint and compares
  it with tagged library recordings of similar duration, regardless of title or
  artist. Exact fingerprint matches are recorded as existing. This does not
  contact AcoustID and does not run when `fpcalc` is unavailable. Reference files
  without readable title/artist tags are not fingerprint candidates. Fingerprints
  are cached in memory for one run, so a large library can add processing time.
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
- Artwork downloads retry transient network errors, HTTP 429 and common HTTP 5xx
  responses three times with a short backoff. Permanent failures remain warnings.
  Embedding operates on a temporary audio copy, preserving the tagged audio if
  embedding fails.
- The import history records `pending`, `downloaded`, `processed`, `publishing`,
  then `done` (or `existing` / `error`). On restart, a published M4A with the
  expected embedded video ID repairs an interrupted row. A complete M4A left in
  staging is reused. Failed imports retain an error and can be retried.

The summary distinguishes `imported`, `existing`, `new`, `failed`, `skipped`, and
`artwork_warnings`. `new` counts candidates, not successful downloads. Exit status
is **0** when processing completes without failed tracks, **1** for import/setup
failures, and **2** for invalid command-line arguments. Artwork warnings alone do
not fail a run. Preview cannot determine whether different new video IDs will
produce the same audio, so its candidate count can exceed actual imports.

An exclusive lock prevents two sync processes from writing the same database at
once. Publication remains an atomic hard link from a complete temporary file on
the destination filesystem, including when staging is on another filesystem.
SQLite and the filesystem cannot commit as one transaction. Recovery reconciles
published tagged files on the next run; an unexpected power failure can still
leave a hidden `.ingest-*` temporary file for manual inspection.

## Maintenance

All maintenance commands accept `--profile` and `--config` with the same
precedence as sync commands. They do not contact YouTube Music.

```bash
.venv/bin/python -m music_ingest status --profile sandbox
.venv/bin/python -m music_ingest doctor --profile sandbox
.venv/bin/python -m music_ingest cleanup --profile sandbox
.venv/bin/python -m music_ingest cleanup --profile sandbox --apply
```

`status` reports import states and missing recorded files. `doctor` checks
FFmpeg, ffprobe, fpcalc, Deno, yt-dlp-ejs, path access, and SQLite integrity
without creating directories. `cleanup` previews known staging sidecars for completed imports;
`--apply` removes them. Error artifacts are retained unless `--drop-errors` is
also passed. Unknown and in-flight artifacts are always kept. The cleanup
command does not delete library audio, and completed staging audio is retained
for inspection if unexpectedly present.

For the first real test, use a playlist containing a new track, a track already
in the reference library, and an obscure track without a YTMusic album. Run a
sandbox sync, inspect tags/artwork/file paths and `status`, then repeat the same
sync to check idempotence. Supply `--reference-library /path/to/existing/music`
to exercise duplicate detection against a separate library. The sandbox profile
alone checks only its own isolated library.

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
| `fingerprint.py` | Local acoustic fingerprint comparison after download |
| `maintenance.py` | Status, doctor and conservative cleanup commands |
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

Runtime files, local deployment targets and the virtual environment are excluded
by `.gitignore`. The Docker build context also excludes libraries, databases,
credentials and local deployment targets.
