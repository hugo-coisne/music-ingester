# Ubuntu Server deployment checklist

The repository's production profile intentionally still points to local project
directories. The suggested `/home/hugo/docker/...` paths have not been verified
on the target server and are **not** activated here.

After the sandbox playlist passes its first run and an idempotent second run:

1. Confirm the real Navidrome music path and the UID/GID that can write it.
2. Install Python 3.10+, FFmpeg, ffprobe and Chromaprint's `fpcalc` on Ubuntu.
   Check out the project, create a venv, and install `requirements.lock`.
3. Copy `music-ingest.toml` into a server-specific configuration file and set
   `profiles.production.library_dir`, `staging_dir`, and `db_path` to confirmed
   absolute paths. Set `reference_libraries` to other read-only music libraries
   only; the destination library is already indexed automatically.
4. Run `python -m music_ingest doctor --config PATH --profile production` and
   `python -m music_ingest status --config PATH --profile production`.
5. Run one manual production sync. Verify tags, artwork, paths, Navidrome's
   library scan, and a second idempotent sync before scheduling anything.
6. Only then add a short-lived systemd timer or equivalent scheduler at a
   5–10 minute interval. Set its working directory to the checkout, call the
   venv Python with `-m music_ingest PLAYLIST_ID --config PATH --profile
   production`, and use a separate environment file for the playlist ID. The
   import lock prevents overlapping runs. Monitor exit status and `status`.
7. Run `cleanup --config PATH --profile production` as a preview before any
   scheduled `cleanup --apply`. By default, failed and unknown artifacts stay.

The service/timer is intentionally not installed or enabled by this project.
Private-playlist authentication, structured logs, and Shazam input are outside
the first production milestone.
