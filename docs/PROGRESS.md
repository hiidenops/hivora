# Hivora — Suivi d'avancement

*Dernière mise à jour : 25 septembre 2026*

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
| M6 Livraison | Image Docker, HTTPS, script d'installation | ⏳ | |
| Retours tests #3 | Fond plus discret en pinceau, graphiques continus (2 s), console toujours ouverte | ✅ | voir `git log` |
| Retours tests #4 | Fiche d'app qui ne chargeait pas (HTTP par IP), fond en trait continu | ✅ | voir `git log` |
| Minecraft, partie A | Horodatage des graphiques, « Modifier les réglages » (révisions), types de serveur et modpacks, propriétés | ✅ | voir `git log` |
| Catalogue de modpacks | Recherche Modrinth / CurseForge dans le panel, déploiement pré-rempli, clé CurseForge globale | ✅ | voir `git log` |
| Minecraft, partie B | Joueurs connectés, liste blanche (on/off + ajout/retrait), admins | ✅ | voir `git log` |
| Fiche d'app et réglages | Carte d'état, cartes repliables, versions en liste, propriétés disponibles | ✅ | voir `git log` |
| Minecraft, partie C | Gestion des mondes | ⏳ proposé | — |
| M6 Livraison | Image Docker, HTTPS, script d'installation, budgets CI, 3 templates | ⏳ à lancer | — |

Tests : 110 backend (dont 3 d'intégration sur Docker réel), 1 parcours e2e Playwright, contrôle du budget bundle. Tout passe.

## En attente de ton retour

Le serveur de test tourne sur la VM : **http://192.168.70.149:8000** (données dans `~/hivora-dev`, Docker réel), relancé avec la partie B de Minecraft. À tester :

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

▶ **Prochaine étape** : M6 (livraison).

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

- Détection des conflits de ports : ne voit que Docker et les apps Hivora (pas un sshd installé sur l'hôte).
- Un code TOTP peut être réutilisé pendant sa fenêtre de validité (30 à 90 s).
- Métriques : en mémoire (1 h), pas encore d'historique 24 h persisté. Dans le conteneur Hivora (M6), le débit réseau de l'hôte exigera `/proc` de l'hôte monté en lecture seule.
- Console : panneau sur la fiche d'app ; le tiroir persistant multi-onglets (F-24, ⌘K, raccourci Ctrl+²) reste à faire.
- Journal d'audit : pas encore de filtres ni de recherche.
- Dérive : seulement état voulu (démarrée / arrêtée) contre état réel ; pas encore l'image modifiée à la main.
- IP publique non détectée : l'adresse d'accès utilise l'IP LAN à défaut.
- Budget frontend serré : base commune 183 Ko, page la plus lourde (`/users`) 238 Ko sur 250. Topologie et console devront être chargées à la demande.
- Non implémenté : adoption de conteneurs existants, gestion des zones dans l'UI, révisions/rollback dans l'UI, logs en direct, topologie.

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
  HIVORA_DEV_INSECURE_COOKIES=true HIVORA_HOST_LAN_IP=192.168.70.149 \
  uv run uvicorn --factory hivora.main:app --host 0.0.0.0 --port 8000
```

Puis ouvrir http://192.168.70.149:8000. Pour repartir de zéro : arrêter le serveur, supprimer les apps depuis l'UI, puis `rm -rf ~/hivora-dev`.

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
