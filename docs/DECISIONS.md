# Décisions

## 2026-10-10 — Conservation du dépôt

Le package reste à la racine. Déplacer vers `apps/music-ingest` casserait les chemins
par défaut, l'image et les déploiements historiques sans bénéfice immédiat.
Les dossiers `docs`, `config`, `scripts`, `deployment` complètent le dépôt existant.
`deploy/` et ses releases restent utilisables. Pas de réécriture ni de nouvelle base lourde.

## Validation parallèle avant bascule

Réutiliser exactement le digest Navidrome du serveur (0.64.0), une copie SQLite
cohérente et le montage musique `/music` inchangé. La copie possède son propre
`/data` ; port 4534 sur 127.0.0.1, projet Compose distinct. Pas de migration de schéma
en même temps qu'une migration d'infrastructure. Pas de scan ou scrobbling automatique
sur la copie de validation. La production reste sur 4533 jusqu'à une bascule autorisée.

## Sauvegarde sans interruption

API SQLite backup : inclut les transactions validées du WAL. Copie de fichier brute
insuffisante (WAL Navidrome observé ~169 Mo). SHA-256 et integrity_check pour chaque
base ; restauration exclusivement dans un nouveau dossier. Permissions 0700/0600.
Ce n'est pas une sauvegarde des 16,9 Go de musique. Une copie supplémentaire du
snapshot serveur a été transférée sur le poste puis vérifiée.

## Séparation des responsabilités et stockage

Navidrome ne télécharge et ne déplace rien. L'ingester garde sa base séparée.
Lidarr n'écrira que les albums dans un dossier distinct des singles et découvertes.
Conserver les chemins réels actuels ; pas de renommage prématuré `media-data`.
Un worker, tâches systemd ponctuelles, SQLite ; aucun LLM ni GPU ni API payante.

## Sécurité du profil sandbox

Les chemins écrits par sandbox doivent être disjoints des chemins production du
TOML, même après overrides et résolution des liens symboliques. Les champs sandbox
omis reçoivent des chemins sandbox. Cette protection ne remplace pas des montages
Docker limités ni ne peut deviner une production extérieure à la configuration.
Le nettoyage effectif partage le verrou de l'import pour éviter les courses.

## Accès distant

Préparer Tailscale, sans installer/authentifier ou modifier le pare-feu automatiquement.
La disponibilité gratuite et les clients iOS seront vérifiés lors de cette étape.
L'écoute sur toutes les interfaces ne prouve pas une exposition Internet : audit
du reverse proxy, du pare-feu et des redirections routeur nécessaire avant conclusion.

## Discovery : développement sans acquisition

L'utilisateur choisit Last.fm et n'autorise pour l'instant que l'audio synthétique
pour les nouveaux imports. Discovery collecte/enregistre seulement des suggestions.
La clé sera lue dans un fichier privé ignoré ou l'environnement ; requêtes POST
pour éviter les secrets dans les URLs, compatibilité réelle encore à valider.
L'adaptateur ListenBrainz utilise les playlists publiques createdfor, sans imposer
les endpoints de recommandation expérimentaux. Aucun compte n'est créé.
Les scores additionnent des contributions traçables ; aucune prédiction IA.
Les références sans preuve locale restent indisponibles et les ambiguïtés explicites.
Pas de timer activé avant validation des comptes et du cycle réel.
