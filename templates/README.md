# Templates officiels Hivora

Templates `hivora/v1` (voir `docs/vision-prd-architecture.md`, section 8). Chaque image est épinglée par digest ; `latest` est interdit.

## Alpha V0.x

Cinq templates multi-architecture (amd64 + arm64), testables sur toute machine :

| Slug | Application | Catégorie | Intérêt pour l'alpha |
|---|---|---|---|
| `minecraft` | Minecraft Java (itzg/minecraft-server) | Jeux | Critère de sortie V0.x, port de jeu public |
| `vaultwarden` | Vaultwarden | Productivité | Critère de sortie V0.x, secrets générés |
| `uptime-kuma` | Uptime Kuma | Services | App web simple à un service |
| `jellyfin` | Jellyfin | Médias | Volumes bind multiples |
| `nextcloud` | Nextcloud + PostgreSQL | Productivité | Stack multi-services, dépendances, healthchecks |

## Outils d'administration (lot L1, 01/10/2026)

Images officielles Docker Hub, variantes Alpine, multi-architecture (amd64 + arm64), figées par digest, suivi des versions `minor` :

| Slug | Application | Catégorie | Image | Port par défaut | Volume sauvegardé |
|---|---|---|---|---|---|
| `nginx` | nginx (serveur web statique) | Services | `nginx:1.30.5-alpine` | 8085 | `html` (vide au départ : 403 tant qu'aucun fichier n'y est déposé) |
| `httpd` | Apache HTTP Server (serveur web statique) | Services | `httpd:2.4.68-alpine` | 8086 | `htdocs` (vide au départ : liste vide) |
| `adminer` | Adminer (interface des bases de données) | Développement | `adminer:5.5.1-standalone` | 8087 | aucun (pas de données) ; serveur par défaut facultatif (`ADMINER_DEFAULT_SERVER`) |

## Outils d'administration des bases (13/10/2026)

Multi-architecture (amd64 + arm64), figées par digest, suivi des versions `minor`, exposition LAN. Chacun se connecte à une base de la même zone (zone « reliées entre elles »), par le nom de son conteneur `<nom de l'app>-server-1`.

| Slug | Application | Catégorie | Image | Port par défaut | Données |
|---|---|---|---|---|---|
| `phpmyadmin` | phpMyAdmin (MariaDB / MySQL) | Développement | `phpmyadmin:5.2.3-apache` (officielle) | 8088 | aucune ; serveur par défaut facultatif (`PMA_HOST`, utilisé quand le champ « Serveur » de la page de connexion reste vide ; `PMA_ARBITRARY=1` : tout autre serveur joignable) ; taille d'import en mode avancé (`UPLOAD_LIMIT`, 64M) |
| `pgadmin` | pgAdmin 4 (PostgreSQL) | Développement | `dpage/pgadmin4:9.18.0` (éditeur) | 8089 | volume `data` (`/var/lib/pgadmin`, propriétaire `5050:5050`, sauvegardé) ; e-mail et mot de passe de connexion demandés au déploiement (mot de passe chiffré) ; l'e-mail refuse les domaines à usage spécial que pgAdmin refuse au démarrage (`.local`, `.localhost`, `.test`, `.invalid`, `.onion`, `home.arpa`) ; vérification de mise à jour de pgAdmin coupée (`PGADMIN_CONFIG_UPGRADE_CHECK_ENABLED=False`) |

## Bases de données (lot L2, 01/10/2026)

Images officielles Docker Hub, amd64 + arm64, figées par digest, suivi `minor` (jamais de changement de version majeure automatique : migration manuelle ; une sauvegarde ne se restaure que sur la même version majeure). **Joignables uniquement par les apps de la même zone** (zone « reliées entre elles »), à l'adresse `<nom de l'app>-server-1:<port>` ; l'ouverture sur le réseau local viendra avec une correction du moteur. Mots de passe choisis par l'utilisateur (12 caractères au moins, jamais réaffichés).

| Slug | Application | Image | Port (interne) | Volume sauvegardé | Healthcheck |
|---|---|---|---|---|---|
| `postgresql` | PostgreSQL 18 | `postgres:18.6-alpine` | 5432 | `data` → `/var/lib/postgresql` | `pg_isready` |
| `mariadb` | MariaDB 11.8 LTS | `mariadb:11.8.9` | 3306 | `data` → `/var/lib/mysql` | `healthcheck.sh --connect --innodb_initialized` ; `MARIADB_AUTO_UPGRADE` ; mot de passe root généré (masqué) |
| `redis` | Redis 8 | `redis:8.10.2-alpine` | 6379 | `data` → `/data` (AOF) | `redis-cli ping` (`REDISCLI_AUTH`) |
