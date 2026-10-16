# Mises à jour

## Savoir qu'une nouvelle version existe

**Paramètres → Mises à jour** affiche la version installée, le canal (Stable ou
Pré-versions), la dernière version publiée avec ses notes, et la commande de mise à jour.
Une pastille bleue sur **Paramètres** signale qu'une version plus récente existe. La
vérification lit les GitHub Releases du projet au plus toutes les 12 heures et n'envoie rien
d'autre qu'un en-tête `User-Agent` ; elle se désactive dans la même carte (aucune requête
n'est alors faite).

L'historique de toutes les versions est dans [`CHANGELOG.md`](../CHANGELOG.md) et sur la
page [GitHub Releases](https://github.com/hiidenops/hivora/releases).

## Mettre à jour

Lancez l'installeur de la nouvelle release sur la machine (la carte affiche la commande
exacte) :

```sh
curl -fsSL https://github.com/hiidenops/hivora/releases/download/vX.Y.Z/install.sh | sudo sh
```

Il garde vos options (`install.env`), sauvegarde le panel, remplace le conteneur `hivora` et
démarre la nouvelle version. Vos applications continuent de tourner pendant la mise à jour.

## Revenir en arrière

Chaque mise à jour sauvegarde d'abord le panel dans `/opt/hivora/data/backups/_hivora/` (la
base, la clé maître et `install.env`). Pour revenir à la version précédente :

```sh
sudo docker rm -f hivora
sudo rm -f /opt/hivora/data/hivora.db-wal /opt/hivora/data/hivora.db-shm
sudo tar -xzf /opt/hivora/data/backups/_hivora/panel-<date>-r<revision>.tar.gz -C /opt/hivora/data
sudo sh install.sh --version vX.Y.Z      # la version précédente
```

Supprimer `hivora.db-wal` et `hivora.db-shm` est indispensable : ils appartiennent à la base
remplacée, et SQLite les appliquerait à la base restaurée (base endommagée).

Une base plus récente n'est jamais ouverte par un Hivora plus ancien : c'est la restauration
de l'archive faite avant la mise à jour qui rend le retour arrière possible. Si une mise à
jour échoue, l'installeur affiche ces commandes avec les bons noms de fichiers.
