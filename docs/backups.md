# Sauvegardes

## Le panel

L'état propre au panel est petit : sa base (`hivora.db`), sa clé maître (`secret.key`, qui
chiffre les secrets de vos applications) et ses options de lancement (`install.env`).

- Il est sauvegardé automatiquement **avant chaque mise à jour** et **avant chaque migration
  de la base**, dans `/opt/hivora/data/backups/_hivora/` (les 5 archives les plus récentes
  sont gardées).
- Pour le sauvegarder maintenant :
  ```sh
  sudo docker exec hivora python -m hivora backup-self
  ```
- **Paramètres → Santé du panel** affiche la date de la dernière archive.

Gardez une copie de ces archives ailleurs : sans `secret.key`, les secrets de vos
applications ne peuvent plus être lus.

## Les applications

Chaque application a une carte **Sauvegardes** (sur sa page) : sauvegarder maintenant, ou
selon un horaire, avec une rétention. Les archives sont écrites dans
`/opt/hivora/data/backups/<application>/` ; elles se restaurent ou se téléchargent depuis la
même carte.

## Tout, pour reconstruire ailleurs

Copiez ces deux dossiers (Hivora et les applications arrêtés, ou depuis un instantané du
système de fichiers) :

- `/opt/hivora/data` : le panel, les fichiers compose des applications et leurs sauvegardes
- `/srv/hivora` : les données des applications (volumes)

Sur la nouvelle machine, remettez-les aux mêmes chemins et lancez l'installeur.
