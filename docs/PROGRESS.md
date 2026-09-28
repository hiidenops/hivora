# Hivora — Suivi d'avancement

*Dernière mise à jour : 28 septembre 2026*

Document de reprise : où en est le projet, ce qui a été décidé, comment relancer l'environnement et ce qui reste à faire. Référence produit : [`vision-prd-architecture.md`](vision-prd-architecture.md).

## État en bref

L'alpha V0.x est fonctionnelle de bout en bout : un utilisateur installe, se connecte (admin/admin puis changement forcé), parcourt le catalogue, déploie une app, la pilote et la supprime, depuis une interface web FR/EN.

| Étape | Contenu | État | Commit |
|---|---|---|---|
| M0 Outillage | Squelette backend/frontend, CI GitHub Actions | ✅ | `38466d4` |
| M1 Socle | `core`, `db` (SQLite WAL, Alembic), `crypto` | ✅ | `6b4cc54` |
| M2 Docker | `docker_gateway`, `compose_runner`, `state` | ✅ | `f35601e` |
| M3 Métier | `templates`, `jobs`, `apps`, `zones` | ✅ | `238ac73` |
| M4 API | Auth, utilisateurs et rôles, routes `/api/v1`, WebSocket, audit | ✅ | `ff7b18f` |
| M5 Interface | Next.js statique, tous les écrans, e2e Playwright | ✅ | `8e86c92` |
| Retours tests #1 | Déploiement Minecraft, logos, animations, mise en page | ✅ | `8953b3d` |
| Retours tests #2 | Interrupteurs, fond en grille, graphiques système, vider l'historique, console | ✅ | voir `git log` |
| Minecraft A et B | Personnalisation, catalogue de modpacks (Modrinth, CurseForge) | ✅ | voir `git log` |
| Fiche d'app | Carte d'état, cartes repliables, liste des versions, propriétés suggérées | ✅ | voir `git log` |
| IP publique et consommation | Adresse publique, cartes repliées, CPU/RAM/réseau par app en direct | ✅ | `19e4aa6` |
| Minecraft C | Mondes (liste, activer, importer, télécharger, supprimer) | ✅ | voir `git log` |
| Changement de version | Avertissement, confirmation, contenu du serveur effacé | ✅ | voir `git log` |
| Retours tests #5 | Copie « Texte copié ! », 30 tâches, catalogue opaque, cartes indépendantes, configuration en sections, main au survol | ✅ | `26f131b` |
| Clé CurseForge sur place | Formulaire dans le catalogue de modpacks | ✅ | `e40ce9c` |
| Architecture | Détectée par Docker, image par architecture, vérification avant téléchargement | ✅ | `4f1bad2` |
| Jeux génériques | Capacités déclarées par le template (joueurs, listes, mondes) | ✅ | `d2414ba` |
| Catalogue de jeux | Valheim, Rust, Project Zomboid, CS2, Garry's Mod (OVH, x86), Palworld (x86 + ARM) | ✅ | voir `git log` |
| Images à jour et versions | Contrôle hebdomadaire des images, version → image (Java de Minecraft), branches Steam en direct | ✅ | `eada91b` |
| 12 jeux de plus | Enshrouded, V Rising, Sons of the Forest, 7 Days to Die, Satisfactory, Terraria, tModLoader, Factorio, Don't Starve Together, Core Keeper, ARK: Survival Ascended, Conan Exiles | ✅ | voir `git log` |
| Zones | Créer, modifier, supprimer ; réseau « reliées entre elles » ; déplacer une app | ✅ | `cd0c3fc` |
| 13 applications | WireGuard, Stirling PDF, Uptime Kuma, AdGuard, Jellyfin, Immich, Paperless, Nextcloud, Home Assistant, Gitea, Syncthing, File Browser, n8n | ✅ | `7389764` |
| Image Docker libre | N'importe quelle image de registre, gérée comme les autres apps | ✅ | `921d41c` |
| WireGuard géré | Clients, IP autorisées, clés, QR code, zones accessibles | ✅ | voir `git log` |
| Logs en direct | Tous les conteneurs d'une app, filtre par service, recherche, téléchargement | ✅ | voir `git log` |
| Mise à jour et retour arrière | Nouvelle version du template ou de l'image en un clic, restaurer une révision | ✅ | voir `git log` |
| Sauvegardes | À la demande ou planifiées, rétention, restauration, téléchargement | ✅ | voir `git log` |
| M6 Livraison | Image Docker, HTTPS, script d'installation, budgets en CI | ✅ | voir `git log` |
| Page Pare-feu | Ports ouverts en direct, UFW, jails fail2ban (bans et réglages), routes | ✅ | voir `git log` |
| Retours tests #6 | Règles UFW visibles pare-feu coupé, autoriser/refuser depuis les ports ouverts, crash « database is locked » (VPN) corrigé, ports publiés sur les cartes, modifications dans la barre d'outils, liseré de zone, export PNG propre | ✅ | `e085102` |
| Topologie | Schéma observé + déclaré, alertes d'exposition, export PNG/JSON | ✅ | voir `git log` |
| Retours tests #3 | Fond plus discret en pinceau, graphiques continus (2 s), console toujours ouverte | ✅ | voir `git log` |
| Retours tests #4 | Fiche d'app qui ne chargeait pas (HTTP par IP), fond en trait continu | ✅ | voir `git log` |
| Minecraft, partie A | Horodatage des graphiques, « Modifier les réglages » (révisions), types de serveur et modpacks, propriétés | ✅ | voir `git log` |
| Catalogue de modpacks | Recherche Modrinth / CurseForge dans le panel, déploiement pré-rempli, clé CurseForge globale | ✅ | voir `git log` |
| Minecraft, partie B | Joueurs connectés, liste blanche (on/off + ajout/retrait), admins | ✅ | voir `git log` |
| Fiche d'app et réglages | Carte d'état, cartes repliables, versions en liste, propriétés disponibles | ✅ | voir `git log` |
| Minecraft, partie C | Gestion des mondes | ⏳ proposé | — |

Tests : 209 backend (dont 3 d'intégration sur Docker réel), 1 parcours e2e Playwright, contrôle du budget bundle. Tout passe (28/09).

## En attente de ton retour

Le serveur de test tourne sur la VM : **http://192.168.70.150:8000** (données dans `~/hivora-dev`, Docker réel), relancé avec la partie B de Minecraft. À tester :

1. **Console** : fiche d'une app démarrée → « Ouvrir la console ». Minecraft : onglet « Console serveur » (`rcon-cli`) + guide des commandes repliable ; toute app : onglet « Shell ».
2. **Activité** : graphiques CPU / RAM / réseau (un point toutes les 10 s), boutons « Vider ».
3. Interrupteurs dorés, fond en grille, alignements pendant un déploiement (bureau et mobile).

Si la VM a redémarré, voir « Relancer le serveur de test » plus bas.

## Catalogue de modpacks (fait)

- Catalogue → onglet « Modpacks Minecraft » : recherche, source Modrinth / CurseForge, filtres chargeur et version, cartes (icône, téléchargements, versions), « Déployer ce modpack » → assistant Minecraft pré-rempli (type, modpack, 6 Go).
- Hivora interroge les API (module `games`, V2 avancée) : le navigateur ne contacte aucun tiers ; résultats en cache 1 min ; icônes relayées depuis `cdn.modrinth.com` / `media.forgecdn.net` uniquement, taille plafonnée, mises en cache.
- **Clé CurseForge globale** : Paramètres → Intégrations (admin, chiffrée, jamais réaffichée). Les templates peuvent déclarer `from_setting` sur un champ secret : vide → valeur du réglage.
- Corrigé : les icônes relayées étaient tronquées (lecture partielle) ; GIF acceptés.

## Minecraft, partie A (fait)

- **Graphiques** : repère horaire chaque minute, heure à la seconde dans l'infobulle.
- **Modifier les réglages** (toutes les apps) : formulaire pré-rempli → diff du compose → nouvelle révision appliquée par une tâche. Secrets laissés vides = conservés.
- **Minecraft 1.4.0** : type de serveur (Vanilla, Paper, Fabric, Forge, modpack CurseForge, modpack Modrinth), PvP, hardcore, Nether, vol, monstres, animaux, blocs de commande, distances, protection du spawn, taille du monde, type de monde, graine, propriétés personnalisées (`CUSTOM_SERVER_PROPERTIES`).
- **CurseForge** : la clé API n'est demandée que pour un modpack CurseForge, stockée chiffrée par app. Modrinth n'en demande pas.
- **Corrigé grâce au test réel** : un champ optionnel vide devenait le texte « None » dans l'environnement (Minecraft refusait de démarrer). Désormais une variable vide n'est pas définie.

## Minecraft, partie B (fait)

- Fiche d'un serveur Minecraft : carte **Joueurs** (connectés / max, pseudos, rafraîchie toutes les 15 s via `rcon-cli list`) et carte **Accès**.
- **Liste blanche et admins** : lus dans `whitelist.json` / `ops.json` du serveur ; ajout/retrait à chaud via `rcon-cli` (pseudos validés `[A-Za-z0-9_]{3,16}`, exec sans shell) ; audit `game.*`.
- **Activer/désactiver la liste blanche** = intention (réglage `enable_whitelist`, template 1.6.0) : nouvelle révision + redémarrage, car l'image réécrit `white-list` à chaque démarrage. L'interrupteur reflète immédiatement la demande.
- Vérifié sur un vrai serveur : `Notch` ajouté puis retiré, passé op (UUID Mojang réel), `white-list` à true puis false dans `server.properties`.

## Fiche d'app et réglages (fait, 25/09)

1. **Carte d'état** en haut de la fiche : icône, badge d'état coloré, « en marche depuis » (`StartedAt` du conteneur), adresse de connexion à copier, joueurs connectés, résumé déclaré par le template (`summary` : type, version, mémoire, joueurs max) et révision. Conteneurs en mode avancé.
2. **Cartes Joueurs et Accès repliables** (état mémorisé, compteur visible replié).
3. **« Tâches récentes » retirée** de la fiche (historique dans Activité ; la progression d'une action en cours reste affichée).
4. **Version de Minecraft = liste** des vraies versions (manifeste Mojang via le backend, cache 1 h ; snapshots en mode avancé). Format de template : `options_from`.
5. **Propriétés disponibles** : panneau filtrable de 30 propriétés `server.properties` (défaut + description FR/EN) ; un clic ajoute ou remplace la ligne. Format de template : `suggestions`.
- Vérifié en réel : serveur déployé en 1.21.1 choisie dans la liste, `player-idle-timeout=0` ajouté via le panneau présent dans `server.properties`.

## IP publique, cartes repliées, consommation (fait, 24/09)

1. **Adresse publique** : IP publique détectée par le backend (`api.ipify.org`, toutes les 6 h ; ignorée si `HIVORA_HOST_PUBLIC_IP` est fixée), ou IP / domaine saisi dans Paramètres → Intégrations (admin ; vide = détection auto). La carte d'état affiche l'adresse publique à copier, « en local : … » en second, et le rappel « ouvrez le port … sur votre box » pour les ports `public`. Les apps `lan` (Vaultwarden) gardent l'adresse locale.
2. **Cartes Joueurs et Accès repliées par défaut** (ouvertes seulement si l'utilisateur les a ouvertes).
3. **Consommation en temps réel** par app : CPU (% de la machine), mémoire, réseau entrant/sortant, trois courbes défilantes. `stats` one-shot toutes les 5 s, **seulement tant qu'une fiche est ouverte** (canal WS `app_metrics`, compteur d'observateurs) ; historique de 5 min en mémoire, effacé quand plus personne ne regarde.
- Vérifié en réel : IP publique détectée ; serveur Minecraft au repos ≈ 0,14 % CPU, 1,3 Go de RAM.

## Minecraft, partie C : mondes (fait, 24/09)

Carte « Mondes » sur la fiche d'un serveur Minecraft (repliée par défaut) :
1. **Liste** des mondes (dossiers avec `level.dat` dans le volume `data`) : nom, taille, date, badge « actif ». Les dossiers `<monde>_nether` / `<monde>_the_end` (Paper, Spigot) sont regroupés avec leur monde.
2. **Activer** : nouveau champ de template `level` (monde actif, variable `LEVEL`) ; activer = nouvelle révision et redémarrage. Template Minecraft passé en 1.8.0 ; la suggestion `level-name` des propriétés personnalisées est retirée (doublon).
3. **Télécharger** en `.zip`, généré à la volée sans fichier temporaire ; `save-all flush` avant si le monde actif tourne. Téléchargement audité (`game.world_downloaded`).
4. **Supprimer** (tâche `world_delete`) ; refusé sur le monde actif.
5. **Importer un `.zip`** (tâche `world_import`) : envoi en flux avec barre de progression, plafonds **10 Go envoyés / 30 Go décompressés / 500 000 fichiers**, vérification de l'espace disque, refus des chemins absolus, `..` et liens symboliques, monde trouvé à la racine ou dans un dossier, extraction dans un dossier caché puis renommage (rien de cassé en cas d'échec). Le fichier envoyé est stocké à côté du volume (`/srv/hivora/<slug>/.hivora-upload-*.zip`) et supprimé après.
- Migration Alembic `0004` : nouveaux types de tâches.
- Vérifié en réel : monde de `serveur-test` exporté puis réimporté à l'identique ; `save-all flush` répond.
- Limite connue : dans un `.zip`, seul le `level.dat` le moins profond est pris ; des dossiers de dimensions Paper zippés à côté sont ignorés.

## Changement de version Minecraft (fait, 25/09)

Constat : passer un serveur de `LATEST` (26.x) à 1.20.1 le faisait planter en boucle (`No key dimensions in MapLike`), car Minecraft ne lit pas un monde enregistré par une version plus récente.
1. Nouveau champ de template `reset_data_on_change` (Minecraft 1.9.0 : version, type de serveur, modpacks) et `reset_keep` sur un volume (`whitelist.json`, `ops.json`, `banned-*.json`).
2. « Modifier les réglages » : si un tel champ change par rapport à la révision **appliquée**, l'aperçu affiche un avertissement rouge (champs, taille effacée, lien pour télécharger les mondes) ; « Effacer et appliquer » reste grisé tant que la confirmation n'est pas cochée.
3. L'API refuse ce changement sans `reset_data: true` (409 `data_reset_required`). La tâche arrête l'app, vide le volume en gardant les fichiers listés, puis redémarre ; journal de tâche et audit `app.data_reset`.
- Tests : unitaire (refus, effacement, réglage anodin sans effacement) et e2e (changement de type de serveur).

## Jeux : architecture, modèle générique, catalogue (fait, 26/09)

1. **Architecture** : lue auprès de Docker au démarrage (`docker info`), affichée dans Paramètres → Système et en tête du catalogue. Un service peut déclarer une image par architecture (`arch: {arm64: {image, tag, env}}`, figées par digest). Avant le téléchargement, la tâche demande au registre les plateformes de l'image et échoue clairement si la machine n'en fait pas partie. Badges « x86 uniquement » / « ARM uniquement ».
2. **Modèle de jeu générique** : le template déclare `game.players` (commande + format `minecraft`/`csv`, ou requête Steam A2S), `game.lists` (listes de joueurs dans un fichier, modifiées par commande ou en éditant le fichier ; `enabled_field` = interrupteur), `game.saves` (dossiers avec un fichier repère, ou fichiers groupés par nom `*.fwl`) et `run_as: app` (commandes sous PUID:PGID). Routes `/apps/{id}/game/...` ; la fiche affiche les cartes déclarées. Minecraft Java est décrit ainsi (1.11.0), sans perte.
3. **Volumes** : `owner: "10001:10001"` pour les images à UID fixe (migration `0005`) ; `stop_grace_period` pour laisser le jeu sauvegarder.
4. **Templates** (images du panel OVHcloud `ovhcom/gamepanel-*`, Apache-2.0, x86 uniquement) : Valheim (joueurs A2S, mondes `*.fwl`, listes admins/autorisés/bannis), Rust, Project Zomboid, Counter-Strike 2 (jeton GSLT obligatoire), Garry's Mod. Console via `/app/send-command.sh`, une commande par ligne. Multi-arch : Palworld (`thijsvanloef/palworld-server-docker`, console `rcon-cli`, joueurs `ShowPlayers`). Minecraft Bedrock testé puis retiré du catalogue (26/09, à la demande).
- **Testé en réel sur la VM ARM** : Palworld : l'image arm64 démarre et installe le serveur (test interrompu, 16 Go recommandés).
- **Non testé en réel** (pas de machine x86) : Valheim, Rust, Project Zomboid, CS2, Garry's Mod. Compilation et `docker compose config` vérifiés pour tous.
- `run_as: app` (commandes de jeu sous PUID:PGID) vient du test réel de Bedrock : un serveur passé sous PUID n'est pas joignable depuis root sans ptrace.

## Catalogue à jour, versions au choix, 12 jeux de plus (fait, 26/09)

1. **Images toujours à jour** : `backend/scripts/check_images.py` compare chaque image figée au plus récent tag de même forme sur Docker Hub (`2026.9.2-java25` n'est comparé qu'aux `-java25` ; un tag mobile comme `latest` ou `stable`, à son digest du jour). GitHub Actions le lance chaque lundi (`.github/workflows/images.yml`) et échoue si une image est en retard. Les versions volontairement anciennes sont marquées `frozen`.
2. **Changer de version quand on veut** :
   - `tag_select` : un champ du formulaire choisit le tag d'image (valeur exacte ou plage `below`). Minecraft Java prend le bon Java selon la version (8 avant 1.17, 17 avant 1.20.5, 21 avant 26, sinon 25). Factorio (stable, expérimentale, 1.1), Terraria (dernière, 1.4.4.9), tModLoader (stable, aperçu, 1.4.3).
   - `options_from: steam_branches` : la liste des branches Steam est lue en direct (api.steamcmd.net, cache 1 h) pour Project Zomboid (public = Build 42, legacy41 = Build 41), Garry's Mod, V Rising et 7 Days to Die.
   - Tout changement de version efface le contenu du serveur après confirmation (règle déjà en place).
3. **`files`** : un template peut placer un fichier dans le conteneur (Compose `configs`, secrets résolus depuis `.env`), utilisé pour le jeton Klei de Don't Starve Together.
4. **Modpacks** : CurseForge par défaut (le catalogue le plus fourni), pagination jusqu'à 10 000 résultats.
5. **12 jeux** (sources vérifiées le 26/09) : Enshrouded (`mornedhels`), V Rising (`trueosiris`), Sons of the Forest (`jammsen`), 7 Days to Die (`vinanrra`), Satisfactory (`wolveix`), Terraria (`ryshe`, x86 + ARM), tModLoader (`jacobsmile`), Factorio (`factoriotools`, x86 + ARM), Don't Starve Together (LinuxGSM `gameservermanagers/gameserver:dst`), Core Keeper (`escaping`, x86 + ARM), ARK: Survival Ascended (`acekorneya`), Conan Exiles (`indifferentbroccoli`). DayZ écarté (compte Steam propriétaire du jeu obligatoire). Images DST dédiées écartées (2022, ou sans documentation).
- **Testé en réel sur la VM ARM** : Terraria (monde créé, passage 1.4.5.8 → 1.4.4.9 avec effacement confirmé), Factorio (volume en 845:845, `rcon`, sauvegarde listée), Core Keeper (session démarrée ; sur ARM l'image doit télécharger avec DepotDownloader, déclaré par architecture). Corrigé grâce au test : les noms de monde peuvent commencer par `_` (`_autosave1` de Factorio).
- **Non testé en réel** (x86 uniquement) : les autres jeux. Compilation, `docker compose config` et fraîcheur des images vérifiés pour tous.
- À savoir : plusieurs jeux se règlent ensuite dans un fichier du volume (V Rising, Sons of the Forest, 7 Days to Die, Factorio, DST), le formulaire le signale. Factorio n'apparaît dans la liste publique qu'avec un compte factorio.com (connexion par IP sans).

## Réseau et applications (fait, 27–28/09)

- **Zones** : page Zones (couleur, réseau, applications), réseau `hivora-zone-<slug>` créé par Hivora pour les zones « Reliées entre elles », déplacement d'une app (nouvelle révision). Le mode réseau ne change pas l'accès depuis l'extérieur (ports publiés).
- **Applications** : 13 templates multi-arch ; `cap_add` / `sysctls` en liste blanche (WireGuard), `shm_size`, `track: minor` et `frozen` pour le contrôle de fraîcheur (ghcr.io lu aussi) ; zone suggérée présélectionnée au déploiement.
- **Image libre** : Catalogue → Applications → « Déployer une image Docker » ; lue dans son registre (digest, plateformes, ports, volumes, variables), template généré (variables et ports modifiables ensuite), figé par digest, rechargé au démarrage.
- **WireGuard géré** (module `vpn`, section de template `vpn`, image `linuxserver/wireguard`) : Hivora est la source de vérité (table `vpn_peer`, clés privées chiffrées AES-GCM), réécrit `wg0.conf` dans le volume et l'applique à chaud par exec (`wg syncconf`) ; ni API, ni interface web, seul 51820/udp est publié. Carte « Clients VPN » (ajout, activation, IP autorisées, QR code, configuration, nouvelles clés, suppression, stats `wg show dump`) et « Zones accessibles » (réseaux de zone rejoints, NAT sur toutes les interfaces dans PostUp). Testé en réel sur ARM avec un vrai client (handshake, ping, coupure à la désactivation). Remplace wg-easy (les apps wg-easy existantes ne sont pas migrées). Adressage en mode avancé (réseau, IP de la passerelle, port UDP public) ; IP de chaque client modifiable sur la carte ; un changement de réseau renumérote les clients hors réseau et reconstruit l'interface, appliqué automatiquement après chaque déploiement (`app.deployed`). **Droits par client appliqués par le serveur** (chaîne `HIVORA-VPN` dans le conteneur, script `hivora-acl.sh` reconstruit à côté puis permuté, relancé par PostUp) : Internet, réseau local (plages privées) et chaque zone atteinte ; préréglages du trafic envoyé dans le tunnel (réglage du VPN, tout, seulement l'autorisé, personnalisé) ; renommage ; expiration (désactivation automatique chaque minute, réactivation manuelle = sans limite) ; pastille en ligne (handshake < 3 min) et IP d'origine. Migration `0007`. Testé en réel : client limité à une zone (zone OK, LAN et Internet bloqués), puis inversé à chaud, expiration coupant le client. À faire après M6 : panel accessible uniquement par le VPN.
- Budget pages : menu Radix remplacé par un menu maison (−17 Ko sur /users), dictionnaire anglais chargé à la demande, carte VPN chargée à la demande.
- Plus tard (V3) : WireGuard en passerelle d'une zone.
- **Mise à jour en un clic** (F-20) : `GET /apps/{id}/upgrade` compare la version du template de l'app au catalogue, ou, pour une image libre, le digest du tag dans son registre (cache 10 min) ; bandeau « Nouvelle version disponible » sur la fiche → dialogue (diff, conflits, avertissement d'effacement) → nouvelle révision avec les mêmes réglages (image libre : template re-figé sur le nouveau digest). **Retour arrière** : chaque révision garde sa version de template (migration `0008`) ; « Restaurer » (fiche, mode avancé, liste des révisions) recompile ses réglages avec cette version, en nouvelle révision. Minecraft 1.13.0 : lignes du sondage RCON masquées des logs en direct (`logs.hide`).
- **Sauvegardes** (module `backups`, migration `0009`) : archive `tar.gz` des volumes marqués `backup` dans `<data>/backups/<slug>/`, tâches `backup` / `backup_restore` dans la file de l'app (arrêt pendant la copie si demandé, relance ensuite), planification quotidienne / hebdomadaire / toutes les N heures à l'heure locale (`HIVORA_TIMEZONE`), vérifiée chaque minute, rétention des N dernières automatiques (les manuelles restent), restauration (contenu des volumes remplacé, propriétaires gardés, archive hors volumes refusée), téléchargement ; archives supprimées avec l'app si ses données le sont. Carte « Sauvegardes » sur la fiche. Testé en réel (Vaultwarden en marche : arrêt, archive, relance ; restauration). À venir : copie vers un stockage externe (S3, SFTP).
- **Livraison (M6)** :
  - `Dockerfile` (racine) : 3 étapes figées par digest (Node → export statique, Python + uv → venv verrouillé, runtime `python:3.13-alpine`), Compose v2 **autonome** (`docker/compose-bin`, `HIVORA_COMPOSE_CMD='["docker-compose"]'`, pas de CLI Docker), `python -m hivora`, healthcheck. Mesuré sur ARM : **174 Mo sur disque, ~51 Mo à télécharger, 88 Mo de RAM au repos**.
  - **HTTPS par défaut** (`HIVORA_TLS`, `HIVORA_PORT`=8443) : certificat auto-signé ECDSA créé au premier démarrage dans `<data>/tls/` (SAN : localhost, nom d'hôte, IP LAN/publique), jamais écrasé (remplaçable par le sien). `HIVORA_TLS=false` derrière un proxy.
  - `deploy/install.sh` (brouillon de get.hivora.io) : Linux amd64/arm64, root, installe Docker si absent (confirmation, `--yes`), Engine ≥ 24, détecte IP LAN / fuseau / PUID, `docker run` avec les 3 montages au même chemin, écoute sur l'IP LAN par défaut (`--bind`), attend « healthy », affiche l'URL ; relancer = mise à jour (données gardées). `deploy/compose.yaml` en alternative.
  - CI `image.yml` : build amd64, budgets vérifiés (image < 200 Mo sur disque, RAM au repos < 150 Mo, HTTPS sain), publication amd64 + arm64 sur `ghcr.io/hiidenops/hivora` à chaque tag `v*`.
  - uvicorn sans extras (`websockets` seul) ; mypy des tests remis au vert.
  - Reste : débit réseau de l'hôte vu depuis le conteneur (monter `/proc` de l'hôte), panel joignable seulement par le VPN, domaine public + Let's Encrypt.
- **Corrections (lot A)** : valeurs par défaut pouvant citer d'autres champs (`{{ form.web_port }}`, évaluées en dernier) — Vaultwarden 1.3.0 : `DOMAIN` suit le port web ; **codes TOTP à usage unique** (dernier pas de 30 s accepté mémorisé par utilisateur) ; **clé pré-partagée WireGuard** par client (chiffrée, migration `0010`, régénérée avec les clés ; les clients existants en reçoivent une : configuration à réimporter). Testé en réel (handshake avec PSK).
- **Édition avancée (lot B, F-08/F-12)** : réglages avancés par service gardés dans chaque révision (`overrides`, migration `0011`) : variables en plus, ports supplémentaires (visibilité LAN/public), dossiers supplémentaires sous le dossier de l'app (sauvegardés), limites `cpus` / `mem_limit`, politique de redémarrage ; éditeur dans « Modifier » (mode avancé). **Compose écrit à la main** (admin, fiche → mode avancé → « Modifier le compose ») : validé par `docker compose config` (modèle résolu), refusé si privileged, réseau/pid/ipc hôte, capacités ou sysctls hors liste, devices, montage hors des dossiers de l'app (socket Docker, chemins relatifs, variables) ; appliqué en révision `custom_compose` ; le formulaire le remplace (avertissement), restaurer le remet. Testé en réel.
- **Adoption (lot C, F-17)** : `GET /apps/discover` liste les projets Compose en marche hors de Hivora (Hivora lui-même exclu via `io.hivora.self`) ; « Adopter » (tableau de bord → bandeau) crée l'app sans rien redéployer (origine `adopted`, identifiant = nom du projet, services et ports lus sur les conteneurs) ; l'état la reconnaît par son projet ; démarrer / arrêter / redémarrer via `docker compose -p <projet>` sans fichier ; logs, console, consommation comme les autres ; « Supprimer » l'oublie seulement. Testé en réel (nginx + redis). Pas encore : conversion en app Hivora, changer sa zone après coup.
- **Tâches planifiées (cron simplifié)** (module `tasks`, migration `0012`) : par app, action redémarrer / arrêter / démarrer / sauvegarder (tâches dans la file de l'app) ou commande (shell `sh -c` dans le service choisi, ou console du jeu : commande du template + arguments, utilisateur du jeu), horaires partagés avec les sauvegardes (`core/schedule.py` : chaque jour / semaine à l'heure locale, toutes les N heures), vérifiés chaque minute ; dernier résultat, sortie (secrets masqués, 2 min max), « Lancer maintenant ». Carte « Tâches planifiées » sur la fiche. Testé en réel (commande dans un service, redémarrage déclenché par le planificateur). La section avancée de la fiche est chargée à la demande (budget : `/app` 247,5 Ko).
- **Topologie (lot E, F-18)** : module `topology` (migration `0013` : `topology_node`, `topology_edge`, `topology_layout`) ; `GET /topology` calcule le graphe en un JSON : Internet, zones (couleur, mode réseau), apps (état, icône, ports et exposition), liens Internet → ports publics (« contourne le pare-feu »), VPN → zones atteintes, couche déclarée (pare-feu, routeur, VPN externe, appareil, note ; liens) ; analyse : port public, zone isolée exposée, app sans zone, conteneurs/stacks non gérés. Page « Topologie » (menu) avec React Flow chargé à la demande (page : 222 Ko) : disposition en grille par zones (sans ELK : ~300 Ko pour un graphe hôte → zones → apps), trois niveaux (zones / zones et apps / tout avec ports), repli aux zones au-delà de 150 éléments, états en direct, panneau latéral (lien vers l'app), glisser = position mémorisée, tirer d'un point à un autre = lien déclaré, disposition automatique, export PNG et JSON. Budget frontend relevé à 520 Ko par page.
- **Topologie éditable (lots G1–G2, V3 anticipée)** : cartes compactes, zones redimensionnables (taille mémorisée, migration `0014`), zoom initial limité. **Modifications préparées** puis appliquées en révisions (ou « Annuler les modifications ») : glisser une app dans une autre zone, exposition de chaque port (public / réseau local / non publié : réglage avancé `publish`), **placer une app derrière le VPN** (bouton du panneau, ou tirer un lien du VPN vers l'app) : ses ports publics se ferment et le VPN rejoint son réseau `<app>_default` (entrée `@<app>` dans `vpn_zones`, WireGuard 2.2.0) ; son adresse via le VPN est affichée ; détacher = cliquer le lien VPN. Une app derrière un VPN ne peut pas être supprimée avant d'être détachée.
- **Pare-feu de l'hôte (lot G3)** : module `hostfw` ; **agent hôte** optionnel (conteneur `hivora-host-agent` Alpine figé, privilégié, PID et réseau de l'hôte, en sommeil ; commandes par `exec` + `nsenter -t 1`), désactivé par défaut, admin + TOTP récent (`POST /host-firewall/confirm`), audité (`hostfw.*`) ; exception inscrite dans CLAUDE.md. UFW : état, défauts, règles numérotées, ajout (autoriser / limiter / refuser, port, protocole, source IP/réseau validée), suppression, activation (SSH 22/tcp limité ajouté avant si absent) ; fail2ban : jails, IP bannies, bannir / débannir. Nœud « Pare-feu de l'hôte » dans la topologie (entre Internet et les zones ; les ports publiés Docker restent reliés directement à Internet : UFW ne les filtre pas) et dialogue « Configurer ». Testé en réel : l'agent atteint l'hôte ; UFW et fail2ban absents de la VM de dev (non installés).
- **Projets Python (lot M)** : module `pyapps` ; Catalogue → Applications → « Déployer un projet Python » : envoi du `.zip` (300 Mo max, chemins et liens refusés), **analyse sans rien exécuter** : racine, version (Dockerfile `FROM`, `.python-version`, `runtime.txt`, `requires-python`), dépendances (`requirements.txt`, `pyproject.toml`), commande (Dockerfile `CMD`/`ENTRYPOINT`, compose `command`, `Procfile`, sinon le fichier avec `if __name__ == "__main__"`), dossiers (volumes du compose `./app:/app`, `COPY` du Dockerfile, sinon `/app` ; dossier sans `.py` = données), variables (compose, `.env`, `.env.example`, `os.getenv` du code ; TOKEN/KEY/SECRET/PASSWORD → secrets chiffrés), ports (`EXPOSE`, compose, `--port`), paquets `apt` du Dockerfile. Écran de vérification modifiable puis template généré : image officielle `python:<v>-slim` figée par digest, venv conservé (`/venv`, recréé si la version change), dépendances installées à chaque démarrage. Carte « Code du projet » sur la fiche : nouveau `.zip` → dossiers de code remplacés, données gardées, redémarrage. Testé en réel (bot : dépendance installée, variables et secret lus, mise à jour du code avec données conservées).
- **Topologie plus discrète (28/09)** : les modifications préparées ne s'empilent plus sous le schéma ; dans la barre d'outils, un groupe apparaît dès qu'il y en a : bouton liste (nombre, ouvre la liste flottante en haut à gauche du schéma, suppression une par une), « Appliquer », annuler tout. Cartes d'app avec un liseré gauche à la couleur de leur zone. Mini-carte (carré en bas à gauche) retirée. Export PNG lisible : la marge passée à React Flow 12 est une fraction (80 = zoom minimal), remplacée par 5 %, rendu à l'échelle 1 en pixel ratio 2. Puis, vérifié dans un vrai navigateur (clair et sombre, trois niveaux) : l'étiquette du port sur le lien Internet sortait en rectangle noir (variables CSS de React Flow absentes de la capture) et tombait sous la carte du pare-feu → plus d'étiquette sur les liens exposés (le port est sur la carte « WAN … » et dans les alertes), couleurs explicites pour les autres ; points de connexion retirés de l'image ; au niveau « Zones et apps », les zones grandissent quand leurs cartes affichent des ports (elles débordaient).
- **Topologie : ports publiés toujours visibles (28/09)** : les cartes d'app affichent leurs ports publiés à tous les niveaux (« LAN 8081/tcp » en bleu, « WAN … » en rouge, infobulle avec l'exposition) ; les ports internes restent réservés au niveau « tout ». Avant, rien n'apparaissait au niveau par défaut pour un port publié sur le réseau local (pas de lien Internet : il n'est pas exposé).
- **Correctif « database is locked » (28/09)** : les actions sur les clients VPN gardaient la base SQLite verrouillée en écriture pendant l'exec dans WireGuard (`wg syncconf` / `wg-quick up`, parfois plusieurs secondes) ; les autres requêtes (mise à jour de la session à chaque appel) attendaient plus de 5 s puis tombaient en erreur 500. Désormais : écriture en base et des fichiers dans une transaction courte, puis application dans le conteneur hors transaction (toujours sous le verrou VPN) ; un client refusé par WireGuard est retiré. Test de non-régression : une écriture en base pendant l'exec (échouait avec l'ancien code). Vérifié : aucun autre module n'appelle Docker avec une écriture en cours.
- **Page Pare-feu (lot I)** : entrée « Pare-feu » du menu (admin) reprenant le panneau UFW / fail2ban de la topologie (`features/firewall/firewall-panel.tsx`), plus : **ports ouverts en direct** (`GET /host-firewall/listening` : `ss -tulpn` sur l'hôte croisé avec les ports publiés par Docker et les règles UFW → local seulement / bloqué par UFW / autorisé / UFW inactif / Docker contourne UFW ; rafraîchi toutes les 5 s) ; **réglages des jails** (essais, fenêtre, bannissement ; `GET/PUT /host-firewall/fail2ban/settings` : `fail2ban-client get`, écriture de `/etc/fail2ban/jail.d/hivora.local` généré et validé par Hivora, passé en argument d'un script fixe, puis `fail2ban-client reload` ; TOTP récent) ; **routes** de l'hôte (`ip -j route`) et redirections Docker, en lecture seule. Le nœud pare-feu de la topologie affiche les ports joignables depuis l'extérieur. Tests : analyse `ss`, validation des jails (nom, durées, essais), les trois routes avec agent simulé, e2e (page affichée, agent désactivé). Non testé en réel : UFW et fail2ban absents de la VM. Règles UFW visibles aussi pare-feu désactivé (`ufw show added`, supprimées par leur texte car la numérotation d'UFW compte les copies IPv6) ; boutons « Autoriser » / « Refuser » sur chaque port ouvert : pré-remplissent le formulaire de règle (source à choisir), désactivés pour les ports publiés par Docker (UFW ne les filtre pas). Blocs du pare-feu sur fond de carte (`surface`), comme les autres pages. Limite : une jail désactivée disparaît de la liste (fail2ban ne la rapporte plus) ; la réactiver = éditer `hivora.local`.
- **Logs en direct** (F-13) : carte « Logs » de la fiche (opérateur, chargée à la demande, flux seulement carte ouverte) : canal WS `logs.open`/`logs.close` (4 flux max par onglet), tous les conteneurs de l'app suivis, liste relue toutes les 2 s (redémarrage, recréation : reprise depuis la dernière ligne, sans doublon), lignes groupées toutes les 250 ms (500 max, le surplus est compté), secrets de l'app masqués. Filtre par service, recherche, suivi automatique, vider. Téléchargement `GET /apps/{id}/logs` (10 000 lignes par conteneur, fusionnées par heure, audit `app.logs_downloaded`). Testé en réel (Vaultwarden, redémarrage suivi).

▶ **Reprise (28/09)** : lot K validé, pas commencé — filtrage des ports publiés par Docker via l'agent (`iptables`, chaîne `HIVORA-USER` appelée depuis `DOCKER-USER`) : par port d'app, ouvert à tous / seulement ces IP ou réseaux / bloqué, règles reconstruites à chaque démarrage. Prérequis : ajouter `iptables` (chaîne `HIVORA-USER` seulement) à l'exception de l'agent hôte dans CLAUDE.md. Puis lot L : catalogue sysadmin (~15 templates multi-arch figés par digest : nginx, Apache httpd, Caddy, Nginx Proxy Manager, MariaDB, PostgreSQL, Redis, Adminer, Grafana, Prometheus, Node exporter, Dozzle, Netdata, SFTPGo, Homepage).

▶ **Prochaine étape** : publier une première version (tag `v0.1.0` → image sur ghcr.io), l'installer sur une machine x86 et y tester les jeux x86. Catalogue LinuxGSM générique (140+ jeux) : non fait (ports inconnus avant installation, contraire à la règle des digests figés).

## Retours traités (tour 4)

| Retour | Réponse |
|---|---|
| La fiche d'une app ne charge pas | Cause : `crypto.randomUUID` n'existe pas en HTTP par IP (contexte non sécurisé) et plantait la console ouverte automatiquement. Remplacé ; l'e2e passe désormais par l'IP réseau et émule des conteneurs démarrés, il échoue sans le correctif |
| Fond encore trop prononcé, pas fluide | Remplacé (tour 5) par une grille qui se déforme sous la souris, cases allumées en doré autour, lignes dorées à proximité ; canvas animé seulement tant que des points bougent |

## Retours traités (tour 3)

| Retour | Réponse |
|---|---|
| Survol du fond trop prononcé, plusieurs cases à la fois | Pinceau 3×3 : centre à 20 % d'opacité max, côtés 45 % de ça, coins 20 % |
| Métriques plus fréquentes, courbe continue | Relevé toutes les 2 s (psutil, coût négligeable), axe temporel de 5 min qui défile à chaque image, ancré sur l'heure du serveur |
| Console à afficher tout le temps, bouton « Commandes » sans effet | Cause : il fallait d'abord « Ouvrir la console », et le guide était masqué sous 768 px. Console ouverte automatiquement, onglets commutables à chaud, guide toujours visible (sous le terminal sur mobile), « Reconnecter » |

## Retours traités (tour 2)

| Retour | Réponse |
|---|---|
| Fond « interactive grid » à plat, couleurs plus marquées | Grille SVG plate, case sous la souris en doré qui s'estompe (suivi global de la souris, pas de dépendance) |
| Éléments mal alignés au lancement d'un serveur | Cause racine : éléments de grille CSS qui refusaient de rétrécir (`min-width: auto`) → règle globale ; liste des tâches sur deux lignes ; carte de tâche active titrée par son type |
| Console des conteneurs + guide de commandes | Console serveur (`game.console`, ex. `rcon-cli`) et Shell (`sh`/`bash`) via xterm.js chargé à la demande ; guide repliable (`game.commands` du template) ; audit ouverture/fermeture, 8 max, 30 min d'inactivité, reconfirmation TOTP 15 min |
| Graphiques système dans Activité | CPU, RAM « utilisée / totale », réseau entrant/sortant (interfaces physiques seulement), infobulle au survol, tableau accessible ; couleurs validées clair/sombre |
| Vider les logs | Admin : vider les tâches terminées et le journal d'audit (une entrée « journal vidé par X » est conservée). Filtres du journal : plus tard |
| Interrupteurs style iPhone | Composant unique doré (case native `role=switch`), y compris pour l'EULA |

## Retours déjà traités (tour 1)

| Retour | Réponse |
|---|---|
| La barre latérale défile avec la page | Barre fixe (`sticky`, pleine hauteur), déconnexion toujours visible |
| Plus d'animations | Apparition des pages et tuiles, survol des cartes, boutons, fenêtres, squelettes de chargement, barre de progression animée. CSS uniquement, désactivé si « réduire les animations » |
| Logos des jeux | Source déclarée dans le template (`icon: {url}` ou `{steam_appid}`), téléchargée une fois par Hivora, mise en cache et servie localement ; lettre en repli |
| Le journal sort du cadre | Cadre pleine largeur, journal de hauteur fixe, retour à la ligne |
| Le déploiement a échoué | Cause : Minecraft 26.x exige Java 25, le template figeait `java21`. Template corrigé ; en cas d'échec, les 40 dernières lignes de log du conteneur s'ajoutent au journal du job |

## Décisions prises (en plus du document de référence)

- **Compte initial `admin` / `admin`**, changement de mot de passe obligatoire avant toute autre action (403 partout ailleurs).
- **Rôles dès la V1** : admin, opérateur, lecture seule. Jamais zéro admin actif. Droits par zone reportés en V4.
- **Secrets** : jamais dans le compose. Référencés en `${HV_SECRET_*}`, valeurs dans `apps/<slug>/.env` (0600).
- **Volumes des templates** : montages bind dans `/srv/hivora/<slug>/<volume>/`, créés avec PUID/PGID.
- **Montages du conteneur Hivora** au même chemin que sur l'hôte : socket, `/opt/hivora/data`, `/srv/hivora`.
- **Accès au socket** : `docker_gateway` (API) et `compose_runner` (CLI `docker compose`) uniquement.
- **Apps adoptées** : reliées par `com.docker.compose.project`, conversion en app Hivora optionnelle (pas encore implémenté).
- **États d'une app** : Sain, Démarrage, Dégradé, Arrêté, En erreur, Absent. Un arrêt demandé (événements `kill`/`stop`) n'est pas compté comme un crash.
- **Templates officiels** figés par digest ; libellés FR/EN (`label: {fr, en}`).
- **Icônes** : le navigateur ne contacte jamais de tiers ; SVG servi avec une CSP `sandbox`.
- **Métriques par app** : échantillonnées toutes les 5 s (et non 10 s) mais uniquement pendant qu'une fiche est ouverte ; jamais de stream `stats` permanent.
- **Licence** du projet (AGPL-3.0 ou Apache-2.0) : **non tranchée**, aucune licence déclarée pour l'instant.

## Limites connues

- Jeux OVH : ports fixes (non modifiables), car le jeu annonce son port aux clients (correspondance 1:1 obligatoire).
- Les ajouts/retraits dans les listes de joueurs ne passent pas par une tâche (comme avant pour Minecraft).

- Détection des conflits de ports : ne voit que Docker et les apps Hivora (pas un sshd installé sur l'hôte).
- Métriques : en mémoire (1 h), pas encore d'historique 24 h persisté. Dans le conteneur Hivora (M6), le débit réseau de l'hôte exigera `/proc` de l'hôte monté en lecture seule.
- Console : panneau sur la fiche d'app ; le tiroir persistant multi-onglets (F-24, ⌘K, raccourci Ctrl+²) reste à faire.
- Journal d'audit : pas encore de filtres ni de recherche.
- Dérive : seulement état voulu (démarrée / arrêtée) contre état réel ; pas encore l'image modifiée à la main.
- IP publique non détectée : l'adresse d'accès utilise l'IP LAN à défaut.
- Budget frontend serré : base commune 183 Ko, page la plus lourde (`/users`) 238 Ko sur 250. Topologie et console devront être chargées à la demande.
- Non implémenté : conversion d'une app adoptée en app Hivora ; topologie : export SVG, édition réelle des réseaux (V3).

## Prochaine étape proposée : M6 (livraison)

1. Image Docker unique amd64 + arm64 < 200 Mo (build multi-étapes, binaires `docker` et `docker compose` figés, healthcheck).
2. HTTPS par défaut : certificat auto-signé généré au premier démarrage (`/opt/hivora/data/tls/`).
3. Brouillon du script `get.hivora.io` (vérifications, installation de Docker, confirmation, `--yes`, montages, affichage de l'URL).
4. Mesures en CI : taille d'image, RAM au repos ; échec si dépassement.
5. Templates restants de l'alpha : Uptime Kuma, Jellyfin, Nextcloud + PostgreSQL.
6. Correctifs : blocage de la réutilisation des codes TOTP, IP publique (détection ou réglage dans l'UI).

## Environnement de développement (VM)

- Tout le code est dans `/mnt/hgfs/shared/hivora` (partage VMware). Dépôt : `git@github.com:hiidenops/hivora.git`, branche `main`.
- Clé de déploiement : `/mnt/hgfs/shared/hivora/.hivora` (ignorée par git), copie utilisée par SSH : `~/.ssh/hivora_deploy` (0600).
- Venv Python hors du partage : `~/.venvs/hivora`. `node_modules` reste dans le partage.
- DNS de la VM : résolveurs publics (1.1.1.1, 9.9.9.9) car le DNS NAT de VMware casse les téléchargements Docker. Si `docker pull` échoue à nouveau : `/sbin/dhcpcd -n enp2s0` puis réécrire `/etc/resolv.conf`.

### Commandes utiles

```sh
# Variables pour le backend (à chaque nouveau shell)
export PATH=$HOME/.local/bin:$PATH UV_PROJECT_ENVIRONMENT=$HOME/.venvs/hivora

# Tests backend (depuis backend/)
uv run ruff check src tests && uv run mypy src tests && uv run pytest -q -p no:logging

# Frontend (depuis frontend/)
npm run lint && npm run build && npm run check:bundle
npm run e2e          # parcours Playwright (backend réel, faux Docker)
npm run gen:api      # régénérer les types TypeScript après un changement d'API
```

### Relancer le serveur de test

```sh
cd /mnt/hgfs/shared/hivora/frontend && npm run build
cd ../backend && PATH=$HOME/.local/bin:$PATH UV_PROJECT_ENVIRONMENT=$HOME/.venvs/hivora \
  HIVORA_DATA_DIR=$HOME/hivora-dev/data HIVORA_VOLUMES_ROOT=$HOME/hivora-dev/srv \
  HIVORA_CATALOG_DIR=../templates HIVORA_FRONTEND_DIR=../frontend/out \
  HIVORA_DEV_INSECURE_COOKIES=true HIVORA_HOST_LAN_IP=192.168.70.150 \
  uv run uvicorn --factory hivora.main:app --host 0.0.0.0 --port 8000
```

Puis ouvrir http://192.168.70.150:8000. Pour repartir de zéro : arrêter le serveur, supprimer les apps depuis l'UI, puis `rm -rf ~/hivora-dev`.

## Arborescence

```
hivora/
├── CLAUDE.md                  règles du projet
├── docs/                      vision/PRD/architecture, ce suivi
├── backend/src/hivora/        16 modules + web/ (dépendances HTTP) + runtime.py
├── backend/tests/             unitaires, intégration Docker (marqueur `docker`), e2e_app.py
├── frontend/                  Next.js (app/, components/, features/, lib/), e2e/
├── templates/                 minecraft/, vaultwarden/ (hivora/v1)
└── .github/workflows/ci.yml   backend, frontend + budget, e2e
```
