# Playlists locales et laboratoire

## Laboratoire reproductible

Depuis le dépôt, avec `.venv` installée (`make install`), FFmpeg et Docker Compose :

```sh
make lab
```

Cette commande crée une instance Navidrome 0.64.0 indépendante sur
`http://127.0.0.1:15435/app/`. Elle génère quatre sons de huit secondes, un compte
`lab` avec mot de passe aléatoire et des états dédiés sous
`artifacts/navidrome-lab-v2/`. Les identifiants restent dans `credentials.json`
(0600), ignoré par Git. Aucun volume de production ni compte externe n'est utilisé.
Les appels HTTP du bootstrap sont limités à la boucle locale. L'image est figée
par digest, musique montée RO, aucun redémarrage automatique du laboratoire.

La commande teste l'indexation, une playlist publique, le retour privé→public,
l'idempotence, le streaming exact, cinq Smart Playlists et trois radios. Les favoris
et écoutes créés sont synthétiques ; les scrobblers externes sont désactivés.
`proof.json` conserve le résultat sans secret. L'amorçage `/auth/createAdmin` est
spécifique à Navidrome 0.64 et isolé dans le script de laboratoire.

```sh
make lab-check   # refaire les vérifications sur les données synthétiques
make lab-stop    # arrêter uniquement le laboratoire, sans supprimer ses fichiers
```

Un dossier non reconnu ou incomplet est refusé. Utiliser `LAB_ROOT=artifacts/nouveau-lab`
pour une nouvelle instance ; arrêter l'ancienne si le même port est utilisé. Un
port différent est disponible via `scripts/navidrome_lab.py up --root ... --port ...`.
La commande de laboratoire n'est pas un installateur/restaurateur de production.
Ne pas modifier son Compose pour y rattacher la bibliothèque réelle.

## Smart Playlists

Les cinq modèles sont dans `config/navidrome/playlists/` :

| Playlist | Sélection |
|---|---|
| Favorites | Favoris du propriétaire, jusqu'à 500 titres |
| Recently Added | 25 ajouts les plus récents |
| Rediscover My Library | 25 titres déjà écoutés, non écoutés depuis 60 jours |
| Weekly Mix | 25 favoris/titres déjà écoutés, sélection conservée une semaine |
| Fresh Discoveries | 25 ajouts récents (14 jours) dans `Managed Singles` |

Ces playlists sont publiques mais reflètent les interactions de leur propriétaire.
Le multiutilisateur personnalisé reste différé. Un compte sans écoutes/favoris ne
reçoit pas un mix inventé. `Weekly Mix` conserve sa sélection une semaine après
évaluation, pas nécessairement du lundi au dimanche.

Avant le déploiement, inventorier les playlists existantes, choisir un dossier neuf
géré dans la bibliothèque, adapter le filtre `filepath` de Fresh Discoveries à
l'emplacement réel et y copier les `.nsp`. Navidrome les importe au scan ; vérifier
le propriétaire, le statut public et le contenu. Aucun modèle n'a encore été installé
dans la bibliothèque de production. Vérifier les fichiers
historiquement manquants avant de valider ce déploiement.

Référence : [Smart Playlists Navidrome](https://www.navidrome.org/docs/usage/features/smart-playlists/).

## Radios à la demande

La commande utilise la configuration `watch.toml` existante ; la simulation est
le défaut et `--apply` crée/met à jour une playlist publique gérée. Exemples locaux :

```sh
.venv/bin/python -m music_ingest radio --config artifacts/navidrome-lab-v2/watch.toml --genre Electronic
.venv/bin/python -m music_ingest radio --config artifacts/navidrome-lab-v2/watch.toml --genre Electronic --apply
.venv/bin/python -m music_ingest radio --config watch.toml --artist-id ID_ARTISTE --apply
.venv/bin/python -m music_ingest radio --config watch.toml --song-id ID_MORCEAU --limit 25 --apply
```

Les IDs sont ceux de Navidrome, disponibles dans les liens de son interface ou son
API. La version mise à jour du script serveur fournit aussi
`./music-playlists radio --genre Rock --apply`. Image et script sont déployés depuis
la reprise du 11 octobre : `Radio — Rock`, 25 morceaux présents, publique et
idempotente, a été vérifiée sur la production 0.64.2. Le genre Electronic était
absent du catalogue réel ; aucune radio vide n'a été créée pour cet essai.

Les radios par artiste et morceau interrogent `getSimilarSongs2` avec l'ID artiste ;
en cas d'indisponibilité elles utilisent les titres locaux du même artiste (au plus
dix albums examinés). La radio genre utilise `getSongsByGenre`, au plus 500 candidats.
Seuls les IDs accessibles au compte et liés à un fichier physique sont retenus.
Le résultat explique l'origine de chaque titre, sans score de similarité inventé.

Le morceau de départ reste premier. À ensemble de candidats identique, l'ordre est
stable pendant la semaine UTC. L'API de similarité peut renvoyer un échantillon
différent sur une grande bibliothèque : ce n'est pas un cache hebdomadaire de radio.
Aucun téléchargement n'est lancé par cette commande. Une réponse vide ne supprime
pas la radio précédente. Les protections de propriété et sauvegardes du miroir sont
réutilisées, avec un rapport conservé dans `watch.db` (`radio_runs`) sous le même verrou
que le worker. La simulation travaille sur une copie SQLite en mémoire.

Référence : [getSimilarSongs2 OpenSubsonic](https://opensubsonic.netlify.app/docs/endpoints/getsimilarsongs2/).
