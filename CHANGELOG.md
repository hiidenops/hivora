# Journal des modifications

Toutes les modifications notables de Hivora sont notées ici.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le projet suit le [versionnage sémantique](https://semver.org/lang/fr/) (avant 1.0, une version mineure peut casser la compatibilité ; ses notes le disent).

## [Non publié]

### Ajouté

- Licence AGPL-3.0.
- Versionnement et releases officiels : la version du paquet fait foi, vérifiée contre le tag ; image publiée avec ses labels OCI ; notes de version tirées de ce fichier.
- Sauvegarde du panel (base, clé maître, options de lancement) dans `backups/_hivora/` avant chaque migration de la base et par `python -m hivora backup-self` ; les 5 dernières sont gardées.
- `python -m hivora bootstrap` : crée le compte `admin` avec un mot de passe aléatoire affiché une seule fois (à changer à la première connexion), ou remplace `admin` / `admin` s'il n'a jamais été changé ; sans effet sur un compte déjà configuré.
- `python -m hivora reset-admin-password [utilisateur]` : nouveau mot de passe aléatoire, à changer à la connexion suivante, depuis la machine seulement.
- Installeur officiel (`install.sh`, publié avec chaque release) : version exacte de la release, options gardées dans `install.env` et reprises à chaque relance, vérification de la distribution (Debian 12+, Ubuntu 22.04+, Raspberry Pi OS 64 bits), de Docker (24+, ni rootless ni Podman) et du port, sauvegarde du panel avant une mise à jour, compte `admin` créé avant le démarrage avec un mot de passe aléatoire, accès `lan` ou `public` (confirmation explicite), `--dry-run`.

- Mode d'accès public : la double authentification (TOTP) est obligatoire pour tous les comptes ; page « Double authentification obligatoire » après la première connexion, puis le panel dans la même session ; elle ne peut pas y être désactivée.
- `python -m hivora reset-totp [utilisateur]` : retire la double authentification d'un compte (téléphone et codes de secours perdus), depuis la machine.
- VPN d'administration (modes d'accès `vpn` et `vpn+lan`, côté serveur) : au démarrage, Hivora met en place une seule fois l'app WireGuard « Admin VPN » dans la zone Administration (réseau partagé), son client `admin` limité à cette zone et `admin.conf` (0600) ; ce client et cette app ne peuvent être ni supprimés ni désactivés (badge « Accès d'administration ») ; `python -m hivora admin-vpn` affiche `admin.conf` en QR code dans le terminal, `python -m hivora rescue-admin` lui donne de nouvelles clés au démarrage suivant. Réglages `HIVORA_ADMIN_VPN_HOST` et `HIVORA_ADMIN_VPN_PORT`.

### Modifié

- Hivora refuse de démarrer sur une base écrite par une version plus récente (retour à une ancienne image), avec un message clair, sans rien modifier.
- La réinitialisation de la double authentification d'un compte par un administrateur coupe aussi ses sessions.
- Une valeur inconnue de `HIVORA_ACCESS` empêche le démarrage.

## [0.1.0]

Première version publique.

### Ajouté

- **Installation et accès** : un seul conteneur (API, WebSocket, interface web), HTTPS par défaut avec certificat auto-signé, script d'installation, interface en français et en anglais, mode simple et mode avancé.
- **Comptes et sécurité** : rôles administrateur, opérateur et lecture seule, double authentification (TOTP), limitation des tentatives de connexion, journal d'audit, secrets chiffrés et jamais écrits dans les fichiers compose.
- **Catalogue** : 39 modèles, des jeux (Minecraft avec modpacks Modrinth et CurseForge, Valheim, Palworld, Rust, Enshrouded, Satisfactory, Factorio, Terraria…) aux applications (Nextcloud, Jellyfin, Immich, Vaultwarden, Home Assistant, Gitea, n8n, AdGuard Home, Uptime Kuma…), aux outils et aux bases de données ; images figées par digest, choix de l'image selon l'architecture.
- **Applications** : déploiement depuis un formulaire avec aperçu du compose généré, démarrage, arrêt, suppression, mises à jour en un clic et retour à une révision précédente, réglages avancés et compose écrit à la main, image Docker libre, projets Python, logs en direct, console, consommation CPU, mémoire et réseau.
- **Jeux** : joueurs, listes (liste blanche, opérateurs, bannis), mondes (importer, activer, télécharger), changement de version.
- **Sites web** : serveurs nginx et Apache hébergeant plusieurs sites, contenu remplacé par une archive ZIP.
- **Bases de données** : MariaDB, PostgreSQL et Redis ; phpMyAdmin et pgAdmin liés à leur base ; ouverture d'une base au réseau local ou à Internet ; carte « Connexion » sur la fiche d'une base.
- **Zones** : regroupement des applications, réseau commun « reliées entre elles », ordre de démarrage, actions sur toute une zone.
- **Topologie** : schéma des zones, des applications et de leurs ports, alertes d'exposition, éléments déclarés à la main, export PNG et JSON.
- **VPN** : serveur WireGuard géré (clients, QR code, droits par client, zones accessibles, expiration).
- **Pare-feu de l'hôte** (agent optionnel) : ports ouverts, règles UFW, fail2ban, connexions en cours, blocage d'adresses IP, routes statiques.
- **Sauvegardes** : à la demande ou planifiées, rétention, restauration, téléchargement.
- **Tâches planifiées** et adoption de conteneurs existants.
