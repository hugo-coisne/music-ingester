PYTHON ?= .venv/bin/python
PROFILE ?= sandbox
COMPOSE = docker compose --env-file .env -f compose.music.yml

.PHONY: test doctor status install music-config start stop logs backup restore verify-backup preview retry discover discover-preview discovery-status
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
discover:
	$(PYTHON) -m music_ingest discover --config discovery.toml --apply
discover-preview:
	$(PYTHON) -m music_ingest discover --config discovery.toml --dry-run
discovery-status:
	$(PYTHON) -m music_ingest discover --config discovery.toml --status

WATCH_CONFIG ?= watch.toml
watch:
	$(PYTHON) -m music_ingest watch run --config "$(WATCH_CONFIG)" --apply
watch-preview:
	$(PYTHON) -m music_ingest watch run --config "$(WATCH_CONFIG)"
watch-status:
	$(PYTHON) -m music_ingest watch status --config "$(WATCH_CONFIG)"
playlist-add:
	$(PYTHON) -m music_ingest watch add "$(PLAYLIST)" --config "$(WATCH_CONFIG)"
playlist-remove:
	$(PYTHON) -m music_ingest watch remove "$(PLAYLIST)" --config "$(WATCH_CONFIG)"
playlist-list:
	$(PYTHON) -m music_ingest watch list --config "$(WATCH_CONFIG)"

LAB_ROOT ?= artifacts/navidrome-lab-v2
.PHONY: lab lab-check lab-stop
lab:
	$(PYTHON) scripts/navidrome_lab.py up --root "$(LAB_ROOT)"
lab-check:
	$(PYTHON) scripts/navidrome_lab.py check --root "$(LAB_ROOT)"
lab-stop:
	$(PYTHON) scripts/navidrome_lab.py stop --root "$(LAB_ROOT)"
