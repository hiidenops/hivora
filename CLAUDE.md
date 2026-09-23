# CLAUDE.md — Hivora

Hivora est un panneau de contrôle Docker pour homelab et serveurs de jeux : installable en une commande, simple par défaut, avancé à un clic.
Document de référence complet : `docs/vision-prd-architecture.md`. Le consulter avant toute décision d'architecture ou ajout de fonctionnalité.

## Principe d'arbitrage (à respecter partout)

**Docker est la source de vérité de l'état réel. SQLite est la source de vérité de l'intention.**
Hivora réconcilie les deux et montre toujours l'écart (dérive). Ne jamais stocker en base l'état d'exécution (up/down, CPU) : il vit en mémoire, alimenté par Docker.

## Stack

- **Un seul conteneur** en production : Python (FastAPI sous Uvicorn, un seul worker) qui sert l'API, le WebSocket et le frontend statique. Pas de Node, Redis ni PostgreSQL en prod.
- **Backend** : FastAPI + Pydantic v2, SQLAlchemy 2 + Alembic, SQLite en mode WAL, `aiodocker` (async) pour le socket, `docker compose` v2 en subprocess sur des fichiers générés.
- **Frontend** : Next.js en `output: export` (SPA statique, App Router, segments dynamiques résolus côté client), TanStack Query, store léger alimenté par le WebSocket, shadcn/ui.
- **Chargés à la demande uniquement** : React Flow + ELK (topologie), xterm.js (console), CodeMirror 6 (éditeur compose).
- **Cibles** : Linux amd64 et arm64, Docker Engine ≥ 24 avec plugin Compose v2.

## Budgets (vérifiés en CI, ne pas dépasser)

- RAM au repos < 150 Mo (10 apps), CPU au repos < 2 % d'un cœur, image Docker < 200 Mo.
- Bundle frontend initial < 250 Ko gzip.
- Tableau de bord < 1 s pour 50 apps ; état mis à jour < 2 s après un événement Docker.
- Base SQLite < 50 Mo après un an (purge métriques et logs de jobs > 30 j).

Conséquences : pas de streams `stats` permanents (échantillonnage one-shot toutes les 10 s), import paresseux des modules lourds, écritures métriques groupées toutes les 60 s.

## Règles d'implémentation backend

- Monolithe modulaire. Modules V1 : `core`, `db`, `crypto`, `auth`, `docker_gateway`, `compose_runner`, `state`, `templates`, `apps`, `zones`, `jobs`, `realtime`, `metrics`, `topology`, `audit`, `system`. Respecter le graphe de dépendances décrit dans la section 6 du document.
- `zones` ne dépend pas de `apps` : c'est `apps` qui gère l'affectation d'une app à une zone.
- **Seuls `docker_gateway` (API) et `compose_runner` (CLI `docker compose`) accèdent au socket Docker.** Aucun autre module. `docker_gateway` expose une interface abstraite (implémentation locale en V1, agent distant en V4).
- **Toute action mutante passe par `jobs`**, même courte (progression, reprise, audit homogènes).
- **Un verrou par application** : jamais deux jobs concurrents sur la même stack.
- Routes HTTP fines ; la logique vit dans des services testables sans Docker réel.
- Les identifiants Docker ne sont jamais clés primaires : on relie par labels `io.hivora.app`, `io.hivora.zone`, `io.hivora.revision`. Les apps adoptées non converties sont reliées par `com.docker.compose.project` ; leur révision 0 est une copie de `docker compose config`.
- `app_revision.compose_yaml` est l'artefact exact appliqué ; le fichier sur disque en est une copie. Toute modification crée une nouvelle révision.
- Parser Compose via `--progress json` et `docker compose config --format json`, jamais la sortie texte.
- API sous `/api/v1/...`, un WebSocket unique multiplexé sur `/ws` (canaux état, job, logs, console, métriques).

## Sécurité (non négociable)

- Accès au socket = root sur l'hôte. Le conteneur Hivora n'est jamais `privileged` et ne monte que le socket, `/opt/hivora/data` et `/srv/hivora`, **au même chemin que sur l'hôte**, pour que le compose généré contienne des chemins hôte absolus valides.
- Pas de shell sur l'hôte, seulement `exec` dans les conteneurs.
- **Les secrets n'apparaissent jamais** dans `inputs`, les logs de job, l'audit ou les logs applicatifs : ils sont référencés par clé et chiffrés en AES-GCM (clé maître `/opt/hivora/data/secret.key`, 0600).
- Auth : Argon2id, cookies `Secure`/`HttpOnly`/`SameSite=Strict`, CSRF, TOTP RFC 6238, rate limiting (5 échecs → délai exponentiel).
- Compte initial `admin` / `admin` créé au premier démarrage : tant que son mot de passe n'est pas changé, la session n'autorise que `me`, `password` et `logout` (403 partout ailleurs).
- Rôles : `admin` (tout, dont comptes et configuration), `operator` (apps, déploiements, jobs), `viewer` (lecture). Chaque route déclare son rôle minimal. Jamais zéro admin actif.
- Console : ouverture journalisée (sans les frappes), 8 sessions max, fermeture après 30 min d'inactivité.
- Docker contourne UFW : ne jamais présenter UFW comme une protection. Toute exposition `public` génère une alerte.

## Données sur disque

- `/opt/hivora/data/hivora.db`, `/opt/hivora/data/secret.key`
- `/opt/hivora/data/apps/<app_slug>/compose.yaml` (utilisable sans Hivora, secrets référencés en `${HV_SECRET_*}`), `.env` (valeurs des secrets, 0600) et `hivora.yaml` (valeurs saisies, hors secrets)
- `/opt/hivora/data/templates/<source>/` (cache des dépôts)
- `/srv/hivora/<app_slug>/<volume>/` sur l'hôte : volumes bind des apps (créés avec PUID/PGID)

## Produit

- **Pas d'enfermement** : désinstaller Hivora doit laisser des stacks compose parfaitement fonctionnelles.
- **Transparence radicale** : toute action montre son équivalent compose ou commande avant exécution.
- **Simple par défaut** : toute nouvelle option naît dans le mode avancé.
- Actions destructives : lister ce qui sera supprimé, case « supprimer aussi les données » décochée par défaut.
- Templates `hivora/v1` : YAML déclaratif, **aucune logique exécutable**, substitutions limitées (`form.*`, `secret.*`, `app.*`, `host.*`, `service.<nom>.host`) et filtres `default`, `lower`, `upper`, `quote` uniquement. Les templates officiels figent chaque image par digest ; `latest` est interdit.
- i18n FR et EN dès la V1 : aucune chaîne en dur dans l'UI, tout passe par des clés de traduction.
- Typographie : Outfit pour l'interface, JetBrains Mono pour tout ce qui est technique.

## Hors périmètre V1 (ne pas implémenter sans demande explicite)

Multi-hôtes, droits par zone, sauvegardes planifiées, reverse proxy managé, import compose, gestion du pare-feu, marketplace communautaire. Jamais : VM, LXC, Kubernetes, Swarm.

## Conventions de travail

- Langue du code et des commentaires : anglais. Documentation produit : français.
- Toute migration de schéma passe par Alembic.
- Si une demande contredit ce fichier ou le document de référence, le signaler avant de coder.
