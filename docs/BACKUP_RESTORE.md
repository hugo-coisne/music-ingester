# Sauvegarde et restauration

La commande `make recover RECOVERY_CONFIG=recovery.local.json` restaure et valide
Navidrome dans une nouvelle instance locale depuis un snapshot et la musique
disponible séparément. Voir [RECOVERY.md](RECOVERY.md) pour les entrées, vérifications
et limites. Les autres bases et configurations sont conservées en archive ; la
réactivation de l'ingester et une bascule de production restent séparées.

Une sauvegarde de base n'est pas une sauvegarde audio. Prévoir un support séparé
pour musique, sauvegardes et configurations. Les configurations et SQLite peuvent
contenir des secrets, comptes et habitudes d'écoute : ne jamais les committer.

```sh
python3 -m music_ingest.backup create /new/private/backup \
  --database /existing/navidrome/data/navidrome.db \
  --database /existing/music-ingest/state/ingest.db \
  --config-file /existing/navidrome/data/navidrome.toml \
  --config-file /existing/navidrome/docker-compose.yml
python3 -m music_ingest.backup verify /new/private/backup
python3 -m music_ingest.backup restore /new/private/backup /new/private/restore-test
```

Le script utilise SQLite backup en lecture seule côté source, fonctionne avec WAL,
calcule SHA-256 et vérifie l'intégrité. Une sauvegarde échouée peut laisser un dossier
incomplet, jamais considéré valide sans manifeste et vérification. Utiliser un autre
nom à la reprise. La restauration refuse tout dossier destination existant et ne
suit pas les chemins source inscrits dans le manifeste. Elle garde les noms numérotés.

Preuves du 2026-10-10 : sauvegarde/restauration locale de 6 fichiers, serveur de
8 fichiers. Copie Navidrome démarrée depuis ce snapshot ; comparaisons exactes de
comptes, playlists, associations et annotations. Test automatisé de sauvegarde
d'une base active WAL, corruption, traversée de chemin et refus d'écrasement.
La copie serveur est aussi disponible et vérifiée sur le poste sous
`backups/server-p0-20261010`. Aucun fichier audio n'est inclus.

## Restauration de production

1. Vérifier le manifeste et restaurer vers un nouveau dossier.
2. Arrêter uniquement l'écrivain concerné après autorisation d'interruption.
3. Sauvegarder l'état courant, même s'il semble défectueux.
4. Pointer un Compose vers le nouveau dossier validé et l'image de la sauvegarde.
5. Valider intégrité, comptes, favoris, playlists, lecture et scan contrôlé.
6. Garder l'ancien dossier pour retour arrière. Ne pas écraser les fichiers audio.

La base d'ingestion contient des chemins absolus : ne pas la rattacher à une nouvelle
arborescence avant validation de la matrice de chemins. Une base plus ancienne peut
omettre des imports récents ; la reprise doit les réconcilier sans les supprimer.
Un rollback d'image n'implique jamais de restaurer une ancienne base incompatible
par-dessus la base courante. Ne jamais utiliser `docker compose down -v`.

## Automatisation des sauvegardes musicales

Pour réinstaller : copier `scripts/backup_runner.py` et `music_ingest/backup.py`
dans le dossier d'automatisation, adapter `deployment/backup-settings.example.json`
en `backup-settings.json` (0600, uniquement des chemins existants), puis remplacer
`@WATCH_ROOT@` dans les unités `home-music-backup.*` et les installer dans
`~/.config/systemd/user/`. Exécuter la restauration de contrôle ci-dessous avant
`systemctl --user daemon-reload` et `systemctl --user enable --now home-music-backup.timer`.
Ajouter à `configs` les fichiers Compose/configuration Navidrome propres à l'installation.

Le nouveau worker utilise `home-music-backup.timer` à 04:07 UTC chaque jour (jusqu'à
cinq minutes de décalage). `scripts/backup_runner.py` réutilise le module de sauvegarde
existant, attend le verrou partagé du worker et sauvegarde Navidrome, `ingest.db`,
`watch.db`, les configurations privées, la liste d'IDs et le Compose. Aucune copie
brute d'une base active WAL et aucune purge de sauvegardes.

Sur le serveur, configuration privée dans
`/home/hugo/docker/home-music/automation/backup-settings.json`. Le runner et une copie
du module `music_ingest/backup.py` sont installés à côté. Un support séparé pour les
sauvegardes et l'audio reste nécessaire ; le disque du serveur ne protège pas de
sa propre panne. La réserve de 2 Gio empêche de remplir volontairement le disque.

```sh
cd /home/hugo/docker/home-music/automation
python3 backup_runner.py --settings backup-settings.json --restore-check
systemctl --user list-timers home-music-backup.timer
journalctl --user -u home-music-backup.service -n 50 --no-pager
```

Conserver ensemble le journal `watch.db` et les playlists gérées : il contient les
jetons de propriété nécessaires pour reprendre leurs mises à jour après restauration.
Les pistes permanentes ne sont jamais nettoyées par ce mécanisme. Pour réinstaller,
restaurer d'abord dans des dossiers neufs, vérifier les chemins de montage et
réactiver les timers uniquement après une prévisualisation correcte.
