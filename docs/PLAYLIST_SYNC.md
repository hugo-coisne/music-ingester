# Playlists surveillées et recommandations

`music_ingest watch` réutilise le moteur d'import existant. Il lit une liste d'IDs
YouTube Music, importe les titres absents et crée des miroirs publics dans le compte
Navidrome configuré. Les identifiants et mots de passe ne figurent jamais dans les
URLs ; les requêtes OpenSubsonic utilisent POST. HTTP est limité à la boucle locale.

## Utilisation sur le serveur

Depuis une session SSH sur le serveur, ajouter une playlist en une commande :

```sh
/home/hugo/docker/home-music/automation/music-playlists add 'PL_ID_DE_LA_PLAYLIST'
```

Prendre la valeur du paramètre `list=` dans l'URL YouTube Music, jusqu'au prochain
`&` s'il existe. Par exemple, `https://music.youtube.com/playlist?list=PL_EXEMPLE`
donne l'ID `PL_EXEMPLE`. Le prochain cycle automatique prend cet ajout en compte ;
aucun redémarrage n'est nécessaire. Les acquisitions restent soumises aux quotas
et à la disponibilité de la source, le miroir peut donc se remplir sur plusieurs cycles.

Actuellement, la liste est unique et les miroirs appartiennent au compte `hugo`.
Les miroirs `music` et `Discover Weekly — Last.fm` ont été observés publics dans
Navidrome. La gestion personnelle par utilisateur est prévue en P5.4/P5.5, différée.

Le déploiement de cette installation utilise
`/home/hugo/docker/home-music/automation`. Depuis une session SSH sur le serveur :

```sh
cd /home/hugo/docker/home-music/automation
./music-playlists add PL_ID_DE_LA_PLAYLIST
./music-playlists list
./music-playlists run
./music-playlists logs
./music-playlists status
./music-playlists report   # détail de chaque titre, y compris les absents
```

On peut aussi éditer `playlists/youtube.txt` : un ID par ligne, commentaires `#`
acceptés. `remove ID` arrête la surveillance ; aucun fichier ni ancienne playlist
Navidrome n'est supprimé. La prochaine exécution prend la nouvelle liste en compte.
Le script `add` rend uniquement le dossier de la liste modifiable dans son conteneur.

Le timer `home-music-watch.timer` vérifie toutes les 15 minutes, avec un décalage
aléatoire maximal d'une minute. Les recommandations sont renouvelées tous les sept
jours puis leurs acquisitions incomplètes sont reprises lors des cycles suivants.
Il n'y a aucun serveur Python résident. Le mode persistant systemd rattrape un arrêt
du serveur ; `loginctl show-user hugo -p Linger` doit indiquer `yes` pour fonctionner
sans session SSH ouverte.

```sh
systemctl --user status home-music-watch.timer
systemctl --user list-timers home-music-watch.timer
systemctl --user stop home-music-watch.timer   # suspendre les futurs cycles
# Attendre la fin du cycle courant avant une sauvegarde du journal du worker.
systemctl --user start home-music-watch.timer
```

## Ce que signifie « miroir »

- Nom exact de la source et ordre des morceaux conservés ; un morceau répété n'est
  inclus qu'une fois, conformément à l'invariant d'absence de doublons.
- Seuls les morceaux disposant d'un fichier existant **et** d'un ID Navidrome
  vérifié sont ajoutés. Un téléchargement ou une indexation en attente apparaît
  dans le rapport, jamais comme une piste jouable fictive.
- Une erreur de lecture de la source ne vide pas la playlist existante. Une source
  effectivement vide peut vider son miroir, sans supprimer les fichiers.
- Les playlists personnelles, même de même nom, ne sont pas adoptées/modifiées.
- Les miroirs gérés sont rendus publics à leur finalisation et maintenus publics
  lors des synchronisations. Un miroir passé manuellement en privé sera republié
  au prochain cycle, même si ses morceaux n'ont pas changé. Le statut public est
  relu via l'API avant de considérer la synchronisation réussie.
- Le journal SQLite attribue un marqueur unique à chaque miroir avant sa création.
  Une interruption après création est récupérable. Le contenu antérieur de chaque
  miroir modifié est conservé dans `playlist_backups`.
- Une modification manuelle du marqueur de commentaire protège la playlist contre
  les écritures suivantes ; le rapport signale alors un conflit. Restaurer le journal
  sauvegardé est préférable à le réinitialiser, ce qui perdrait la propriété des miroirs.

## Acquisition et erreurs

Simulation par défaut en CLI, double condition `--apply` et
`acquisition_enabled=true` pour les téléchargements. Dix tentatives maximum par cycle,
un téléchargement à la fois, 100 Mio maximum par fichier, réserve de 2 Gio par défaut.
La limite yt-dlp est complétée par une vérification du fichier terminé ; l'estimation
de taille de la source n'est pas une garantie de quota strict pendant le transfert.
Le conteneur est limité à 0,75 CPU et 768 Mio, avec timeout individuel configuré.

Les erreurs sont réessayées avec attente de 15 minutes puis un doublement jusqu'à
24 heures. Les succès ne sont pas retéléchargés. Les erreurs partielles restent dans
le rapport et ne font pas annuler les succès. Aucune suppression automatique de
musique n'est activée ; favoris et fichiers permanents sont conservés.

Les recommandations Last.fm alimentent `Discover Weekly — Last.fm`. ListenBrainz
alimente `Weekly Exploration — ListenBrainz` et `Weekly Jams — ListenBrainz` lorsque
le compte possède ces résultats. Un fournisseur vide n'est pas remplacé par des
recommandations inventées. Les suggestions, leur provenance et leur résolution sont
conservées dans le journal. Les recherches YouTube Music exigent titre et artiste
exacts, respectent durée/album connus et refusent plusieurs correspondances possibles.
Un identifiant MusicBrainz non vérifié n'est pas recopié sur un résultat YouTube.

Le connecteur ne fournit aucun cookie ni mécanisme de contournement des DRM ou des
contrôles d'accès. Les sources non accessibles ou les versions ambiguës restent
signalées. La demande d'automatisation du 10 octobre remplace la limitation antérieure
aux essais synthétiques ; elle ne garantit pas la disponibilité de tout le catalogue.

## Installation reproductible

Cette procédure est manuelle : il n'existe pas encore de commande unique qui
réinstalle l'ensemble de la plateforme ou restaure une installation perdue.
Voir aussi `INSTALL.md` et `BACKUP_RESTORE.md` ; simplification suivie en P6.5.

1. Construire `docker build --target production -t music-ingester:watch .` ; les
   tests sont obligatoires dans la construction. Relever l'ID `docker image inspect`.
2. Créer un dossier privé pour `config`, `state`, `staging`, `backups`, `playlists`.
   Créer un dossier musical neuf dédié `Managed Singles`, dans la bibliothèque lue
   par Navidrome. Ne pas modifier la base ou les fichiers existants.
3. Copier `compose.watch.yml`, `scripts/music-playlists` (exécutable) dans ce dossier.
   Préparer `.env` avec `WATCH_IMAGE` (ID immuable), `WATCH_ROOT`, `MUSIC_ROOT`,
   `MANAGED_MUSIC_ROOT`, `WATCH_NAVIDROME_DATA`, `MUSIC_UID`, `MUSIC_GID` ; les chemins doivent exister.
4. Adapter `watch.example.toml` et `music-ingest.toml` dans `config/`. Dans le conteneur :
   musique de référence `/music` RO, bibliothèque gérée `/music/Managed Singles` RW,
   staging `/staging`, bases `/state`, liste `/playlists/youtube.txt`. Configurer
   `navidrome.catalog_db="/navidrome/navidrome.db"` et l'ID de bibliothèque correspondant.
5. Mettre les identifiants dans `config/navidrome-credentials.json` (0600), JSON
   `{"username":"…","password":"…"}`. Clé Last.fm dans `config/lastfm-api-key` (0600).
   Renseigner les noms publics ; ListenBrainz ne nécessite pas de token pour lire ses
   playlists publiques. Le scrobbling est une configuration séparée.
6. Sauvegarder Navidrome avec `python -m music_ingest.backup create`, puis vérifier et
   restaurer dans un dossier neuf. `./music-playlists preview` doit fonctionner avant
   le premier import. Contrôler ensuite les rapports et la lecture des morceaux.
7. Remplacer `@WATCH_ROOT@` dans `deployment/systemd/home-music-watch.service`, placer
   les deux unités dans `~/.config/systemd/user/`, lancer `systemctl --user daemon-reload`,
   `loginctl enable-linger`, puis `systemctl --user enable --now home-music-watch.timer`.

Les anciens services continuent de fonctionner. L'ingester historique n'est pas
remplacé ; ne pas planifier deux ingesters qui acquièrent les mêmes playlists.
Les vidéos et leurs volumes ne participent pas à ce déploiement.

## Développement et diagnostic

Copier `watch.example.toml` en `watch.toml` et la liste exemple en
`config/youtube-playlists.txt`. Conserver le profil sandbox et désactiver Navidrome
pour les premiers essais locaux. `make playlist-add PLAYLIST=…`, `make playlist-list`,
`make watch-preview`, `make watch`, `make watch-status` sont disponibles.

```sh
.venv/bin/python -m music_ingest watch status --config watch.toml --summary
.venv/bin/python -m music_ingest watch run --config watch.toml --apply --refresh-recommendations
make test
```

`--refresh-recommendations` force la lecture des fournisseurs sans contourner
l'attente des acquisitions en échec. Les statuts distinguent `playable`,
`awaiting_index`, `queued_limit`, `backoff`, `download_failed`,
`unresolved_or_ambiguous`, `source_unavailable`, `insufficient_space`.
Le catalogue et les tags sont vérifiés avec les chemins réels ; les tags inchangés
sont mis en cache par taille/date/inode. Aucun fingerprinting massif.

### Particularités de Navidrome 0.64 validées sur le serveur

Le champ `path` OpenSubsonic est un chemin virtuel dérivé des tags : il ne suffit pas
à retrouver un fichier physique. `navidrome.catalog_db` pointe donc vers
`/navidrome/navidrome.db` ; le dossier `/data` existant est monté **en lecture seule**
avec son WAL, via `WATCH_NAVIDROME_DATA` dans `.env`. Le worker ne lit que `id,path` pour
`library_id` configuré puis intersecte avec les IDs accessibles au compte par API.
Une évolution de schéma échoue explicitement au lieu de deviner les chemins.
La base n'est jamais ouverte avec `immutable=1` ni écrite par le worker.

Pour vider un miroir, `updatePlaylist(songIndexToRemove=…)` est nécessaire :
`createPlaylist` sans `songId` conserve ses anciennes pistes sur cette version.
Ces deux différences ont été détectées et corrigées par essais réels sur l'instance
parallèle. Le catalogue vérifié contient 3611 fichiers physiques ; les neuf chemins
historiquement absents ne deviennent pas artificiellement jouables.

API de référence : [création/remplacement de playlist](https://opensubsonic.netlify.app/docs/endpoints/createplaylist/),
[mise à jour](https://opensubsonic.netlify.app/docs/endpoints/updateplaylist/),
[catalogue paginé](https://opensubsonic.netlify.app/docs/endpoints/search3/),
[POST](https://opensubsonic.netlify.app/docs/extensions/formpost/).
