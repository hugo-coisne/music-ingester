# Exploitation

| Besoin | Commande |
|---|---|
| Installer les dépendances locales | `make install` |
| Tests hors réseau | `make test` |
| Diagnostic ingestion | `make doctor PROFILE=sandbox` |
| État ingestion | `make status PROFILE=production` |
| Prévisualiser / conserver les suggestions | `make discover-preview` / `make discover` |
| Dernier rapport de recommandations | `make discovery-status` |
| Prévisualiser une playlist | `make preview PLAYLIST=ID PROFILE=sandbox` |
| Reprendre une playlist autorisée | `make retry PLAYLIST=ID PROFILE=sandbox` |
| Valider / démarrer Navidrome parallèle | `make music-config` / `make start` |
| Arrêter seulement cette instance | `make stop` |
| Logs limités | `make logs` |
| Sauvegarder ingestion locale | `make backup DEST=backups/new-name` |
| Vérifier / restaurer en isolation | `make verify-backup SOURCE=...` / `make restore SOURCE=... DEST=...` |

Le défaut Makefile est sandbox. `retry` réexécute la playlist en réutilisant les
imports terminés ; ce n'est pas encore une commande filtrant exclusivement les
erreurs. La demande du 10 octobre autorise désormais les acquisitions YouTube Music
sur les playlists surveillées et recommandations, sans contourner les restrictions
d'accès. Les tests automatisés continuent à utiliser de l'audio synthétique.

La synchronisation déployée utilise `/home/hugo/docker/home-music/automation` :
`./music-playlists add ID`, `list`, `run`, `status`, `report`, `logs`.
Voir [PLAYLIST_SYNC.md](PLAYLIST_SYNC.md) pour les limites et la planification.
Les codes de sortie non nuls signalent aussi les **échecs partiels** : contrôler
le rapport avant de conclure que tout le cycle a échoué.

Sur le serveur, utiliser `docker compose --env-file .env -f compose.music.yml`
depuis `/home/hugo/docker/home-music/repo-p1-20261010`. Le projet est
`home-music-preview`, distinct du service `navidrome` historique.
Logs Docker limités à 3 × 10 Mo. Pas de monitoring résident ajouté.

## Mise à jour / rollback

Sauvegarder, changer le digest de l'image explicitement dans une copie du Compose,
télécharger avec `docker compose ... pull navidrome`, tester une copie de la base,
puis seulement programmer une bascule autorisée. `make start` ne télécharge pas
silencieusement une nouvelle image. Pour l'ingester déployé historiquement,
conserver les commandes `deploy/manage.py` et procédures de `deploy/README.md`.

La prévisualisation ne remplace pas la production. Une bascule doit rafraîchir la
copie depuis une sauvegarde finale pour ne pas perdre les écoutes intervenues
depuis le 2026-10-10, préserver le chemin `/music`, désactiver l'ancienne instance
après accord et valider un seul scrobbler par écoute.

## Diagnostic léger

Comparer `docker stats --no-stream`, `free -m` et l'espace disque avant/pendant un
import. Le plafond parallèle Navidrome est provisoire : 768 Mio et un CPU, à réévaluer
avec streaming/transcodage. Mesure initiale de la copie sans scans : 11,73 Mio,
0,05 % CPU ; ancienne instance : ~259 Mio. Ce n'est pas une mesure d'import.
Un code OpenSubsonic 40 sans identifiants prouve que l'authentification est exigée,
pas qu'un morceau est lisible.
