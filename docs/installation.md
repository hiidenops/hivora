# Installation

Hivora tourne dans un seul conteneur Docker (`hivora`) sur une machine Linux. L'installeur
le met en place ; le relancer le met à jour ou change ses options.

## Prérequis

- Debian 12+, Ubuntu 22.04+ ou Raspberry Pi OS 64 bits (les autres distributions Linux
  fonctionnent « au mieux », après un avertissement)
- un processeur amd64 ou arm64
- un accès root (`sudo`)
- Docker Engine 24 ou plus récent ; l'installeur propose de l'installer s'il manque
  (Docker sans root et Podman ne sont pas pris en charge)

## Une commande

```sh
sudo sh -c "$(curl -fsSL https://github.com/hiidenops/hivora/releases/latest/download/install.sh)"
```

### Vérifier le script d'abord

Chaque release publie `install.sh` avec sa somme SHA-256 :

```sh
curl -fsSLO https://github.com/hiidenops/hivora/releases/latest/download/install.sh
curl -fsSLO https://github.com/hiidenops/hivora/releases/latest/download/install.sh.sha256
sha256sum -c install.sh.sha256 && sudo sh install.sh
```

## Ce que demande l'installeur

1. **La langue** : Français ou English (pour l'installeur seulement ; le panel a son propre
   réglage).
2. **La façon d'accéder au panel** (voir [Modes d'accès](#modes-daccès)).
3. En mode VPN, **l'adresse publique** qu'utiliseront vos appareils : celle détectée, ou une
   adresse IP ou un nom de domaine que vous saisissez.
4. Un **récapitulatif**, puis *Continuer ?*

Dans un terminal, les questions s'affichent dans des fenêtres (whiptail, présent d'office
sur Debian, Ubuntu et Raspberry Pi OS ; flèches et Entrée pour choisir), puis une fenêtre
suit les étapes de l'installation. Sans whiptail, ou avec `HIVORA_UI=text`
(`sudo HIVORA_UI=text sh -c "$(curl ...)"`), les mêmes questions sont posées en texte.

À la fin, il affiche l'URL du panel, l'utilisateur `admin` et son mot de passe (une seule
fois).

## Modes d'accès

| Mode | Le panel est joignable | Ports ouverts sur la machine |
|---|---|---|
| Réseau local uniquement (`lan`) | depuis votre réseau local | le port du panel, sur l'adresse LAN |
| Réseau local + VPN (`vpn+lan`, par défaut) | depuis votre réseau, et de partout par WireGuard | le port du panel sur l'adresse LAN, et un port UDP pour le VPN |
| Uniquement par le VPN (`vpn`) | par WireGuard seulement | un port UDP pour le VPN |
| Internet (`public`, déconseillé) | de partout | le port du panel sur toutes les adresses ; la double authentification devient obligatoire |

Sur une machine qui n'a qu'une adresse IP publique (un VPS), les deux modes « réseau local »
sont refusés (ils publieraient le panel sur Internet sans les protections du mode
Internet) : le défaut y est `vpn`. `--bind IP` passe outre si vous savez ce que vous faites.

Pour changer de mode plus tard, relancez l'installeur avec `--reconfigure`.

## Options (installations automatiques)

Sans terminal, ou avec `--yes`, l'installeur ne pose aucune question et utilise les options,
puis celles enregistrées, puis les valeurs par défaut ; ses messages sont en anglais, sauf
avec `--lang fr`.

```sh
sudo sh -c "$(curl -fsSL https://github.com/hiidenops/hivora/releases/latest/download/install.sh)" install.sh \
  --yes --lang fr --access vpn+lan --vpn-host maison.example.org
```

| Option | Rôle |
|---|---|
| `--yes` | aucune question (le mode Internet demande aussi `--i-understand`) |
| `--dry-run` | afficher les commandes, ne rien changer |
| `--lang fr\|en` | la langue de l'installeur |
| `--version TAG` | la version d'Hivora (par défaut : celle de la release du script) |
| `--image REF` | une autre image (par défaut `ghcr.io/hiidenops/hivora`) |
| `--access MODE` | `vpn+lan`, `vpn`, `lan` ou `public` |
| `--reconfigure` | redemander la façon d'accéder au panel |
| `--port N` | le port du panel sur la machine (8443) |
| `--bind IP` | l'adresse sur laquelle le panel écoute |
| `--vpn-host HOST` | l'adresse à laquelle se connectent les clients VPN (par défaut : l'IP publique) |
| `--vpn-port N` | le port UDP du VPN d'administration (51820) |
| `--rescue-admin` | de nouvelles clés pour le client du VPN d'administration (voir [VPN d'administration](admin-vpn.md)) |
| `--data DIR` | les données du panel (`/opt/hivora/data`) |
| `--srv DIR` | les volumes des applications (`/srv/hivora`) |
| `--i-understand` | confirme `--access public` avec `--yes` |

Les options sont gardées dans `/opt/hivora/data/install.env` et reprises à chaque relance.

## Première connexion

- Ouvrez l'URL affichée à la fin. Le certificat est auto-signé : votre navigateur vous
  avertit une fois, c'est normal.
- Connectez-vous en `admin` avec le mot de passe affiché par l'installeur, puis choisissez
  le vôtre.
- Activez la double authentification dans **Paramètres** (obligatoire en mode Internet).

## Sans l'installeur : Docker Compose

[`deploy/compose.yaml`](../deploy/compose.yaml) fait tourner Hivora sur le réseau local
seulement :

```sh
HIVORA_BIND=192.168.1.10 docker compose -f deploy/compose.yaml up -d
```

`HIVORA_BIND` est l'adresse LAN de cette machine. La première connexion est alors `admin` /
`admin`, à changer tout de suite. Ce mode n'a pas de VPN d'administration.
