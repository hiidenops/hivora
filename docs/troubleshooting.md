# Dépannage

## Premier coup d'œil

- **Paramètres → Santé du panel** : base, espace disque, Docker, tâches, sauvegarde du
  panel, exposition, certificat et VPN d'administration, chacun avec son état.
- Les journaux du panel :
  ```sh
  sudo docker logs hivora
  ```
- Toute exécution de l'installeur peut être prévisualisée avec `--dry-run`.

## Mot de passe perdu

Depuis la machine, un nouveau mot de passe aléatoire pour un compte (à changer à la
connexion suivante ; ses sessions sont fermées) :

```sh
sudo docker exec hivora python -m hivora reset-admin-password          # admin
sudo docker exec hivora python -m hivora reset-admin-password alice    # un autre compte
```

Un autre administrateur peut aussi le réinitialiser depuis **Utilisateurs**.

## Appareil de double authentification et codes de secours perdus

Retirer la double authentification d'un compte (ses sessions sont fermées ; en mode Internet,
elle doit être réactivée à la connexion suivante) :

```sh
sudo docker exec hivora python -m hivora reset-totp          # admin
sudo docker exec hivora python -m hivora reset-totp alice
```

## Plus d'accès par le VPN d'administration

Voir [VPN d'administration → Accès perdu](admin-vpn.md#accès-perdu) : de nouvelles clés avec
`--rescue-admin`, ou le mode réseau local avec `--access lan`.

## L'installeur refuse de continuer

| Message | Que faire |
|---|---|
| le port … est déjà utilisé | en choisir un autre avec `--port N` (ou `--vpn-port N` pour le VPN) |
| cette machine n'a qu'une adresse publique | c'est un VPS : utilisez `--access vpn` (ou `--bind IP`) |
| … chevauche 10.254.253.0/24 ou 10.254.254.0/24 | votre réseau utilise les adresses du VPN d'administration : utilisez `--access lan` |
| le réseau Docker hivora-zone-administration existe avec une autre plage d'adresses | suivez le message : déplacez les applications de la zone Administration, supprimez le réseau, relancez |
| Docker Engine 24 ou plus récent est nécessaire | mettez Docker à jour |

## Un bandeau dit que le panel est publié sur toutes les adresses

Le panel écoute sur toutes les adresses (Internet) alors que son mode d'accès n'est pas
`public` : la double authentification n'est donc pas imposée. Relancez l'installeur avec
`--access lan` (ou `--access public` pour l'accepter, avec la double authentification pour
tous).
