# Désinstallation

Retirer le panel ne retire pas vos applications : ce sont de simples projets Docker Compose,
qui continuent de tourner sans lui.

## Retirer seulement le panel

```sh
sudo docker rm -f hivora
```

Vos données restent dans `/opt/hivora/data` et `/srv/hivora` ; relancer l'installeur ramène
le panel tel qu'il était.

## Tout retirer

1. **Les applications** : supprimez-les d'abord depuis le panel (page de chaque application
   → Supprimer, avec ses données si vous le souhaitez). Cela comprend l'application **Admin
   VPN** : passez d'abord en mode réseau local (`sudo sh install.sh --access lan`), puis
   supprimez-la.
2. **Le panel** :
   ```sh
   sudo docker rm -f hivora
   ```
3. **Les réseaux** créés par Hivora pour ses zones :
   ```sh
   sudo docker network ls --filter label=io.hivora.zone-network=1 -q | xargs -r sudo docker network rm
   ```
4. **Les données** (irréversible : les données des applications et leurs sauvegardes aussi) :
   ```sh
   sudo rm -rf /opt/hivora /srv/hivora
   ```
5. Éventuellement, l'image : `sudo docker image rm ghcr.io/hiidenops/hivora:<version>`.

Docker lui-même reste installé.
