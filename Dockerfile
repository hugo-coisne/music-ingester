FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp \
    MUSIC_INGEST_CONFIG=/config/music-ingest.toml \
    MUSIC_INGEST_PROFILE=production

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libchromaprint-tools ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.lock ./
RUN python -m pip install --no-cache-dir -r requirements.lock && python -m pip check
COPY music_ingest ./music_ingest
# Increment only with an explicit migration and rollback strategy.
LABEL org.opencontainers.image.source="https://github.com/hugo-coisne/music-ingester" \
      io.music-ingest.state-format="1"
USER 1000:1000
ENTRYPOINT ["python", "-m", "music_ingest"]
CMD ["--help"]

FROM runtime AS test
COPY tests ./tests
COPY deploy ./deploy
COPY sync.py test_playlist.py inspect_artwork.py music-ingest.toml ./
RUN env -u MUSIC_INGEST_CONFIG -u MUSIC_INGEST_PROFILE python -m unittest discover -s tests -v \
    && touch /tmp/tests-passed

FROM runtime AS production
# Publishing production always builds and tests the exact same runtime layers.
COPY --from=test /tmp/tests-passed /usr/local/share/music-ingest/tests-passed
