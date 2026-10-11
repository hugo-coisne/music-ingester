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
La clé est lue dans un fichier privé ignoré ou l'environnement ; requêtes POST
pour éviter les secrets dans les URLs, compatibilité validée sur l'API réelle.
L'adaptateur ListenBrainz utilise les playlists publiques createdfor, sans imposer
les endpoints de recommandation expérimentaux. Aucun compte n'est créé.
Les scores additionnent des contributions traçables ; aucune prédiction IA.
Les références sans preuve locale restent indisponibles et les ambiguïtés explicites.
Pas de timer activé avant validation des comptes et du cycle réel.

## Last.fm : compte sans écoutes récentes

Le classement sur trois mois était vide, malgré un historique de 2700 écoutes.
Repli sur `period=overall` uniquement lorsque le classement récent est vide ;
une erreur API conserve son statut d'échec. Le motif de recommandation indique la
période utilisée. Pas de graines artificielles ni de modification du compte Last.fm.
Validation réelle : 25 suggestions, deux cycles sans doublon. La planification
serveur attend encore le raccordement à la bibliothèque réelle et OpenSubsonic.

## Surveillance et acquisition — nouvelle demande du 10 octobre

La demande explicite d'import automatique des playlists YouTube Music et des
recommandations remplace la restriction antérieure aux essais synthétiques.
Pas de cookies, DRM ou contrôles d'accès contournés. Les échecs restent des échecs.
Le compte ListenBrainz fourni est `Barge9757` ; ses playlists hebdomadaires publiques
étaient vides au premier essai réel. Last.fm reste `macarena3897`.

Le module `watch` réutilise le pipeline existant, avec snapshots des sources pour
éviter qu'une source modifiée entre deux lectures produise un import incohérent.
Liste d'IDs texte, une tâche systemd toutes les 15 minutes, renouvellement des
recommandations tous les sept jours, queue/backoff et cache de tags en SQLite.
Les erreurs d'un fournisseur n'effacent pas les derniers résultats corrects.

Les miroirs OpenSubsonic appartiennent à un compte et à un jeton persisté avant
création ; jamais de rapprochement par simple nom avec les playlists personnelles.
Une création interrompue est reprise par nom temporaire unique. Le contenu antérieur
est sauvegardé dans le journal avant modification. Aucun fichier musical n'est
supprimé quand une piste quitte la source. Les nouvelles acquisitions restent
conservées ; la rétention temporaire/promotion est encore une tâche distincte.

Le worker monte la bibliothèque existante RO et uniquement `Managed Singles` RW.
L'ancienne release d'ingestion reste récupérable, sans planificateur actif observé.
Le réseau hôte sert seulement à joindre Navidrome sur 127.0.0.1 ; le worker n'écoute
sur aucun port. HTTP n'est accepté que sur la boucle locale, secrets en corps POST.
Pas de scan complet forcé de l'ancienne bibliothèque ; le rapport attend que le
catalogue Navidrome confirme l'indexation des fichiers publiés.

## 11 octobre — validation OpenSubsonic et chemins virtuels

L'essai réel révèle que les chemins API Navidrome 0.64 sont virtuels : six seulement
correspondaient aux noms sur disque. L'adaptateur optionnel lit `media_file(id,path)`
pour la bibliothèque configurée dans SQLite RO, avec le WAL, puis intersecte les IDs
avec le catalogue OpenSubsonic autorisé. Résultat confirmé : 3611 fichiers existants,
neuf absents exclus. Cette lecture du schéma est isolée et échoue explicitement si
le schéma change. Elle ne modifie pas Navidrome et ne remplace pas son API de playlists.

Une playlist vide nécessite `updatePlaylist` avec les indices à retirer : la requête
`createPlaylist` sans titres est un no-op dans Navidrome. Le test d'intégration a
détecté cette différence ; fixture corrigée et test réel vide→vide idempotent réussi.
Le quota d'acquisition est partagé entre sources et la priorité tourne à chaque
cycle pour éviter qu'une longue liste prive les recommandations de téléchargements.
