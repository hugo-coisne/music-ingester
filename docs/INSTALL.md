# Installation et validation

## Portée de la procédure actuelle

La remise en place est documentée mais nécessite plusieurs étapes : Navidrome
ci-dessous, worker et timers dans [PLAYLIST_SYNC.md](PLAYLIST_SYNC.md), sauvegardes
et restauration dans [BACKUP_RESTORE.md](BACKUP_RESTORE.md). Il n'existe pas encore
d'installateur complet en une commande ; cet objectif est suivi en P6.5.
`make install` ne prépare que l'environnement Python local ; `make start` suppose
déjà disponibles les configurations, chemins, données et image Docker.

En cas de perte de l'installation, conserver hors du serveur le dépôt, les
configurations/secrets, les sauvegardes cohérentes des bases (dont `watch.db` pour
la propriété des miroirs) et la musique. Les sauvegardes automatiques actuelles
n'incluent pas les fichiers audio. Les restaurations isolées validées ne constituent
pas encore un test de réinstallation complète sur une machine vierge.

## Poste de développement

Python 3.10+ ; FFmpeg/ffprobe, Chromaprint et Deno sont utilisés par l'ingester
historique. Voir README pour leurs versions. `make install`, puis `make test` et
`make doctor`. Les dépendances sont figées dans `requirements.lock`.
Le module backup n'utilise que la bibliothèque standard Python.

## Nouvelle instance Navidrome

Ne pas utiliser les données live comme `NAVIDROME_DATA`. Préparer une sauvegarde
avec `python3 -m music_ingest.backup create` (BACKUP_RESTORE.md), puis :

```sh
python3 scripts/prepare_navidrome.py /path/to/backup /path/to/new/preview/data
cp .env.example .env
# Renseigner les chemins réellement audités, UID/GID et le port dans .env.
docker compose --env-file .env -f compose.music.yml config --quiet
docker compose --env-file .env -f compose.music.yml up -d --pull never navidrome
```

L'image doit déjà être disponible. Sur un nouvel hôte, télécharger le digest fixé
avec `docker compose --env-file .env -f compose.music.yml pull navidrome` après
vérification des chemins. Le Compose refuse de créer implicitement les montages.

Instance déjà déployée le 2026-10-10 : serveur `hugo@192.168.1.111`, fichiers dans
`/home/hugo/docker/home-music/repo-p1-20261010`, données indépendantes sous
`/home/hugo/docker/home-music/preview/data`. Elle répond seulement sur la boucle locale.
Pour un essai navigateur depuis le poste :

```sh
ssh -N -o StrictHostKeyChecking=yes -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:14534:127.0.0.1:4534 hugo@192.168.1.111
```

Ouvrir `http://127.0.0.1:14534/app/`, se connecter avec son compte Navidrome existant,
écouter un morceau, vérifier les pochettes et playlists. Les favoris modifiés dans
la copie ne sont pas synchronisés vers l'ancienne instance : ne pas l'utiliser au
quotidien avant bascule. Les comptes n'ont pas été réinitialisés.

Scans, plugins, partage et services externes sont désactivés dans cette instance
de validation. Elle n'est pas encore une installation musicale automatisée.
Les options suivent la [configuration officielle](https://www.navidrome.org/docs/usage/configuration/options/)
et les [volumes Docker officiels](https://www.navidrome.org/docs/installation/docker/).

## Accès privé et iPhone (à valider)

La connexion Tailscale exige un compte autorisé et une décision réseau ; aucune
installation, règle de pare-feu ou redirection publique n'a été effectuée.
Après configuration privée, tester Amperfy et Arpeggi avec un compte non administrateur :
catalogue, un morceau natif sans transcodage, favori, playlist, téléchargement local,
mode avion, reconnexion et synchronisation. Vérifier les offres iOS disponibles
et gratuites au moment de l'installation. SubStreamer reste un client à évaluer.
La validation sur iPhone ne peut pas être remplacée par les tests serveur.
