# Admin VPN

In the `vpn+lan` and `vpn` access modes, the panel is reached through a WireGuard VPN that
Hivora sets up itself. Nothing else is needed on your router than one UDP port.

## How it works

- The panel's container joins the Docker network of the **Administration** zone
  (`hivora-zone-administration`, `10.254.254.0/24`) at a fixed address: **`10.254.254.254`**.
- On start, the server deploys an app named **Admin VPN** (WireGuard) in that zone, with a
  client named `admin` that reaches that zone only (neither the Internet nor your local
  network go through it). VPN addresses: `10.254.253.0/24`.
- The client's configuration is written to `/opt/hivora/data/admin.conf` (readable by root
  only).
- In these modes the Admin VPN app and its `admin` client cannot be deleted or disabled
  from the panel.

## Connecting a device

1. Install the WireGuard app (phone or computer).
2. Forward the VPN's UDP port (51820 by default) from your router to this machine.
3. Import `admin.conf`, or scan its QR code:
   ```sh
   sudo docker exec hivora python -m hivora admin-vpn
   ```
   (in `vpn+lan` mode the QR code is also in the panel: Applications → Admin VPN).
4. Turn the tunnel on and open **https://10.254.254.254:8443**.

## Changing the address or the port

The address your devices connect to and the UDP port come from the installation:

```sh
sudo sh install.sh --vpn-host home.example.org   # or --vpn-port 51830, or --reconfigure
```

The VPN is updated at the panel's next start (it restarts for a few seconds). Devices keep
their keys: change *Endpoint* in their WireGuard app, or import the new configuration.
While the installation sets them, these two settings cannot be changed in the panel.

## Lost access

- **New keys** for the `admin` client (a lost or leaked `admin.conf`):
  ```sh
  sudo sh install.sh --rescue-admin
  ```
  The old configuration stops working; the new QR code is shown.
- **No VPN at all**: from the machine itself, switch to the local network mode:
  ```sh
  sudo sh install.sh --access lan
  ```
