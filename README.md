# Hivora

[![Licence : AGPL-3.0](https://img.shields.io/badge/licence-AGPL--3.0-blue)](LICENSE)
[![Version](https://img.shields.io/github/v/release/hiidenops/hivora?include_prereleases)](https://github.com/hiidenops/hivora/releases)
[![CI](https://github.com/hiidenops/hivora/actions/workflows/ci.yml/badge.svg)](https://github.com/hiidenops/hivora/actions/workflows/ci.yml)

## Hivora en quelques mots

Hivora est un panel web auto-hébergé pour une machine Linux : installez des applications et
des serveurs de jeux depuis un catalogue, faites-les tourner avec Docker, rangez-les en zones,
accédez au panel par son propre VPN WireGuard, et gardez tout sauvegardé. Un conteneur, une
commande pour l'installer, en français ou en anglais.

## Fonctionnalités clés

- **Catalogue** : applications (Nextcloud, Jellyfin, Immich, Vaultwarden, Home Assistant…),
  bases de données et serveurs de jeux (Minecraft et ses modpacks, Valheim, Palworld,
  Terraria…), ou n'importe quelle image Docker
- **Zones et topologie** : regroupez les applications, reliez leurs réseaux, voyez ce qui est
  exposé et comment
- **VPN d'administration** : le panel joignable uniquement par WireGuard, avec un QR code à
  scanner
- **Sauvegardes** : par application, à la demande ou planifiées ; chaque modification est une
  révision vers laquelle revenir
- **Pare-feu de l'hôte** : règles UFW, fail2ban, adresses bloquées, routes statiques
- **Santé du panel et mises à jour** : disque, Docker, tâches, exposition, versions disponibles
- **Utilisateurs et rôles**, double authentification, journal d'audit

## Installation rapide

Sur Debian 12+, Ubuntu 22.04+ ou Raspberry Pi OS 64 bits (amd64 ou arm64), en root :

```sh
curl -fsSL https://github.com/hiidenops/hivora/releases/latest/download/install.sh | sudo sh
```

L'installeur met en place Docker si besoin, demande sa langue et la façon dont vous
accéderez au panel, puis affiche l'URL et le mot de passe administrateur. Options,
installations automatiques et vérification du script : [docs/installation.md](docs/installation.md).

## Modes d'accès

| Mode | Accès au panel |
|---|---|
| Réseau local uniquement | depuis votre réseau local |
| Réseau local + VPN (par défaut) | depuis votre réseau, et de partout par WireGuard |
| Uniquement par le VPN | par WireGuard seulement |
| Internet (avancé) | de partout ; double authentification obligatoire |

Sur une machine qui n'a qu'une IP publique (un VPS), le défaut est *Uniquement par le VPN*.
Changez de mode plus tard avec `--reconfigure`. Détails : [docs/admin-vpn.md](docs/admin-vpn.md).

## Première connexion

Connectez-vous en `admin` avec le mot de passe affiché par l'installeur (il n'est montré
qu'une fois), puis choisissez le vôtre. Activez la double authentification dans
**Paramètres**. Le certificat est auto-signé : votre navigateur vous avertit une fois, c'est
normal.

## Captures d'écran

| Tableau de bord | Catalogue | Santé du panel |
|---|---|---|
| ![Tableau de bord](docs/images/dashboard.png) | ![Catalogue](docs/images/catalog.png) | ![Santé du panel](docs/images/health.png) |

## Documentation

- [Installation](docs/installation.md) : prérequis, options, modes d'accès, Docker Compose
- [VPN d'administration](docs/admin-vpn.md) : fonctionnement, connecter un appareil, accès perdu
- [Mises à jour](docs/updating.md) : nouvelles versions, mise à jour, retour arrière
- [Sauvegardes](docs/backups.md) : le panel, les applications, changer de machine
- [Dépannage](docs/troubleshooting.md) : journaux, mot de passe ou appareil de double authentification perdu
- [Désinstallation](docs/uninstall.md)

Historique des versions : [CHANGELOG.md](CHANGELOG.md) et les
[GitHub Releases](https://github.com/hiidenops/hivora/releases), dont les notes en sont tirées.

## Sécurité

Hivora pilote Docker sur sa machine, ce qui revient à un accès root : gardez le panel sur
votre réseau local ou derrière son VPN, et activez la double authentification. Docker
contourne UFW. Le panel ne contacte des tiers que pour ce que vous utilisez : GitHub
(nouvelles versions, désactivable), `api.ipify.org` (l'adresse publique), les registres
d'images et les sources du catalogue.

Signalez les vulnérabilités en privé :
[signaler une vulnérabilité](https://github.com/hiidenops/hivora/security/advisories/new)
(voir [SECURITY.md](SECURITY.md)).

## Licence

[AGPL-3.0](LICENSE). Le panel donne un lien vers le code source de la version qu'il exécute.

## Développement

Le serveur est en Python (FastAPI, SQLite), le panel en Next.js ; les tests tournent sans
vrai Docker :

```sh
cd backend && uv run pytest -q
cd frontend && npm ci && npm test && npx playwright test
```

Plus : [docs/development.md](docs/development.md) et [docs/releasing.md](docs/releasing.md).
