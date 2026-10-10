# Sauvegarde et restauration

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
