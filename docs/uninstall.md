# Uninstalling

Removing the panel does not remove your apps: they are plain Docker Compose projects and
keep running without it.

## Remove the panel only

```sh
sudo docker rm -f hivora
```

Your data stays in `/opt/hivora/data` and `/srv/hivora`; running the installer again brings
the panel back as it was.

## Remove everything

1. **The apps**: remove them from the panel first (each app's page → Remove, with its
   data if you want). This includes the **Admin VPN** app: switch to the local network mode
   first (`sudo sh install.sh --access lan`), then remove it.
2. **The panel**:
   ```sh
   sudo docker rm -f hivora
   ```
3. **The networks** Hivora created for its zones:
   ```sh
   sudo docker network ls --filter label=io.hivora.zone-network=1 -q | xargs -r sudo docker network rm
   ```
4. **The data** (irreversible: the apps' data and their backups too):
   ```sh
   sudo rm -rf /opt/hivora /srv/hivora
   ```
5. Optionally, the image: `sudo docker image rm ghcr.io/hiidenops/hivora:<version>`.

Docker itself is left installed.
