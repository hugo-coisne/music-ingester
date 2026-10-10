# Audit et migration — 2026-10-10

## Environnements constatés

Poste : Pop!_OS 22.04, noyau 7.0.11, i7-11800H, 15 619 Mio RAM,
10 063 Mio utilisés au relevé (poste chargé, pas une mesure au repos), 145 Go libres
sur `/home` ext4. UID/GID 1000. Python 3.10.12, Compose 5.4.0.
Deux conteneurs actifs hors musique : lwt (~19 Mio) et MySQL (~184 Mio).
Ancienne stack Servarr arrêtée, Navidrome local 0.58.0, UID/GID 1000.

Serveur SSH configuré : `hugo@192.168.1.111`, hostname `hp-ubuntu-server`.
Ubuntu 24.04.3, i3-5005U (2 cœurs / 4 threads), 7 853 Mio RAM ;
938 Mio utilisés, 6 915 Mio disponibles, swap 1 Mio, disque ext4 `/dev/sda2`
915 Go dont 271 Go disponibles. Python 3.12.3. UID/GID 1000, groupe docker.
Mesures ponctuelles à faible activité, pas un benchmark d'import.

| Conteneur serveur | État | RAM relevée | Ports hôte |
|---|---|---|---|
| Navidrome 0.64.0 | actif depuis 2 semaines | 258,7 Mio | toutes interfaces :4533 |
| obsidian-livesync CouchDB 3.3.3 | actif/sain | 64,49 Mio | toutes interfaces :5984 |
| Portainer | actif | 21,32 Mio | toutes interfaces :9000 |

Aucun service vidéo actif sur ce serveur à l'inventaire Docker.
Ces services annexes ne sont pas modifiés. Pas de timer music-ingest dans
`systemctl list-timers --all` système ; crontabs et timers utilisateur restent à vérifier.
Tailscale absent. Le pare-feu et les redirections NAT restent à vérifier.

## Données

- Poste : 9 M4A gérés, 29 502 382 octets. Ingest production : 9 done / 1 existing,
  aucun fichier enregistré manquant. Sandbox : 2 done / 9 existing, aucun manquant.
- Serveur musique : 3 615 fichiers, 16 869 641 035 octets : 3 601 MP3, 10 M4A,
  3 smart playlists `.nsp`, 1 `.cp`. Aucun fichier déplacé ni retagué.
- SQLite Navidrome : intégrité OK, 3 620 media_file, 2 user, 5 playlist,
  4 001 annotation, 0 playqueue, 1 library. Écart de neuf entrées catalogue à
  diagnostiquer, sans conclure à une perte ni purger les entrées.
- SQLite ingest serveur : intégrité OK, 11 imports. Quatre anciennes sauvegardes
  intègres sont présentes. Une release active existe déjà sous `current`.
- WAL Navidrome observé : 168 812 912 octets ; sauvegarde SQLite en ligne nécessaire.

## Matrice des chemins (aucune migration physique)

| Hôte / ancien chemin | Usage / chemin conteneur | Destination de cette étape |
|---|---|---|
| Poste `library/`, `staging/`, `state/` | ingester local | inchangé |
| Poste `environments/sandbox/` | essais isolés | inchangé |
| Poste `/home/hugow/Downloads/servarr/storage/Completed/Music` | ancienne musique `/music` RO | inchangé |
| Poste `…/Completed/data` | ancienne SQLite Navidrome | inchangé, non utilisée pour la production |
| Serveur `/home/hugo/docker/navidrome/music` | `/music` RO | même montage, aucune copie audio |
| Serveur `/home/hugo/docker/navidrome/data` | `/data` RW de l'ancien service | inchangé |
| Serveur `/home/hugo/docker/music-ingest/{state,staging,releases}` | déploiement existant | inchangé |
| Serveur `/home/hugo/docker/home-music/backups/p0-20261010` | nouveau snapshot privé | créé sans écrasement |
| Serveur `/home/hugo/docker/home-music/preview/data` | nouveau `/data` indépendant | copie de sauvegarde prévue |

Music, data et ingester serveur partagent `st_dev=2050`, ext4. Une sonde isolée
sous home-music a confirmé les hardlinks et le même device que la musique.
Aucun hardlink n'a été créé sur un morceau existant.
Les futurs répertoires albums/downloads devront partager un montage `/media`.

## Écrivains et risques

Navidrome serveur monte déjà `/music` RO. L'ingester peut publier dans cette musique.
Sur le poste, Lidarr, Deluge, Sonarr et Radarr ont historiquement accès RW à tout
`storage` ; Jellyfin à `Completed`. Ils sont arrêtés, ne pas les redémarrer globalement.
Le nouveau Compose n'inclut aucun de ces services.

Le nom `latest` de l'ancienne image est mutable ; image réelle identifiée :
`deluan/navidrome@sha256:a384948b81bd1529986c5960169e7fc4fa00f46bde6bd517971a4c36671db2af`.
Le Compose parallèle fige cette image. Ne jamais démarrer la copie avec la base live.

Un premier accès SQLite à l'ancienne base du poste a été refusé par le bac à sable ;
ne pas utiliser `immutable=1` sur une base WAL pour contourner cette restriction.
La base authoritative auditée et sauvegardée est celle du serveur.

## Sauvegardes

Local : `backups/p0-local-20261010`, 3 bases et 3 configurations, 6 fichiers.
Serveur : `…/home-music/backups/p0-20261010`, 2 bases et 6 configurations, 8 fichiers.
SHA-256 et `integrity_check` via `music_ingest.backup`. Les manifestes avec chemins
et empreintes restent dans ces dossiers privés ignorés par Git.
Ces snapshots ne sauvegardent ni l'audio ni les caches et ne protègent pas contre
la perte du disque. Une deuxième copie sur support indépendant reste à organiser.
