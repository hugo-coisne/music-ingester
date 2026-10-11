# Restauration guidée en isolation

Une commande restaure et valide **Navidrome** dans un nouveau dossier et un projet
Compose distinct. Elle conserve l'ensemble du snapshot, dont les états de l'ingester,
mais ne réactive ni les acquisitions, ni les timers, ni les scrobblers. La bascule de
production et la remise en service complète du worker restent des étapes séparées.

## Préparer les entrées

Sur la machine qui héberge Docker, disposer de Python et des dépendances du dépôt
(`make install`), Docker Compose, d'un snapshot créé par `music_ingest.backup`, et
des fichiers musicaux restaurés séparément ou toujours disponibles.
Copier `deployment/recovery.example.json` en `recovery.local.json` (ignoré par Git)
et renseigner les chemins réels :

```json
{
  "backup": "/sauvegardes/snapshot-verifie",
  "destination": "/home/utilisateur/home-music-restaure",
  "music": "/media/musique",
  "port": 15436
}
```

Les chemins relatifs sont résolus depuis ce fichier de configuration. La destination
doit être neuve, séparée de la musique, du snapshot et de l'ancien dossier Navidrome.
Le port choisi doit être disponible sur la boucle locale.

Le snapshot doit contenir une base dont le nom source est `navidrome.db` et le fichier
privé `navidrome-credentials.json` (ou `credentials.json`) du compte de validation.
Ce fichier doit être au format `{"username":"…","password":"…"}` et sauvegardé
avec les configurations. Ses valeurs ne sont pas affichées. En cas de plusieurs
entrées candidates, préciser `database_entry` et/ou `credentials_entry` avec leur
nom exact dans `manifest.json`, par exemple `000-navidrome.db`.

## Une commande pour restaurer

```sh
make recover RECOVERY_CONFIG=recovery.local.json
```

Équivalent :

```sh
.venv/bin/python -m music_ingest recover --config recovery.local.json --apply
```

La prévisualisation est disponible avec `make recovery-preview` : elle vérifie les
entrées sans créer de dossier, appeler Docker ou contacter Navidrome.

Le processus :

1. Vérifie les sommes SHA-256, l'intégrité SQLite, les droits des identifiants et
   l'existence des morceaux référencés. Refuse les chemins qui sortent du montage.
2. Vérifie l'espace disponible et l'absence de conteneur utilisant déjà ce nouveau
   projet. Restaure toutes les entrées dans `destination/archive/` avec droits privés.
3. Prépare une copie de travail de Navidrome dans `destination/data/` et un Compose
   limité à `127.0.0.1`, musique RO, scans/plugins/scrobblers désactivés. Les anciens
   réglages sont archivés ; ils ne sont pas exécutés automatiquement.
4. Démarre Navidrome 0.64.0 avec le digest testé, en téléchargeant l'image si nécessaire.
5. Compare comptes, propriétés utilisateur, annotations, playlists, associations,
   catalogue, écoutes et file de scrobbling au snapshot. Vérifie l'authentification,
   les fichiers accessibles et les premiers 16 Kio d'un flux audio natif.

Le rapport sans secrets est `destination/recovery-result.json`. Seul le statut
`verified` atteste que les contrôles ont réussi. Une restauration réussie laisse
l'instance accessible localement pour vérification interactive.

## Portée et reprise après erreur

Cette version prend en charge une bibliothèque Navidrome montée à `/music`, avec
des chemins de fichiers relatifs. Une autre arborescence, une base d'une version
incompatible ou un fichier absent provoque un refus explicite. Aucune réécriture
automatique des chemins dans SQLite. Les installations avec réglages particuliers
doivent être examinées avant de prétendre à une restauration complète.

Les fichiers audio ne sont pas contenus dans les snapshots de bases : une perte
du disque exige aussi une sauvegarde indépendante de la musique. Les caches de
pochettes non inclus dans le snapshot ne sont pas restaurés par cette commande.

Sur échec de validation ou interruption Ctrl-C, la commande tente d'arrêter
uniquement sa nouvelle instance. Les fichiers restaurés et l'archive sont conservés.
Le rapport indique si l'arrêt a réussi. Après arrêt brutal du processus ou du système,
vérifier manuellement l'état ; l'absence de rapport `verified` n'est pas un succès.
Un dossier existant est toujours refusé : corriger le problème et choisir une autre
destination pour un nouvel essai, sans effacer les données du premier.

Pour arrêter une copie créée :

```sh
docker compose -f /chemin/destination/compose.json stop
```

Pour reprendre le worker après validation, conserver impérativement `watch.db`,
ses jetons de propriété et les IDs des playlists restaurées. Réauditer les chemins
absolus de `ingest.db`, adapter les configurations, prévisualiser puis valider un
cycle avant réactivation des timers. Cette partie n'est pas encore automatisée.

## Preuve reproductible sur audio synthétique

Avec le laboratoire de `make lab` disponible :

```sh
.venv/bin/python tests/recovery_smoke.py --work artifacts/nouvel-exercice-restauration
```

Le script crée un snapshot cohérent de la base active, du journal des miroirs,
des identifiants et des configurations. Il appelle réellement la CLI de restauration,
contrôle que `watch.db` et l'archive sont identiques, puis arrête la copie de test.
Il ne remplace pas un exercice sur la bibliothèque réelle après sa maintenance.
