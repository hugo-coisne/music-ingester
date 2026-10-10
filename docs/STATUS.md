# État au 2026-10-10

Mission en cours : socle P0 livré, validation P1 et corrections P2 indépendantes.
La plateforme complète P0–P6 n'est pas encore validée.

## Preuves initiales

- Git propre initialement, HEAD `b716a36`, historique conservé.
- `.venv/bin/python -m unittest discover -s tests -v` : **75 tests réussis**.
- Python 3.10.12 local, `pip check` sans dépendance cassée ; doctor sandbox OK.
- 9 M4A locaux / 10 imports production ; 11 imports sandbox, aucun fichier manquant.
- Trois SQLite locales : `integrity_check = ok`.
- Serveur accessible via la configuration SSH existante ; Python 3.12.3.
- Navidrome serveur 0.64.0, 3620 entrées catalogue, 2 comptes, 5 playlists,
  4001 annotations ; base intègre. 3611 fichiers audio observés sur disque.

## Incrément P0 / P1 — preuves

- Module sauvegarde/restauration standard-library, quatre tests supplémentaires.
- Protection sandbox contre les chemins production ; cleanup partage le verrou.
- Alias `--dry-run` de `--list-only`, sans changer l'ancienne syntaxe.
- Instructions persistantes et feuille de route détaillée dans AGENTS/ROADMAP.
- Sauvegarde locale `backups/p0-local-20261010` : 6 fichiers vérifiés ; restauration
  isolée `artifacts/restore-local-20261010` réussie. Aucun audio inclus.
- Sauvegarde serveur et restauration isolée : 8 fichiers vérifiés. Sonde hardlink
  réussie sur des fichiers neufs, même device que la musique.
- Nouveau Compose démarré réellement : `home-music-preview-navidrome-1`, image 0.64.0
  figée par digest, `127.0.0.1:4534`, musique RO, base indépendante. Ancien service actif.
- `/ping` et `/app/` : HTTP 200 ; OpenSubsonic sans credentials : erreur 40 attendue.
- Comparaison exacte sauvegarde→copie démarrée : 2 users, 5 playlists, 3979 playlist_tracks,
  4001 annotations et 3620 media_file. Intégrité SQLite OK.
- **81 tests réussis** après les corrections ; Compose validé localement et sur serveur.
- L'utilisateur autorise seulement les nouveaux imports synthétiques pour le moment.
- Fournisseur choisi : Last.fm ; nom public fourni en conversation, clé API non fournie.

## Problèmes et interventions

- Tailscale absent du serveur ; autorisation de compte et configuration privée requises.
- Identifiants utilisateur Navidrome et essais physiques iPhone nécessaires pour
  certifier streaming authentifié, favoris et écoute hors ligne.
- Fournisseurs de recommandations et source d'acquisition autorisée à configurer.
- L'instance existante écoute sur toutes les interfaces ; exposition externe inconnue.
- Écart catalogue/fichiers à examiner en lecture seule avant tout scan ou purge.
- Ne pas basculer la production tant que la copie n'est pas validée.

Prochaines actions : lecture authentifiée et accès privé, module Discovery et ses
tests fournisseurs simulés. Ni accès iOS ni source externe ne sont validés par fixtures.
