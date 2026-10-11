# Roadmap exécutable

États : TODO, IN_PROGRESS, DONE, BLOCKED. Un test simulé ne valide pas une API réelle.
Mise à jour : 2026-10-11. Les critères ci-dessous restent ouverts jusqu'à preuve.

| ID | État | Travail / critère de validation | Dépendance |
|---|---|---|---|
| P0.1 | DONE | Audit dépôt, historique Git, 75 tests initiaux, Python et dépendances | — |
| P0.2 | DONE | Inventaire poste et serveur, Docker, chemins, UID/GID, SQLite et ressources | SSH existant |
| P0.3 | DONE | Sauvegardes vérifiées, restauration isolée, matrice de chemins, hardlinks | P0.2 |
| P0.4 | DONE | Instructions AGENTS et documents de suivi persistants | — |
| P1.1 | DONE | Compose musique versionné, volumes explicites, accès boucle locale | P0.3 |
| P1.2 | DONE | Instance parallèle avec copie de la base, comparaison favoris/historiques/playlists | P1.1 |
| P1.3 | IN_PROGRESS | Streaming API réel validé ; lecture interactive navigateur/iPhone restante | Appareil et accès privé |
| P1.4 | BLOCKED | Accès privé Tailscale, tests réseau mobile | Autorisation compte et réseau |
| P1.5 | BLOCKED | Last.fm : clés chargées, session refusée (erreur 9), reconnexion personnelle puis écoute réelle requises ; ListenBrainz à valider | Réautorisation Last.fm par utilisateur |
| P2.1 | DONE | Verrou import, états persistants, publication sans écrasement et reprise | Tests existants |
| P2.2 | DONE | Renforcer isolation sandbox, nettoyage sous verrou et CLI dry-run | Tests de non-régression |
| P2.3 | DONE | Identifiants MBID/ISRC et déduplication conservatrice, limiter fingerprint de références | P2.2 |
| P2.4 | DONE | Retry/backoff, quota partagé, taille/espace et ressources bornés ; cycles serveur réels | P2.2 |
| P2.5 | DONE | Imports réels autorisés, tags/pochettes/indexation, streaming puis second passage sans doublon | Demande d'acquisition reçue |
| P3.1 | IN_PROGRESS | Adaptateurs externes et catalogue OpenSubsonic faits ; graines locales depuis favoris/histoire restantes | API officielles |
| P3.2 | IN_PROGRESS | Historique SQLite/provenance/déduplication/exclusions/score faits ; cache HTTP et réconciliation d'identités restent à faire | P3.1 |
| P3.3 | IN_PROGRESS | Last.fm réel validé ; ListenBrainz testé réellement vide/indisponible, attente de résultats | Fournisseur ListenBrainz |
| P3.4 | DONE | Clé Last.fm, repli historique complet, deux cycles réels de 25 suggestions sans doublon | Clé fournie et tests réels |
| P4.1 | DONE | Queue/résolution conservative, acquisitions YouTube réelles et erreurs partielles | P2, P3 |
| P4.2 | DONE | Cache hebdomadaire, timer 15 min actif, quotas et déclenchement systemd réel vérifiés | P4.1 |
| P4.3 | DONE | Deux miroirs réels, IDs vérifiés, lecture HTTP audio, second passage idempotent | P4.2 |
| P4.4 | TODO | Favoris conservés, promotion temporaire→permanent, rétention explicite | P4.3 |
| P4.5 | DONE | E2E synthétique et serveur, succès partiels, reprise et absence de doublons au second passage | P4.1–3 |
| P4.YT | IN_PROGRESS | Surveillance opérationnelle ; rattrapage des 202 titres en cours, refus 403 signalés | Disponibilité YouTube |
| P5.1 | TODO | Smart playlists et radios locales artiste/titre/genre | P3, P4 |
| P5.2 | BLOCKED | Amperfy/Arpeggi/SubStreamer : streaming, favoris, hors ligne, reconnexion | P1.3–4 et iPhone |
| P5.3 | TODO | Statut léger, formats limitant transcodage, vérification playlists hebdomadaires | P4 |
| P6.1 | TODO | Lidarr optionnel, dossier albums distinct, listes artistes/profils qualité | P2 stabilisée |
| P6.2 | IN_PROGRESS | Sauvegarde quotidienne et restauration de 11 fichiers validées ; copie externe/audio à préparer | Support de sauvegarde distinct |
| P6.3 | DONE | Timer verrouillé actif, logs Docker bornés, résumés journald, CPU/RAM mesurés pendant import | P4 |
| P6.4 | BLOCKED | Import réel d'album autorisé sans conflit avec ingester | Source d'albums autorisée |
| P7 | BLOCKED | Architecture future vidéo seulement ; aucun déploiement/migration | Validation P0–P6 |

## Critères de passage

- P0 : inventaire réel, aucune altération de bibliothèque, sauvegarde restaurable.
- P1 : nouvelle instance lit les fichiers réels ; lecture authentifiée, favoris et
  historique conservés, ancien service récupérable, accès privé.
- P2 : aucun doublon au second import ; reprise après incident ; sandbox isolé.
- P3 : candidats persistants, inspectables, reproductibles ; une panne fournisseur
  n'interrompt pas les autres ; aucun résultat inventé.
- P4 : cycle complet sandbox puis autorisé, fichiers valides, playlists sans absents
  artificiellement jouables ni modification de playlists personnelles.
- P5 : essais réels iPhone sur Wi-Fi, mobile et hors ligne ; favoris synchronisés.
- P6 : réinstallation et restauration testées, albums séparés, ressources mesurées.
- P7 reste suspendue, y compris si certaines tâches musicales sont bloquées.
