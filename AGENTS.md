# Home Music Platform

Conserver le package `music_ingest` à la racine et l'historique Git. Lire
`docs/STATUS.md`, `docs/ROADMAP.md`, `docs/DECISIONS.md` avant de reprendre.
La feuille de route distingue réalisation, tests simulés et validation sur serveur.

## Développement

- Python local : `.venv/bin/python`. Tests : `make test`.
- CLI historique : `.venv/bin/python -m music_ingest` (voir README.md).
- Synchronisation : `music_ingest watch`, `docs/PLAYLIST_SYNC.md`. Le 10 octobre,
  l'utilisateur a demandé l'acquisition automatique YouTube Music, remplaçant
  sa restriction antérieure aux tests synthétiques. Ne pas contourner les accès.
- Préserver `production` et `sandbox`. Tester avec des fichiers synthétiques.
- Tester erreurs partielles, concurrence, reprises et absence d'écrasement.
- Commit explicite des seuls fichiers source après validation ; jamais `git add .`.
- Actualiser STATUS et les tâches ROADMAP à chaque incrément.

## Invariants

- Aucun modèle IA, API payante, GPU ou serveur Python résident pour planifier.
- SQLite, tâches ponctuelles, un worker ; ne pas fingerprint toute la bibliothèque.
- Ne jamais supprimer/déplacer/écraser de donnée existante sans autorisation.
- Sauvegarder SQLite avec l'API backup, pas une copie isolée d'une base en WAL.
- Navidrome lit la musique ; seul l'ingester écrit dans ses dossiers dédiés.
- Ne jamais faire écrire deux instances Navidrome dans le même `/data`.
- Ne pas modifier les services vidéo, ni leurs volumes ; P7 reste en attente.
- Pas de secrets dans Git, logs ou URLs. Pas de TLS désactivé, `down -v`, prune global.
- Pas d'acquisition réelle sans source et autorisation de droits identifiées.
- Une suggestion n'est jouable qu'après correspondance locale vérifiée ou publication.
- Navidrome 0.64 retourne des chemins API virtuels : intersecter les IDs autorisés
  avec les chemins SQLite RO et les fichiers existants. Ne jamais écrire sa base.
- Préserver les jetons de propriété de `watch.db` : aucun rapprochement de playlist
  par simple nom, aucune suppression des playlists personnelles.
- Le poste Pop!_OS et le serveur Ubuntu sont distincts. Ne pas confondre leurs chemins.
- SSH vérifie la clé d'hôte ; déploiement parallèle sur boucle locale, sans bascule
  de production ni changement réseau sensible sans autorisation.

## Reprise

1. `git status --short`, lire les trois documents de suivi.
2. Exécuter les tests et vérifier la disponibilité du serveur configuré localement.
3. Choisir la prochaine tâche indépendante ; documenter les accès manquants.
4. Valider, conserver les preuves sans secrets, mettre à jour les états
   TODO / IN_PROGRESS / DONE / BLOCKED et committer l'incrément.
