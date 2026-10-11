# État au 2026-10-11

## P6.5 — restauration guidée validée en laboratoire

- Nouveau `music_ingest recover`, exposé par `make recovery-preview` et `make recover`.
  Configuration d'exemple dans `deployment/recovery.example.json`, procédure dans
  `docs/RECOVERY.md`. La simulation ne crée rien et n'appelle pas Docker.
- Snapshot vérifié, destination neuve, contrôles des chemins/fichiers/espace/port,
  refus de réutiliser un projet Compose occupé ; musique RO et écoute boucle locale.
  Scans, plugins, services externes et scrobbling restent désactivés sur la copie.
- Les dix fichiers de la sauvegarde synthétique sont restaurés et vérifiés, dont
  `watch.db` strictement identique (propriété des miroirs conservée). La base Navidrome
  de travail est copiée depuis l'archive sans modifier cette dernière.
- Test réel de la CLI : `tests/recovery_smoke.py --work artifacts/recovery-cli-20261011`.
  Un compte, quatre annotations, neuf playlists, 22 associations, quatre morceaux
  et trois écoutes préservés ; file de scrobbling vide conservée. Comparaison par
  empreintes des lignes persistantes, puis authentification et streaming natif vérifiés
  sur `127.0.0.1:15436` (premiers 16 Kio identiques au fichier).
- Les deux copies de restauration utilisées pour les essais sont arrêtées. Le
  laboratoire principal reste disponible sur 15435 ; aucune modification du serveur
  Ubuntu ou de sa bibliothèque en cours de réarrangement.
- `make test` : **144 tests réussis**, dont 11 tests de restauration guidée
  (corruption, chevauchement, manque d'espace, fichiers absents, permissions,
  ambiguïté, interruption et préservation sur échec). `git diff --check` réussi.
- Preuve privée : `artifacts/recovery-cli-20261011/restored/recovery-result.json`.
  Seule la restauration Navidrome isolée est validée en une commande. Réinstallation
  complète sur machine vierge, reprise automatique du worker et bascule de production
  restent ouvertes en P6.5 ; sauvegarde externe/audio toujours à préparer en P6.2.

Prochain incrément indépendant possible : conservation/promotion des découvertes
en sandbox (P4.4). La production attend la fin annoncée du réarrangement et le réaudit.

## Laboratoire isolé et playlists locales — 11 octobre

- Autorisation reçue de créer une autre instance pendant le réarrangement.
  Laboratoire sur le poste **Pop!_OS**, sans volume du serveur Ubuntu :
  `artifacts/navidrome-lab-v2`, `http://127.0.0.1:15435/app/`, Navidrome 0.64.0
  figé par digest. Musique RO, base neuve, compte synthétique, intégrations externes
  désactivées. Aucun accès ni changement de production dans cet incrément.
- `make lab` crée/démarre et vérifie le laboratoire ; `make lab-check` / `make lab-stop`
  le recontrôlent/l'arrêtent. La première fixture locale `navidrome-lab-v1` est arrêtée.
  Prérequis : environnement Python, FFmpeg et Docker. Ce n'est pas une restauration
  de production en une commande ; P6.5 reste ouverte.
- **API Navidrome réelle** : quatre sons synthétiques indexés ; miroir public,
  réparation privé→public et deuxième passage sans changement. Streaming authentifié
  HTTP 200, octets identiques au fichier. Contrôle de production toujours à refaire
  après maintenance. Le JSON API omet `public` quand il est faux : fixture adaptée.
- Cinq Smart Playlists publiques importées : Favorites (1), Fresh Discoveries (1),
  Recently Added (4), Rediscover My Library (1), Weekly Mix (2). Historique synthétique
  de 100 jours et favori utilisés ; aucun scrobble externe. Mix stable au second accès.
  Essai réel ayant corrigé le filtre Fresh Discoveries : chemin relatif
  `Managed Singles/`, pas `/Managed Singles/`.
- Nouveau `music_ingest radio` : artiste, morceau ou genre, simulation par défaut,
  sources expliquées, filtre fichiers physiques/IDs autorisés, réutilisation du verrou,
  de la propriété et des sauvegardes de miroir. Trois radios réelles de trois titres
  chacune ; répétition idempotente. Fallback local testé avec panne de similarité simulée.
- `make test` : **133 tests réussis** en local. `make lab-check` et `make lab` réussis
  après correction ; preuve privée `artifacts/navidrome-lab-v2/proof.json`.
- Mesure au repos sur le poste : **22,08 Mio et 0,02 % CPU**, limite 384 Mio/0,75 CPU.
  C'est une mesure de laboratoire avec quatre pistes, pas celle de la bibliothèque réelle.
- Documentation : `docs/LOCAL_PLAYLISTS.md`. Aucun déploiement des radios/Smart Playlists
  sur le serveur en maintenance ; timer d'ingestion laissé suspendu. Prochaines étapes :
  promotion/rétention ou restauration guidée en isolation ; audit des chemins et
  validation de production seulement à la fin du réarrangement.

## P3.2 local et suspension de l'automatisation — 11 octobre

- Confirmation serveur : `home-music-watch.timer` est `inactive` et `disabled`.
  Le worker a `MainPID=0` (dernier état failed, Navidrome indisponible) ; aucun
  conteneur d'ingestion actif au contrôle. Ne pas réactiver pendant le réarrangement.
- Cache de réponses Last.fm/ListenBrainz ajouté au worker dans `watch.db`, borné
  en durée, nombre d'entrées et taille ; forcage de rafraîchissement conservé.
  Échecs non cachés, secrets de requête non stockés en clair, simulation en mémoire.
- Tests ciblés réussis : 24 (dont huit nouveaux), avec reprise après panne partielle,
  expiration, quotas, séparation des paramètres/comptes/clés, corruption et absence
  d'écriture en simulation. Ces preuves utilisent des APIs simulées.
- Non-régression : `make test`, **126 tests réussis** localement ;
  `git diff --check` réussi. Aucun test local ne vaut validation du fournisseur réel.
- Incrément de cache local uniquement : aucun déploiement ni appel fournisseur réel
  pendant cette étape. La correction des miroirs publics reste dans l'image serveur
  préparée précédemment, avec validation API réelle encore bloquée.
- Après maintenance : auditer les nouveaux chemins/montages, vérifier le catalogue,
  prévisualiser sans acquisition, contrôler les miroirs publics, puis seulement
  réactiver `systemctl --user enable --now home-music-watch.timer`.

## Maintenance bibliothèque et correctif de visibilité — 11 octobre

- L'utilisateur a arrêté Navidrome pour réarranger sa bibliothèque. Ne pas le
  redémarrer ni reprendre les imports avant la fin annoncée de cette maintenance
  et la vérification des nouveaux chemins. Aucun worker actif au dernier contrôle.
- Correctif des miroirs publics : `public=true`, réparation des miroirs privés même
  sans changement de titres, contrôle du résultat API. **118 tests passent** en
  local et dans la construction serveur (Python 3.12).
- Image activée dans le Compose du worker :
  `sha256:f7003b41023be39ef2ecfa540ffd47a07618584aadf226787bf7b9890689331f`.
  Ancien `.env` conservé sous `.env.before-public-20261011` ; release source
  `release-public-20261011`. Sauvegarde préalable et restauration isolée : 11 fichiers
  vérifiés, `backups/auto-20261011T101619Z-12435454`.
- Vérification réelle interrompue par l'indisponibilité de Navidrome, avant la
  mise à jour des miroirs : ne pas déclarer leur visibilité validée sur le serveur.
  Refaire le contrôle public et l'idempotence après la maintenance.

## Documentation et évolutions différées — 11 octobre

- P5.4/P5.5 ajoutées à la roadmap : recommandations et listes YouTube par utilisateur.
  Priorité basse, explicitement différées ; aucune implémentation ni modification serveur.
- Configuration actuelle confirmée en lecture seule : worker connecté en `hugo`,
  Last.fm `macarena3897`, ListenBrainz `Barge9757`. Les miroirs `music` et
  `Discover Weekly — Last.fm` appartiennent à `hugo` et sont actuellement publics.
- Ajout de playlists documenté avec une commande utilisant le chemin absolu du script.
- Installation et restauration documentées mais encore manuelles en plusieurs étapes.
  `make install` installe uniquement l'environnement Python, pas la plateforme.
  P6.5 suit l'objectif de réinstallation en une commande après préparation des entrées.
- Validation de cet incrément : lecture des scripts et procédures, `git diff --check` ;
  aucun code exécutable modifié, pas de nouvelle preuve de restauration complète.

## Diagnostic scrobbling Last.fm — 11 octobre

- Conteneur de production recréé à 06:10 UTC ; `ND_LASTFM_APIKEY` et
  `ND_LASTFM_SECRET` présents, sans exposition de leurs valeurs.
- Les lecteurs NavidromeUI et Arpeggi autorisent le scrobbling. Une session Last.fm
  existe, mais Last.fm répond `error(9): Invalid session key - Please re-authenticate`.
- Intervention requise : désactiver puis réactiver Last.fm dans les paramètres
  personnels du compte Navidrome et autoriser à nouveau le compte Last.fm.
  La clé API seule ne renouvelle pas cette autorisation personnelle.
- Une soumission est journalisée comme abandonnée ; file de reprise vide au contrôle.
  Ne pas promettre de renvoi des écoutes concernées. Validation réelle restante :
  écouter un nouveau morceau après reconnexion et vérifier sa réception Last.fm.
- Diagnostic en lecture seule ; aucun redémarrage ni modification de base.

Mission en cours : playlists surveillées et acquisitions Last.fm déployées, timer
actif et premiers cycles réels validés. P1 parallèle lit maintenant un flux authentifié.
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
- Fournisseur choisi : Last.fm ; clé désormais fournie dans le fichier privé prévu.

## Incrément Discovery / déduplication

- `music_ingest/discovery/` : adaptateurs Last.fm, playlists hebdomadaires ListenBrainz,
  repli local avec artistes explicitement choisis, score détaillé, exclusions,
  correspondances conservatrices, état SQLite indépendant et rapports d'erreur.
- `discover --dry-run` n'écrit rien ; `--apply` ne fait qu'enregistrer les suggestions ;
  `--status` lit le dernier rapport et recontrôle les fichiers. Aucune acquisition.
- MBID d'enregistrement/ISRC prioritaires, tags M4A conservés et relus. Fingerprinting
  de l'ancienne bibliothèque limité à huit fichiers supplémentaires par cycle.
- Configuration personnelle `discovery.toml` préparée et ignorée par Git. Clé API
  fournie et connexion réelle validée ; voir l'incrément ci-dessous.
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

## Validation réelle Last.fm — 2026-10-10

- Clé lue dans le fichier ignoré `state/lastfm-api-key`, permissions 0600. Secret
  jamais affiché, transmis uniquement dans le corps HTTPS, absent des rapports/Git.
- Compte reconnu : 2700 écoutes, 1692 titres ; classement des trois derniers mois
  et favoris Last.fm vides. Ajout du repli sur l'historique complet, provenance explicite.
- Deux cycles `discover --config discovery.toml --apply` réussis : 25 suggestions
  chacun, mêmes identités, 25 lignes candidates uniques, intégrité SQLite `ok`.
- Un premier essai bloqué par le réseau sandbox est conservé comme échec dans
  l'historique. Les deux succès réels suivent ; aucun échec n'est masqué.
- Les 25 suggestions sont indisponibles dans la sandbox (deux fichiers). Leur
  présence sur le serveur n'est pas encore vérifiée. Aucun téléchargement ni
  scrobbling ni création de playlist n'a été effectué.
- Rapport privé : `artifacts/lastfm-recommendations-20261010.md`.
- **101 tests réussis** en local et dans l'image Docker, dont repli historique,
  compte vide et distinction entre erreur API et absence de résultats.
- Image locale `music-ingester:home-music-lastfm` :
  `sha256:a218ae7ceedbb64033513cefc882dbd5bddf44e3dac8520dec1ca01f83aae9cd`.
  Pas de remplacement de l'ingester de production ni d'activation de timer.

## Synchronisation — développement et tests du 10 octobre

- Nouvelle demande : surveiller des IDs YouTube Music et acquérir automatiquement
  les titres manquants ; la restriction précédente aux synthétiques est levée.
- `watch`, `watch_state`, `subsonic` : liste modifiable, cache incrémental, acquisitions
  bornées, reprise/backoff, miroirs avec propriété persistée et sauvegarde des contenus.
- Réutilisation du pipeline et des profils ; nouvel exemple de configuration,
  Compose ponctuel, unités systemd et commandes `music-playlists`/Makefile.
- **113 tests passent en local**, incluant audio synthétique→publication→miroir,
  second passage, changement de nom, source vide, erreurs partielles, interruption
  après création distante, protection des playlists personnelles et cache incrémental.
- API Navidrome réelle authentifiée avec le fichier privé fourni : ping OK, 5 playlists.
- YouTube Music réel : playlist `music`, 202 titres reçus sur 202 annoncés.
- ListenBrainz `Barge9757` répond, aucun résultat hebdomadaire disponible actuellement.
- Serveur : dossiers d'automatisation neufs préparés, sauvegarde avant miroirs vérifiée
  (7 fichiers), `Linger=yes` activé. Activation et preuves dans l'incrément ci-dessous.
- Procédure : `docs/PLAYLIST_SYNC.md`.

## Déploiement et validation réelle — 11 octobre

- **116 tests passent**, en Python local 3.10 et dans la construction serveur Python 3.12.
  Commit initial de l'orchestration : `98d80ed` ; corrections réelles documentées dans DECISIONS.
- Adaptateur corrigé après essais réels : chemins API Navidrome virtuels → lecture
  SQLite RO avec WAL, intersection avec IDs autorisés et fichiers physiques (3611).
  Playlist vide → retrait explicite des indices. Test réel vide puis vide idempotent.
- Déploiement dédié : `/home/hugo/docker/home-music/automation`, image immuable
  `sha256:45f7a4a48be60fdc7ebe947e42e557883684780590323c4cbdda21988662942a`.
  Ancienne release de l'ingester et services Navidrome existants conservés.
- Premier cycle réel : 10 tentatives, 8 fichiers publiés avec tags/pochettes et indexés
  automatiquement. Deux refus YouTube HTTP 403 conservés en erreur, sans contournement.
  Miroirs créés : `music` (28 jouables/202) et `Discover Weekly — Last.fm` (6/25).
- Streaming authentifié sur chaque miroir : HTTP 200 audio/mp4, 16 Kio reçus identiques
  au fichier publié. Second passage sans acquisition : mêmes IDs, `changed=false`,
  aucune duplication. Les 5 playlists originales, leurs 3979 entrées et 4012 annotations
  sont inchangées par rapport au snapshot immédiatement antérieur.
- `home-music-watch.timer` activé et observé : déclenchement automatique à 05:30:59 UTC,
  fin du service à 05:32:55 UTC, code 0. Aucun worker résident entre deux cycles.
  Cycle précédent à 05:27 : miroirs déjà à 33 et 10 titres ; le rattrapage continue.
- Contrôle final à 05:31 UTC : **27 imports terminés, 1 erreur encore en attente**,
  `music` à **38/202**, Last.fm à **15/25** ; intégrité des deux bases `ok`.
  Commandes serveur `add` (ID déjà présent) et `list` validées sans duplication.
  Streaming sur l'instance parallèle : HTTP 200 audio/mpeg, 16 Kio identiques au fichier.
- Quota partagé/rotation entre sources, au plus 10 acquisitions par cycle ; un worker.
  Mesure pendant import : worker 73,02 % d'un CPU et 97,19 Mio ; Navidrome historique
  pendant indexation 115,19 % et 327,5 Mio. Ce sont des échantillons, pas des maxima.
- Sauvegarde des 3 bases et configurations : **11 fichiers vérifiés et restaurés**
  dans un dossier isolé, `backups/auto-20261011T053141Z-a0f2ab66` sur le serveur.
  `home-music-backup.timer` actif, prochain passage quotidien à 04:07 UTC avec jitter.
  Audio non sauvegardé ; aucun nettoyage/suppression automatique activé.
- ListenBrainz : lecture publique réelle vide, puis indisponibilités temporaires,
  indépendantes des succès Last.fm/YouTube. L'utilisateur confirme que Last.fm est
  **déjà relié** à ListenBrainz ; ne pas redemander cette liaison. Aucun titre ListenBrainz
  n'a été inventé ou acquis sous cette provenance en l'absence de résultats.
- Preuves privées serveur : `state/first-preview.json`, `first-cycle.json/.log`,
  `second-cycle.json`, rapports complets dans `state/watch.db`, journal systemd.

## Interventions encore requises

- Tailscale absent du serveur ; autorisation de compte et configuration privée requises.
- Identifiants Navidrome reçus, authentification validée. Essais physiques iPhone
  encore nécessaires pour certifier favoris et écoute hors ligne.
- Last.fm et YouTube fonctionnent avec erreurs partielles signalées. Le premier
  remplissage des 202 titres reste en cours ; certains refus d'accès peuvent persister.
- ListenBrainz configuré et déjà relié à Last.fm, mais pas de playlist hebdomadaire
  disponible lors des validations ; reprise automatique lorsque le fournisseur répond.
- L'instance existante écoute sur toutes les interfaces ; exposition externe inconnue.
- Neuf fichiers référencés absents : retrouver leur origine avant tout scan ou purge.
- Ne pas basculer la production tant que la copie n'est pas validée.

Prochaines actions : surveiller le rattrapage et les 403, valider les résultats
ListenBrainz lorsqu'ils existent, puis rétention/promotion, radios et playlists
locales, scrobbling autorisé, accès privé et essais iPhone. Les accès physiques iOS
et la bascule de production restent non validés. P7 reste suspendue.
