# Troubleshooting

## First look

- **Settings → Panel health**: database, disk space, Docker, jobs, panel backup, exposure,
  certificate and admin VPN, each with its state.
- The panel's logs:
  ```sh
  sudo docker logs hivora
  ```
- Any installer run can be previewed with `--dry-run`.

## Lost password

From the machine, a new random password for an account (to change at next login; its
sessions end):

```sh
sudo docker exec hivora python -m hivora reset-admin-password          # admin
sudo docker exec hivora python -m hivora reset-admin-password alice    # another account
```

Another admin can also reset it from **Users**.

## Lost two-factor device and recovery codes

Turn two-factor authentication off for an account (its sessions end; in the Internet mode
it must be set up again at next login):

```sh
sudo docker exec hivora python -m hivora reset-totp          # admin
sudo docker exec hivora python -m hivora reset-totp alice
```

## No access through the admin VPN

See [Admin VPN → Lost access](admin-vpn.md#lost-access): new keys with `--rescue-admin`,
or the local network mode with `--access lan`.

## The installer refuses to run

| Message | What to do |
|---|---|
| port … is already in use | choose another with `--port N` (or `--vpn-port N` for the VPN) |
| only has a public address | the machine is a VPS: use `--access vpn` (or `--bind IP`) |
| overlaps 10.254.253.0/24 or 10.254.254.0/24 | your network uses the admin VPN's addresses: use `--access lan` |
| the Docker network hivora-zone-administration exists with another address range | follow the message: move the Administration zone's apps, remove the network, run again |
| Docker Engine 24 or newer is needed | update Docker |

## A banner says the panel is published on every address

The panel listens on all addresses (the Internet) while its access mode is not `public`, so
two-factor authentication is not enforced. Run the installer again with `--access lan`
(or `--access public` to accept it, with two-factor authentication for everyone).
