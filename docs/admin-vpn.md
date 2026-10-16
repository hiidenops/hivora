# VPN d'administration

Dans les modes d'accès `vpn+lan` et `vpn`, le panel est joignable par un VPN WireGuard
qu'Hivora met en place lui-même. Il suffit d'ouvrir un port UDP sur votre box.

## Fonctionnement

- Le conteneur du panel rejoint le réseau Docker de la zone **Administration**
  (`hivora-zone-administration`, `10.254.254.0/24`) à une adresse fixe : **`10.254.254.254`**.
- Au démarrage, le serveur déploie dans cette zone une application **Admin VPN** (WireGuard),
  avec un client `admin` qui n'atteint que cette zone (ni Internet ni votre réseau local ne
  passent par lui). Adresses du VPN : `10.254.253.0/24`.
- La configuration du client est écrite dans `/opt/hivora/data/admin.conf` (lisible par root
  seulement).
- Dans ces modes, l'application Admin VPN et son client `admin` ne peuvent être ni supprimés
  ni désactivés depuis le panel.

## Connecter un appareil

1. Installez l'application WireGuard (téléphone ou ordinateur).
2. Redirigez le port UDP du VPN (51820 par défaut) de votre box vers cette machine.
3. Importez `admin.conf`, ou scannez son QR code :
   ```sh
   sudo docker exec hivora python -m hivora admin-vpn
   ```
   (en mode `vpn+lan`, le QR code est aussi dans le panel : Applications → Admin VPN).
4. Activez le tunnel et ouvrez **https://10.254.254.254:8443**.

## Changer l'adresse ou le port

L'adresse à laquelle se connectent vos appareils et le port UDP viennent de l'installation :

```sh
sudo sh install.sh --vpn-host maison.example.org   # ou --vpn-port 51830, ou --reconfigure
```

Le VPN est mis à jour au prochain démarrage du panel (il redémarre quelques secondes). Les
appareils gardent leurs clés : corrigez *Endpoint* dans leur application WireGuard, ou
importez la nouvelle configuration. Tant que l'installation les fixe, ces deux réglages ne
peuvent pas être changés dans le panel.

## Accès perdu

- **De nouvelles clés** pour le client `admin` (`admin.conf` perdu ou divulgué) :
  ```sh
  sudo sh install.sh --rescue-admin
  ```
  L'ancienne configuration cesse de fonctionner ; le nouveau QR code s'affiche.
- **Plus de VPN du tout** : depuis la machine elle-même, passez en mode réseau local :
  ```sh
  sudo sh install.sh --access lan
  ```
