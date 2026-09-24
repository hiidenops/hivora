# Hivora — Suivi d'avancement

*Dernière mise à jour : 24 septembre 2026*

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
| Retours tests #3 | Fond plus discret en pinceau, graphiques continus (2 s), console toujours ouverte | ✅ | voir `git log` |
| Retours tests #4 | Fiche d'app qui ne chargeait pas (HTTP par IP), fond en trait continu | ✅ | voir `git log` |
| M6 Livraison | Image Docker, HTTPS, script d'installation, budgets CI, 3 templates | ⏳ à lancer | — |

Tests : 110 backend (dont 3 d'intégration sur Docker réel), 1 parcours e2e Playwright, contrôle du budget bundle. Tout passe.

## En attente de ton retour

Le serveur de test tourne sur la VM : **http://192.168.70.149:8000** (données dans `~/hivora-dev`, Docker réel), relancé avec le tour 2. À tester :

1. **Console** : fiche d'une app démarrée → « Ouvrir la console ». Minecraft : onglet « Console serveur » (`rcon-cli`) + guide des commandes repliable ; toute app : onglet « Shell ».
2. **Activité** : graphiques CPU / RAM / réseau (un point toutes les 10 s), boutons « Vider ».
3. Interrupteurs dorés, fond en grille, alignements pendant un déploiement (bureau et mobile).

Si la VM a redémarré, voir « Relancer le serveur de test » plus bas.

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
