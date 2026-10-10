PYTHON ?= .venv/bin/python
PROFILE ?= sandbox
COMPOSE = docker compose --env-file .env -f compose.music.yml

.PHONY: test doctor status install music-config start stop logs backup restore verify-backup preview retry
test:
	$(PYTHON) -m unittest discover -s tests -v
doctor:
	$(PYTHON) -m music_ingest doctor --profile $(PROFILE)
status:
	$(PYTHON) -m music_ingest status --profile $(PROFILE)
install:
	python3 -m venv .venv
	$(PYTHON) -m pip install -r requirements.lock
music-config:
	$(COMPOSE) config --quiet
start: music-config
	$(COMPOSE) up -d --pull never navidrome
stop:
	$(COMPOSE) stop navidrome
logs:
	$(COMPOSE) logs --tail 100 navidrome
preview:
	@test -n "$(PLAYLIST)" || (echo 'Set PLAYLIST'; exit 2)
	$(PYTHON) -m music_ingest "$(PLAYLIST)" --profile $(PROFILE) --dry-run
retry:
	@test -n "$(PLAYLIST)" || (echo 'Set PLAYLIST: reruns the playlist, skips completed imports'; exit 2)
	$(PYTHON) -m music_ingest "$(PLAYLIST)" --profile $(PROFILE)
backup:
	@test -n "$(DEST)" || (echo 'Set a new DEST directory'; exit 2)
	$(PYTHON) -m music_ingest.backup create "$(DEST)" --database state/ingest.db --config-file music-ingest.toml
verify-backup:
	$(PYTHON) -m music_ingest.backup verify "$(SOURCE)"
restore:
	$(PYTHON) -m music_ingest.backup restore "$(SOURCE)" "$(DEST)"
