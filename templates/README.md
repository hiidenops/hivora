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
