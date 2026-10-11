# Music Discovery — premier incrément

Le module collecte des suggestions, les rapproche des fichiers locaux, calcule un
score explicable et peut enregistrer le résultat dans sa propre SQLite. Il n'acquiert
aucun contenu, ne crée pas encore de playlist Navidrome et ne supprime aucun fichier.

```sh
cp discovery.example.toml discovery.toml
# Modifier les fournisseurs, noms publics et chemins. discovery.toml est ignoré par Git.
make discover-preview   # appels de lecture seulement, aucune écriture locale
make discover          # conserve candidats et rapport SQLite ; aucun téléchargement
make discovery-status  # dernier rapport, sans appel externe
```

Le fichier local de cette session est configuré pour le compte Last.fm fourni par
l'utilisateur. La connexion réelle a été validée le 2026-10-10 : deux cycles ont
conservé les mêmes 25 suggestions, sans doublon ni erreur. Pour une réinstallation,
obtenir sa clé depuis
[Last.fm API](https://www.last.fm/api/account/create), puis enregistrer seulement
sa valeur dans `state/lastfm-api-key`, permissions `chmod 600 state/lastfm-api-key`.
Ne pas fournir le secret dans le chat. `LASTFM_API_KEY` dans l'environnement est
également accepté et prioritaire. Aucune clé n'est stockée dans le rapport ou l'URL.

## Adaptateurs et classement

- Last.fm : [top tracks](https://www.last.fm/api/show/user.getTopTracks) sur trois mois
  (repli sur l'historique complet si ce classement est vide)
  et [favoris](https://www.last.fm/api/show/user.getLovedTracks), puis
  [titres similaires](https://www.last.fm/api/show/track.getSimilar). Maximum dix
  graines, 25 voisins chacune. Score normalisé `match / (1 + match)`.
- ListenBrainz : [playlists createdfor](https://listenbrainz.readthedocs.io/en/latest/users/api/playlist.html),
  sélection des dernières Weekly Exploration et Weekly Jams dans les 25 métadonnées
  retournées, puis récupération des pistes. Score de rang `1 / (1 + position/25)`.
  Pas d'endpoint expérimental obligatoire. Pagination complète encore à ajouter.
- Local : morceaux réels d'artistes explicitement sélectionnés dans `seed_artists`,
  score 0,5. Ce repli ne prétend pas connaître les favoris ou écoutes Navidrome :
  l'adaptateur OpenSubsonic personnel reste à implémenter.

Le score final somme les meilleurs scores par fournisseur multipliés par les poids
configurés. Répéter une suggestion dans une source n'augmente pas son poids.
Les motifs et contributions sont conservés. Maximum 25 résultats par défaut.
Les exclusions portent sur l'artiste ou `artiste - titre` normalisé. Les qualificatifs
live/remix ne sont pas supprimés. MBID d'enregistrement et ISRC sont normalisés ;
des identifiants contradictoires restent séparés. Une ambiguïté de durée sous une
même identité est signalée `ambiguous`, sans fichier jouable attribué.

`available` exige un fichier existant avec identifiant fort compatible, ou artiste,
titre et durée compatibles. Sans cette preuve : `unavailable`. Le statut recontrôle
l'existence du fichier. Cela ne prouve pas encore son indexation ni son ID Navidrome.
Les rapports restent distincts des playlists personnelles et des acquisitions.

## Résilience et limites connues

Délais HTTP 3 s connexion / 15 s lecture, trois essais maximum sur panne réseau,
429 ou 5xx ; backoff 1 puis 2 secondes. TLS vérifié, redirections refusées, réponse
limitée à 2 Mio. Une panne de fournisseur conserve les résultats des autres ; le
code de sortie est non nul pour permettre le diagnostic du fonctionnement dégradé.
Les erreurs brutes susceptibles de contenir des credentials ne sont pas enregistrées.

Les adaptateurs ont des tests simulés. Last.fm utilise un corps POST pour éviter
les clés dans les URLs : cette méthode et les recommandations ont aussi été
validées sur l'API réelle avec la clé utilisateur. ListenBrainz reste validé
uniquement avec des fixtures. Le cache
actuel est l'historique des candidats/rapports ; il ne dispense pas encore des appels
HTTP répétés. Une évolution d'identité texte→MBID peut laisser un ancien candidat
dans l'historique ; les playlists futures devront utiliser le rapport du cycle et
une réconciliation d'identités, pas toutes les anciennes lignes.

Le compte testé ne disposait d'aucune écoute récente sur trois mois ni de favoris
Last.fm, mais son historique complet contenait 2700 écoutes. Le repli utilise cet
historique réel ; sa provenance `period=overall` figure dans chaque suggestion.
Un compte sans aucune écoute ne produit toujours aucun résultat. Une erreur API
n'est pas interprétée comme un historique vide.

Les 25 résultats du test sont `unavailable` dans les deux fichiers de la sandbox.
Cela ne prouve pas leur absence de la bibliothèque complète du serveur. Le rapport
personnel se trouve sous `artifacts/lastfm-recommendations-20261010.md`, ignoré par Git.

## Planification préparée

Unités utilisateur sous `deployment/systemd/`, non installées. Adapter le checkout
`%h/home-music`, créer `~/.config/home-music/secrets.env` privé (peut rester vide si
la clé est lue depuis un fichier), puis tester manuellement. Après validation réelle :

```sh
systemctl --user link /absolute/repo/deployment/systemd/music-discovery.service
systemctl --user link /absolute/repo/deployment/systemd/music-discovery.timer
systemctl --user daemon-reload
systemctl --user start music-discovery.service
systemctl --user enable --now music-discovery.timer
journalctl --user -u music-discovery.service -n 100
```

Le lundi à 06 h avec délai aléatoire ; verrou de cycle et verrou SQLite indépendants.
Le fonctionnement sans session ouverte peut nécessiter le linger systemd, à autoriser
sur le serveur. Ne pas activer les timers avant configuration des fournisseurs.

## Validation reproductible sans réseau

`make test` inclut panne fournisseur, doublons intersources, exclusions, données
ambiguës, refus de bases étrangères, simulation sans écriture et concurrence.
Scénario synthétique : FFmpeg → ingestion/tagging MBID/ISRC → publication → second
import idempotent → Discovery avec un titre disponible et un absent → deux cycles
SQLite sans doublon. Aucune API réelle ni synchronisation de playlist n'est simulée
comme une preuve de fonctionnement distant.

À suivre : OpenSubsonic, cache HTTP incrémental, file d'acquisition désactivée tant que
l'autorisation reste limitée à l'audio synthétique, playlists gérées, rétention,
promotion des favoris et validation réseau/iOS.
