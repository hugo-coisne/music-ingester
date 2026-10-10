# État au 2026-10-10

Mission en cours : socle P0 livré, P1 parallèle déployée, durcissement P2 et
premier module P3 testés. P1 n'est pas encore validée pour usage quotidien.
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

## Incrément Discovery / déduplication

- `music_ingest/discovery/` : adaptateurs Last.fm, playlists hebdomadaires ListenBrainz,
  repli local avec artistes explicitement choisis, score détaillé, exclusions,
  correspondances conservatrices, état SQLite indépendant et rapports d'erreur.
- `discover --dry-run` n'écrit rien ; `--apply` ne fait qu'enregistrer les suggestions ;
  `--status` lit le dernier rapport et recontrôle les fichiers. Aucune acquisition.
- MBID d'enregistrement/ISRC prioritaires, tags M4A conservés et relus. Fingerprinting
  de l'ancienne bibliothèque limité à huit fichiers supplémentaires par cycle.
- Configuration personnelle `discovery.toml` préparée et ignorée par Git. Le fichier
  de clé API est attendu ; l'utilisateur prévoit de le configurer. Pas d'appel Last.fm
  réel réussi à ce stade.
- Templates systemd hebdomadaires fournis mais **non installés**. Verrou de cycle
  et verrou de base testés, pas de nouveau processus Python résident.
- **98 tests réussis** sur Python local 3.10 et image Docker Python 3.12. Construction
  `docker build --target production -t music-ingester:home-music-p3 .` réussie.
- Scénario synthétique ingestion→tags→publication→Discovery : second passage sans
  doublon ; titre absent non jouable. Tests APIs uniquement simulés.
- Image locale finale : `sha256:c79e946a2a8106e5cac025461452895bfc5daef063ffdabdeb0df5d87289f08e`.
  Le nouvel ingester n'a pas remplacé la release de production sur le serveur.
- `.venv/bin/python tests/container_smoke.py --image music-ingester:home-music-p3`
  réussi sur cette image : FFmpeg synthétique, vrais montages Compose, droits UID,
  tags, SQLite persistante, second passage sans doublon, zéro fichier manquant.
- Sauvegarde serveur recopiée sur le poste dans `backups/server-p0-20261010` ; les
  huit fichiers passent la vérification après transfert. Audio toujours non sauvegardé.
- Diagnostic catalogue : neuf chemins ne correspondent plus à un fichier. Snapshot :
  30 annotations favorites, somme des compteurs d'écoute 10601. Aucune purge.

## Problèmes et interventions

- Tailscale absent du serveur ; autorisation de compte et configuration privée requises.
- Identifiants utilisateur Navidrome et essais physiques iPhone nécessaires pour
  certifier streaming authentifié, favoris et écoute hors ligne.
- Fournisseurs de recommandations et source d'acquisition autorisée à configurer.
- L'instance existante écoute sur toutes les interfaces ; exposition externe inconnue.
- Neuf fichiers référencés absents : retrouver leur origine avant tout scan ou purge.
- Ne pas basculer la production tant que la copie n'est pas validée.

Prochaines actions : tester Last.fm lorsque le fichier de clé sera prêt, lecture
Navidrome authentifiée et accès privé, adaptateur OpenSubsonic Discovery, cache HTTP,
file d'acquisition sandbox et synchronisation des playlists. Ni accès iOS ni source
externe ne sont validés par fixtures. P4–P6 restent largement à réaliser, P7 suspendue.
