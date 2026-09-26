# Déploiement et exploitation du serveur

Le dépôt fournit une image Docker, une publication GitHub Container Registry
(GHCR), un outil SSH et un timer systemd facultatif. Le serveur reçoit une image
**identifiée par digest**, pas un checkout Git à reconstruire. Chaque déploiement
conserve sa configuration et la version précédente. Les commandes depuis le poste
et depuis GitHub Actions utilisent le même outil.

Aucun serveur n'est configuré automatiquement en clonant le dépôt. Les chemins de
`music-ingest.toml` restent locaux. Le premier déploiement nécessite les vrais
chemins, le compte serveur et une connexion SSH vérifiée.

## Flux de livraison

```text
PR → construction Docker + tests + test Compose hors réseau
main → mêmes contrôles → publication ghcr.io/...@sha256:...
                           ↓
           déploiement SSH depuis le poste ou GitHub Actions
                           ↓
             sauvegarde SQLite + contrôles du conteneur
                           ↓
                  bascule atomique de current
                           ↓
             import manuel, puis timer si validé
```

Le workflow `Test and publish` publie seulement après un push sur `main`, y compris
un merge. Il publie exactement l'image testée, sans reconstruction après le test
Compose. Le digest est affiché dans le résumé du job `publish`. L'image est
actuellement construite pour **Linux amd64** sur le runner Ubuntu hébergé. Un
serveur ARM nécessitera un runner/construction ARM et les mêmes tests avant usage.

Le workflow `Production operation` permet `deploy`, `rollback`, `preview`, `run`,
`doctor` et `status` via **Actions → Run workflow → main**. Il refuse les autres
branches. Pour déployer automatiquement après publication, définir la variable
**de dépôt** `DEPLOY_ON_MAIN=true`. Sans cette variable, le merge publie seulement
l'image. Une livraison automatique issue d'un commit `main` déjà dépassé est
ignorée. Les opérations GitHub sont sérialisées, et le verrou serveur couvre aussi
les commandes du poste et du timer.

## 1. Préparer le serveur une seule fois

Prérequis : Ubuntu/Linux, Python **3.10+**, Docker Engine local et Docker Compose
v2 récent ou v5 (syntaxe `bind.create_host_path` et `run --pull`). L'installation
validée ici utilise un Docker Engine classique, pas un daemon distant ni un
mapping rootless. L'application, Deno, les scripts EJS de yt-dlp et les dépendances
Python/audio sont dans l'image.

Choisir un compte non-root autorisé à utiliser Docker, un dossier de déploiement
et le dossier **réel** de musique partagé avec Navidrome. Le compte SSH doit avoir
le même UID que le processus dans le conteneur ; le GID configuré doit faire partie
de ses groupes. La bibliothèque doit être accessible en écriture avec ces droits,
et Navidrome doit pouvoir lire les nouveaux fichiers.

Depuis une session d'administration, exemple à adapter :

```bash
id YOUR_USER
sudo install -d -o YOUR_USER -g YOUR_GROUP -m 0750 /srv/music-ingest
# La bibliothèque Navidrome doit déjà exister : ne pas en créer une vide ici.
docker version
docker compose version
```

L'outil crée ensuite `state/`, `staging/`, `releases/` et `backups/` sous le dossier
de déploiement. Il refuse une bibliothèque absente. Ne pas placer ce dossier dans
la bibliothèque Navidrome, ni l'inverse. Conserver SQLite sur un stockage local.

Pour une image GHCR privée, connecter **ce compte serveur** au registre avec un
jeton ayant uniquement les droits de lecture nécessaires (`read:packages` et accès
au package). Utiliser `docker login ghcr.io --username YOUR_GITHUB_USER` et saisir
le jeton à l'invite, ou un gestionnaire de secrets avec `--password-stdin`. Ne pas
mettre le jeton dans le dépôt, l'image, le TOML ou les arguments de commande.
Protéger le fichier Docker de credentials ou utiliser un credential helper.

**Périmètre de confiance :** un accès au socket Docker classique permet de prendre
le contrôle de l'hôte. Le compte de déploiement et sa clé SSH sont donc sensibles,
même si le conteneur applicatif tourne sans root. Utiliser une clé dédiée, limiter
l'accès réseau au LAN/VPN ou à des sources choisies, et désactiver ses redirections
SSH (par exemple option `restrict` dans `authorized_keys`). L'application ne reçoit
ni socket Docker ni clé SSH. La clé de déploiement doit permettre la commande
Python distante ; ce mécanisme n'est pas une sandbox pour une clé compromise.

## 2. Configurer le poste

Python **3.11+** suffit. Avec Python 3.10, utiliser le venv du projet qui contient
`tomli` : remplacer `python3` par `.venv/bin/python` dans les commandes suivantes.

```bash
cp deploy/production.example.toml deploy/production.local.toml
```

Modifier les valeurs du fichier copié :

| Champ | Valeur attendue |
| --- | --- |
| `ssh.host` | Alias SSH du poste ou `compte@serveur` joignable |
| `ssh.port` | Port SSH |
| `ssh.identity_file` | Clé dédiée, facultative si déjà configurée dans SSH |
| `ssh.known_hosts` | Fichier d'empreintes vérifiées, facultatif |
| `deployment.root` | Dossier existant appartenant au compte de déploiement |
| `deployment.library` | Chemin existant de musique utilisé par Navidrome |
| `deployment.uid`, `gid` | UID du compte SSH et GID autorisé |
| `deployment.playlist_id` | Identifiant de la playlist publique |
| `deployment.download_timeout` | Délai par téléchargement, 900 secondes par défaut |

Le fichier `*.local.toml` est ignoré par Git et exclu du contexte Docker. On peut
créer plusieurs cibles distinctes pour une sandbox et la production. Chaque cible
doit avoir ses propres dossiers persistants pour isoler son historique.

Vérifier l'empreinte de la clé d'hôte par un canal indépendant (console serveur,
par exemple `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` sur le serveur), puis
l'enregistrer dans `known_hosts`. Un simple `ssh-keyscan` non vérifié n'établit pas
l'identité du serveur. L'outil impose `StrictHostKeyChecking=yes`, le mode SSH sans
invite et l'absence de redirection d'agent/ports.

Récupérer le digest dans le résumé GitHub `publish`, puis vérifier le plan :

```bash
python3 deploy/manage.py --target deploy/production.local.toml --dry-run deploy \
  --image 'ghcr.io/hugo-coisne/music-ingester@sha256:REMPLACER_PAR_64_CARACTERES_HEXA'
```

Le placeholder ci-dessus doit être remplacé : un tag `latest`, un tag de commit ou
un digest mal formé est refusé. `--dry-run` valide les paramètres sans contacter le
serveur ; il ne vérifie pas sa disponibilité ni ses permissions.

## 3. Premier déploiement et validation

```bash
python3 deploy/manage.py --target deploy/production.local.toml deploy \
  --image 'ghcr.io/hugo-coisne/music-ingester@sha256:REMPLACER_PAR_64_CARACTERES_HEXA'
python3 deploy/manage.py --target deploy/production.local.toml doctor
python3 deploy/manage.py --target deploy/production.local.toml preview
python3 deploy/manage.py --target deploy/production.local.toml run
python3 deploy/manage.py --target deploy/production.local.toml status
python3 deploy/manage.py --target deploy/production.local.toml run
```

`deploy` n'importe aucun morceau. Avant d'activer la version, il :

1. Prend le verrou des opérations et celui de l'historique des imports.
2. Refuse un conteneur d'une opération précédente encore présent.
3. Enregistre une nouvelle release et sauvegarde SQLite avec son API de backup,
   puis vérifie l'intégrité de la copie.
4. Télécharge l'image exacte si elle n'est pas déjà disponible par digest en local,
   puis vérifie le format d'état annoncé par son label.
5. Valide Compose, l'écriture avec le vrai UID, les liens physiques nécessaires à
   la publication et SQLite, au moyen de fichiers temporaires supprimés ensuite.
6. Exécute `doctor` et `status` avec cette image sur les volumes réels.
7. Remplace atomiquement le lien `current` uniquement après ces contrôles.

Un échec avant la bascule conserve la version active. Une release incomplète ne
peut pas être sélectionnée pour un rollback. Le journal `operations.jsonl` indique
les résultats. Les contrôles ne contactent pas YouTube : le premier import réel
reste nécessaire pour valider l'accès réseau, la playlist et la détection Navidrome.

Inspecter tags/artwork et Navidrome, puis vérifier que le second import ne crée
rien. Les chemins internes sont toujours `/music`, `/staging` et `/state`.
**Ne pas copier directement une ancienne base locale contenant des chemins hôte** :
ils ne seront pas valides dans le conteneur. Démarrer avec un état dédié (la
bibliothèque est rescannée pour les doublons), ou préparer une migration explicite.

## 4. Rollback et changements de configuration

Même commande depuis le poste, ou opération `rollback` dans GitHub Actions :

```bash
# Rétablit l'image, le TOML, la playlist et le Compose de la version précédente.
python3 deploy/manage.py --target deploy/production.local.toml rollback

# Ou sélectionne explicitement une release validée conservée sur le serveur.
python3 deploy/manage.py --target deploy/production.local.toml rollback \
  --release 20260921T120000Z-012345abcdef

python3 deploy/manage.py --target deploy/production.local.toml status
```

Un rollback crée une nouvelle release à partir de la version sélectionnée, la
recontrôle, puis bascule `current`. Son prédécesseur est la version qu'il remplace :
un nouveau rollback peut donc annuler le précédent. Le rollback ne nécessite pas
de reconstruire une ancienne révision Git. Il peut utiliser l'image conservée par
digest dans Docker sans accès au registre ; si elle a été purgée localement, le
registre doit encore la fournir.

Pour modifier une playlist ou le délai, éditer le TOML cible et exécuter `deploy`
avec le digest souhaité, même identique à l'actuel. Cela crée une configuration
versionnée et réversible. Pour GitHub Actions, mettre à jour également le secret
cible. Les commandes d'exploitation utilisent la configuration **active du serveur**.
Les changements de dossier de stockage ou d'UID/GID sont refusés sur une
installation existante : ils demandent une migration préparée séparément.

**Le rollback applicatif conserve les morceaux et la base courante.** Il ne
supprime pas les imports effectués entre les versions. Le format d'état est
actuellement `1` ; un autre label est refusé. Toute évolution incompatible de
schéma doit fournir sa migration et sa stratégie de retour avant de changer ce
contrat. Ce label est un contrat du projet, pas une preuve de compatibilité d'une
image arbitraire : déployer seulement les images produites par ce dépôt contrôlé.

Les sauvegardes pré-déploiement sont dans `backups/<release>/ingest.db`, avec un
manifeste. Une restauration de données est une opération distincte : arrêter le
timer, attendre la fin de tout conteneur/import, sauvegarder l'état courant, puis
préparer une restauration cohérente de la base **et** des fichiers. Restaurer une
ancienne base seule peut perdre l'historique d'imports déjà publiés. Les backups
locaux ne remplacent pas une sauvegarde externe du serveur et de la musique.
Aucune purge automatique des images, releases ou backups n'est activée ; conserver
au moins toutes les images correspondant aux versions auxquelles on veut revenir.

## 5. Activer GitHub Actions pour le serveur

Configurer l'environnement GitHub **`production`**, limité à `main`. Ajouter ses
secrets :

| Secret | Contenu |
| --- | --- |
| `PRODUCTION_TARGET_TOML` | TOML cible complet, avec un hôte joignable du runner |
| `PRODUCTION_SSH_KEY` | Clé privée dédiée au compte de déploiement |
| `PRODUCTION_KNOWN_HOSTS` | Clé d'hôte préalablement vérifiée (port inclus si nécessaire) |

Le workflow crée des fichiers temporaires mode `0600`, force ces chemins SSH, et
les supprime en fin de job. Un runner personnel doit fournir Bash, SSH et Python
3.11+ et être une machine de confiance.

Par défaut, il s'exécute sur `ubuntu-latest` : ce runner doit pouvoir joindre
l'adresse SSH. Pour un serveur uniquement joignable sur le LAN/VPN, utiliser le
poste pour déployer, ou renseigner la variable **de dépôt** `DEPLOY_RUNNER` avec
un label unique de runner de confiance ayant cet accès. Ne pas ouvrir SSH sur
Internet uniquement pour ce workflow ; ne pas utiliser la production comme runner
chargé d'exécuter les PR. La CI de test reste sur les runners GitHub hébergés.

Protéger `main` : PR, check `test` requis, suppression/push forcé interdits et revue
selon ton organisation. Protéger particulièrement les workflows, Dockerfile et
scripts de déploiement. Un approbateur de l'environnement `production` peut imposer
une validation finale avant toute opération depuis Actions. La disponibilité de
cette protection dépend du plan GitHub et de la visibilité du dépôt :
[documentation des environnements GitHub](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).

Commencer par une opération `status` manuelle et un rollback d'essai. Ensuite,
activer `DEPLOY_ON_MAIN=true` pour le déploiement après merge ; laisser une revue
d'environnement si souhaitée. Pour suspendre ces déploiements, repasser la variable
à `false`. Cela ne suspend pas le timer d'import. Une correction durable après un
rollback passe par une nouvelle PR/revert : sinon un futur merge pourra redéployer
le code que tu viens de retirer.

## 6. Programmer les imports et superviser

Après validation manuelle, adapter les valeurs `User`, `Group` et les deux chemins
`/srv/music-ingest` dans `deploy/systemd/music-ingest.service`, puis installer les
unités sur le serveur avec un compte administrateur :

```bash
sudo install -m 0644 deploy/systemd/music-ingest.service /etc/systemd/system/
sudo install -m 0644 deploy/systemd/music-ingest.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now music-ingest.timer
systemctl list-timers music-ingest.timer
journalctl -u music-ingest.service -n 100 --no-pager
```

Si l'installation se fait sans checkout sur le serveur, transférer uniquement ces
deux fichiers depuis le poste avant `install`. Le timer lance la version désignée
par `current` dix minutes après la fin de l'exécution précédente. Pas de daemon
Python permanent, pas de port applicatif exposé. Le contrôleur refuse une opération
concurrente ; le timer réessaie à son prochain passage. Un déploiement/rollback ne
modifie pas l'activation du timer.

```bash
# Sur le serveur : suspend les futurs imports, laisse le lancement en cours finir.
sudo systemctl disable --now music-ingest.timer
systemctl status music-ingest.service

# Diagnostic depuis le poste.
python3 deploy/manage.py --target deploy/production.local.toml status
python3 deploy/manage.py --target deploy/production.local.toml doctor
```

En cas de coupure SSH/timeout, un conteneur peut survivre à son client. L'opération
suivante le signale par son nom `music-ingest-...` et refuse de continuer. Inspecter
`docker ps -a` et `docker logs NOM`, attendre sa fin ou décider explicitement de
l'arrêter. Ne pas effacer les fichiers de verrou pour contourner un import actif.
Un conteneur arrêté resté présent peut être supprimé après inspection avec
`docker rm NOM`. Le mécanisme applicatif récupère les imports interrompus au
prochain passage.

Les journaux systemd contiennent les sorties des imports programmés ; Actions
conserve la sortie des opérations lancées depuis GitHub. `operations.jsonl`
conserve les résultats sur le serveur. Les alertes externes et la rotation de ce
journal sont à raccorder à la supervision du serveur.

## Validation locale du dispositif

```bash
.venv/bin/python -m unittest discover -s tests -v
docker build --target production -t music-ingester:local .
.venv/bin/python tests/container_smoke.py --image music-ingester:local
systemd-analyze verify deploy/systemd/music-ingest.service deploy/systemd/music-ingest.timer
```

Les tests de releases exercent les bascules, échecs de contrôles, backups SQLite,
rollback avec conservation des imports récents, conflits de verrous et changements
de stockage interdits ; seule l'interface Docker y est simulée. Le test Compose
utilise réellement l'image finale, son UID, son système de fichiers en lecture
seule et ses volumes, avec un morceau synthétique et le réseau désactivé. Il
vérifie la publication et le second passage idempotent. Il ne valide pas le
transport SSH, GHCR, les secrets GitHub ni les chemins réels du serveur.

L'image de base et les actions GitHub sont figées par digest/SHA ; les dépendances
Python sont figées par version. Les paquets Debian restent résolus lors du build :
les builds ne sont donc pas garantis identiques bit à bit. Le rollback repose sur
les images déjà publiées conservées par digest. Prévoir des mises à jour revues de
la base, des actions et des dépendances, suivies des mêmes contrôles.
