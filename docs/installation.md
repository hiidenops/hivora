# Installation

Hivora runs as one Docker container (`hivora`) on a Linux machine. The installer sets it
up, and running it again updates it or changes its options.

## Requirements

- Debian 12+, Ubuntu 22.04+ or Raspberry Pi OS 64-bit (other Linux distributions work
  on a best-effort basis, after a warning)
- an amd64 or arm64 CPU
- root access (`sudo`)
- Docker Engine 24 or newer; the installer offers to install it if it is missing
  (rootless Docker and Podman are not supported)

## One command

```sh
curl -fsSL https://github.com/hiidenops/hivora/releases/latest/download/install.sh | sudo sh
```

### Checking the script first

Every release publishes `install.sh` with its SHA-256 checksum:

```sh
curl -fsSLO https://github.com/hiidenops/hivora/releases/latest/download/install.sh
curl -fsSLO https://github.com/hiidenops/hivora/releases/latest/download/install.sh.sha256
sha256sum -c install.sh.sha256 && sudo sh install.sh
```

## What the installer asks

1. **Language**: Français or English (for the installer only; the panel has its own setting).
2. **How you will reach the panel** (see [Access modes](#access-modes)).
3. In the VPN modes, **the public address** your devices will use: the detected one, or an
   IP address or domain name you type.
4. A **summary**, then *Continue?*

At the end it shows the panel's URL, the `admin` user and its password (once only).

## Access modes

| Mode | The panel is reached | Ports opened on the machine |
|---|---|---|
| Local network only (`lan`) | from your local network | the panel's port, on the LAN address |
| Local network + VPN (`vpn+lan`, default) | from your network, and from anywhere through WireGuard | the panel's port on the LAN address, and a UDP port for the VPN |
| Only through the VPN (`vpn`) | through WireGuard only | a UDP port for the VPN |
| Internet (`public`, not recommended) | from everywhere | the panel's port on every address; two-factor authentication becomes mandatory |

On a machine that only has a public IP address (a VPS), the two local network modes are
refused (they would publish the panel on the Internet without the protections of the
Internet mode): the default there is `vpn`. `--bind IP` overrides this if you know what
you are doing.

To change the mode later, run the installer again with `--reconfigure`.

## Options (automated installs)

Without a terminal, or with `--yes`, the installer asks nothing and uses the options, then
the saved ones, then the defaults; its messages are in English unless `--lang fr`.

```sh
curl -fsSL https://github.com/hiidenops/hivora/releases/latest/download/install.sh \
  | sudo sh -s -- --yes --lang en --access vpn+lan --vpn-host home.example.org
```

| Option | Meaning |
|---|---|
| `--yes` | no questions (the Internet mode still needs `--i-understand`) |
| `--dry-run` | show the commands, change nothing |
| `--lang fr\|en` | the installer's language |
| `--version TAG` | the Hivora version (default: the script's own release) |
| `--image REF` | another image (default `ghcr.io/hiidenops/hivora`) |
| `--access MODE` | `vpn+lan`, `vpn`, `lan` or `public` |
| `--reconfigure` | ask again how the panel is reached |
| `--port N` | the panel's port on the machine (8443) |
| `--bind IP` | the address the panel listens on |
| `--vpn-host HOST` | the address VPN clients connect to (default: the public IP) |
| `--vpn-port N` | the admin VPN's UDP port (51820) |
| `--rescue-admin` | new keys for the admin VPN client (see [Admin VPN](admin-vpn.md)) |
| `--data DIR` | the panel's data (`/opt/hivora/data`) |
| `--srv DIR` | the apps' volumes (`/srv/hivora`) |
| `--i-understand` | confirms `--access public` with `--yes` |

The options are kept in `/opt/hivora/data/install.env` and reused by every later run.

## First login

- Open the URL shown at the end. The certificate is self-signed: your browser warns once,
  that is expected.
- Sign in as `admin` with the password shown by the installer, then choose your own.
- Turn on two-factor authentication in **Settings** (mandatory in the Internet mode).

## Without the installer: Docker Compose

[`deploy/compose.yaml`](../deploy/compose.yaml) runs Hivora on the local network only:

```sh
HIVORA_BIND=192.168.1.10 docker compose -f deploy/compose.yaml up -d
```

`HIVORA_BIND` is this machine's LAN address. The first login is then `admin` / `admin`,
to change right away. There is no admin VPN in this setup.
