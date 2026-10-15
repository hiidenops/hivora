# Updating

## Knowing that a new version exists

**Settings → Updates** shows the installed version, the channel (Stable or Pre-releases),
the latest published version with its notes, and the command to update. A blue dot on
**Settings** means a newer version exists. The check reads the project's GitHub Releases at
most every 12 hours and sends nothing but a `User-Agent` header; it can be turned off in
the same card (then no request is made at all).

The history of every version is in [`CHANGELOG.md`](../CHANGELOG.md) and on the
[GitHub Releases](https://github.com/hiidenops/hivora/releases) page.

## Updating

Run the new release's installer on the machine (the card shows the exact command):

```sh
curl -fsSL https://github.com/hiidenops/hivora/releases/download/vX.Y.Z/install.sh | sudo sh
```

It keeps your options (`install.env`), backs the panel up, replaces the `hivora` container
and starts the new version. Your apps keep running during the update.

## Going back (rollback)

Every update first saves the panel in `/opt/hivora/data/backups/_hivora/` (the database,
the master key and `install.env`). To go back to the previous version:

```sh
sudo docker rm -f hivora
sudo rm -f /opt/hivora/data/hivora.db-wal /opt/hivora/data/hivora.db-shm
sudo tar -xzf /opt/hivora/data/backups/_hivora/panel-<date>-r<revision>.tar.gz -C /opt/hivora/data
sudo sh install.sh --version vX.Y.Z      # the previous version
```

Removing `hivora.db-wal` and `hivora.db-shm` matters: they belong to the database being
replaced, and SQLite would apply them to the restored one (a damaged database).

A newer database is never opened by an older Hivora: restoring the archive made before the
update is what makes the rollback possible. If an update fails, the installer prints these
commands with the right file names.
