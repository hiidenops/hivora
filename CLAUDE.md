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
- Bundle frontend initial < 520 Ko gzip par page (relevé de 250 Ko le 28/09/2026).
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
- Pas de shell sur l'hôte, seulement `exec` dans les conteneurs. **Exception validée le 29/09/2026** : l'agent hôte optionnel (`hostfw`, conteneur `hivora-host-agent` privilégié, PID/réseau de l'hôte) n'exécute que des lignes de commande fixes (`ufw`, `fail2ban-client`, `ss`, `ip route`, et depuis le 09/10/2026 `conntrack -L -p tcp --state ESTABLISHED`, en lecture seule, sans argument venant de l'utilisateur, pour lister les connexions vers les apps Docker) aux arguments validés, jamais du code shell construit ; seules écritures : `jail.d/hivora.local`, contenu généré par Hivora passé en argument d'un script fixe, et, depuis le 09/10/2026, l'installation du seul paquet `conntrack` (`apt-get install -y --no-install-recommends conntrack`, précédée au besoin d'un `apt-get update`, lignes fixes, par un job, Debian et Ubuntu seulement) ; et, depuis le 09/10/2026 (lot K), le **blocage d'adresses IP** pour l'hôte et les apps Docker : `iptables` et `ip6tables` en lignes fixes (`-S HIVORA-BLOCK`, `-N HIVORA-BLOCK`, `-C`/`-I INPUT 1 -j HIVORA-BLOCK`, `-C`/`-I DOCKER-USER 1 -j HIVORA-BLOCK`), puis `iptables-restore --noflush` / `ip6tables-restore --noflush` d'un contenu généré par Hivora qui ne touche que la chaîne `HIVORA-BLOCK` (une règle `-s <IP> -j DROP` par adresse validée, IP seule, pas de réseau), passé en argument d'un script fixe, appliqué par un job et réappliqué au démarrage ; l'IP de l'admin qui fait la demande est toujours refusée ; et, depuis le 12/10/2026 (lot R), les **routes statiques IPv4** de l'hôte : `ip -j route show proto 241` (lecture), puis `ip route replace <réseau> via <passerelle> [dev <interface>] [metric <n>] proto 241` et `ip route del <réseau> proto 241`, lignes fixes aux arguments validés, appliquées par un job depuis la base et réappliquées au démarrage ; Hivora ne touche que les routes marquées `proto 241`, jamais celles de DHCP, du noyau, de Docker ou posées à la main ; refusés : la route par défaut, une destination qui contient l'IP de l'admin qui fait la demande ou recouvre un réseau directement connecté, une passerelle hors des réseaux directement connectés, une interface inconnue ; désactivé par défaut, admin + TOTP récent, tout est audité.
- **Les secrets n'apparaissent jamais** dans `inputs`, les logs de job, l'audit ou les logs applicatifs : ils sont référencés par clé et chiffrés en AES-GCM (clé maître `/opt/hivora/data/secret.key`, 0600).
- Auth : Argon2id, cookies `Secure`/`HttpOnly`/`SameSite=Strict`, CSRF, TOTP RFC 6238, rate limiting (5 échecs → délai exponentiel).
- Compte initial `admin` : **mot de passe aléatoire** créé par l'installeur (`python -m hivora bootstrap`, décision D3 du 14/10/2026) et affiché une fois ; `admin` / `admin` seulement pour un lancement manuel sans installeur (`deploy/compose.yaml`). Dans les deux cas, tant que son mot de passe n'est pas changé, la session n'autorise que `me`, `password` et `logout` (403 partout ailleurs).
- **Mode d'accès public** (panel publié sur toutes les adresses, `HIVORA_ACCESS=public`, lu dans `Settings.access`, jamais stocké) : TOTP obligatoire pour tous les comptes avant toute autre action (D4, M12-4b). Après le changement du mot de passe initial, seules `health`, `login`, `me`, `password`, `logout`, `totp/enroll` et `totp/confirm` répondent ; tout le reste renvoie `403 totp_setup_required` et le WebSocket se ferme (`4403`) ; le TOTP ne peut pas y être désactivé (`409 totp_mandatory`). Récupération : codes de secours, réinitialisation par un autre admin (qui coupe les sessions du compte), ou sur la machine `python -m hivora reset-totp [utilisateur]`.
- Rôles : `admin` (tout, dont comptes et configuration), `operator` (apps, déploiements, jobs), `viewer` (lecture). Chaque route déclare son rôle minimal. Jamais zéro admin actif.
- Console : ouverture journalisée (sans les frappes), 8 sessions max, fermeture après 30 min d'inactivité.
- Docker contourne UFW : ne jamais présenter UFW comme une protection. Toute exposition `public` génère une alerte.
- **Accès d'administration** (M12, 14/10/2026) : modes `VPN + LAN` (défaut), `VPN uniquement`, `public`, fixés au lancement (`/opt/hivora/data/install.env`, jamais modifiés par Hivora lui-même). Pour le VPN, le conteneur `hivora` rejoint le réseau de la zone Administration à une IP fixe ; aucun port du panel n'est publié pour cela. Hivora ne crée, ne recrée ni ne supprime **son propre conteneur** : l'auto-mise à jour (`hivora-updater`, M13) demandera une exception validée ici avant d'être codée.

## Données sur disque

- `/opt/hivora/data/hivora.db`, `/opt/hivora/data/secret.key`
- `/opt/hivora/data/apps/<app_slug>/compose.yaml` (utilisable sans Hivora, secrets référencés en `${HV_SECRET_*}`), `.env` (valeurs des secrets, 0600) et `hivora.yaml` (valeurs saisies, hors secrets)
- `/opt/hivora/data/templates/<source>/` (cache des dépôts)
- `/opt/hivora/data/install.env` (0600) : options de lancement du conteneur écrites par l'installeur (version, mode d'accès, port, adresses) ; `admin.conf` (0600, client VPN d'administration, régénérable) ; `backups/_hivora/` (sauvegardes du panel avant mise à jour)
- `/srv/hivora/<app_slug>/<volume>/` sur l'hôte : volumes bind des apps (créés avec PUID/PGID)

## Produit

- **Pas d'enfermement** : désinstaller Hivora doit laisser des stacks compose parfaitement fonctionnelles.
- **Transparence radicale** : toute action montre son équivalent compose ou commande avant exécution.
- **Simple par défaut** : toute nouvelle option naît dans le mode avancé.
- Actions destructives : lister ce qui sera supprimé, case « supprimer aussi les données » décochée par défaut.
- Templates `hivora/v1` : YAML déclaratif, **aucune logique exécutable**, substitutions limitées (`form.*`, `secret.*`, `app.*`, `host.*`, `service.<nom>.host`, et depuis le 13/10/2026, lot B, `link.<champ>.host|port|database|user|password` : l'app choisie par un champ « lien vers une app » du formulaire, que le modèle de cette app décrit dans sa section déclarative `connection` ; l'outil rejoint alors le réseau Docker de cette app ; `link.<champ>.password` est un secret : jamais écrit dans le compose, seulement dans le `.env` (0600) de l'outil, et seulement si l'utilisateur a demandé la connexion automatique) et filtres `default`, `lower`, `upper`, `quote` uniquement. Les templates officiels figent chaque image par digest ; `latest` est interdit.
- i18n FR et EN dès la V1 : aucune chaîne en dur dans l'UI, tout passe par des clés de traduction.
- Typographie : Outfit pour l'interface, JetBrains Mono pour tout ce qui est technique.

## Distribution (décisions D1 à D10 du 14/10/2026, détail : document de référence, « Installation », « VPN d'administration », « Distribution et versions »)

- **Licence** : AGPL-3.0.
- **Installation** : `curl -fsSL https://github.com/hiidenops/hivora/releases/latest/download/install.sh | sudo sh` (script et `.sha256` publiés dans chaque GitHub Release ; pas de domaine ni de service tiers). Le script ne touche jamais la base ni les fichiers des apps : il délègue à `python -m hivora bootstrap` dans le conteneur, qui passe par les services et les jobs.
- **Base** : SQLite seulement (pas de PostgreSQL, D2).
- **Versions** : le tag git `vX.Y.Z` est la source de vérité, égal à la version du paquet ; version disponible lue dans les GitHub Releases (vérification activée par défaut, désactivable, sans télémétrie) ; `CHANGELOG.md` en français.
- **Mise à jour** : relancer le script (sauvegarde du panel avant). Bouton « Mettre à jour » reporté à M13.
- **Distributions supportées** : Debian 12+, Ubuntu 22.04+, Raspberry Pi OS 64 bits.
- **Installeur interactif** (M12-5c, décisions D11 à D16 du 15/10/2026) : français ou anglais au premier écran (`--lang` ; sans question : anglais ; gardé dans `install.env`), indépendant de la langue du panel (D16 refusée) ; mode d'accès choisi dans un menu à la première installation (défaut : VPN + LAN sur IP privée, VPN seul sans réseau privé, D15) ; sur une machine sans IP privée, `lan` et `vpn+lan` refusés sauf `--bind` (D13) ; adresse publique du VPN détectée par `api.ipify.org` (seul appel à un tiers de l'installeur, en mode interactif VPN, D12), toujours confirmée ou remplacée par l'utilisateur ; QR code dans le terminal seulement en mode VPN seul (D14) ; aucune question avec `--yes` ni sans terminal. Changer l'adresse ou le port d'un VPN d'administration existant : lot M12-5d (D17).

## Hors périmètre V1 (ne pas implémenter sans demande explicite)

Multi-hôtes, droits par zone, reverse proxy managé, import compose, marketplace communautaire. (Faits sur demande : sauvegardes planifiées, pare-feu de l'hôte via l'agent.) Jamais : VM, LXC, Kubernetes, Swarm.

## Conventions de travail

- Langue du code et des commentaires : anglais. Documentation produit : français.
- Toute migration de schéma passe par Alembic.
- Si une demande contredit ce fichier ou le document de référence, le signaler avant de coder.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
