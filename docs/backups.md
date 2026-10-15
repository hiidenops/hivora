# Backups

## The panel

The panel's own state is small: its database (`hivora.db`), its master key (`secret.key`,
which encrypts the secrets of your apps) and its launch options (`install.env`).

- It is saved automatically **before every update** and **before every database
  migration**, in `/opt/hivora/data/backups/_hivora/` (the 5 most recent archives are kept).
- To save it now:
  ```sh
  sudo docker exec hivora python -m hivora backup-self
  ```
- **Settings → Panel health** shows the date of the last archive.

Keep a copy of these archives elsewhere: without `secret.key`, the secrets of your apps
cannot be read again.

## The apps

Each app has a **Backups** card (on its page): back up now, or on a schedule, with a
retention. Archives are written to `/opt/hivora/data/backups/<app>/`; they can be
restored or downloaded from the same card.

## Everything, to rebuild elsewhere

Copy these two folders (Hivora and the apps stopped, or from a filesystem snapshot):

- `/opt/hivora/data`: the panel, the apps' compose files and their backups
- `/srv/hivora`: the apps' data (volumes)

On the new machine, put them back at the same paths and run the installer.
