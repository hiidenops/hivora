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
