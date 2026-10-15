# Journal des modifications

Toutes les modifications notables de Hivora sont notées ici.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le projet suit le [versionnage sémantique](https://semver.org/lang/fr/) (avant 1.0, une version mineure peut casser la compatibilité ; ses notes le disent).

## [Non publié]

### Ajouté

- Licence AGPL-3.0.
- Versionnement et releases officiels : la version du paquet fait foi, vérifiée contre le tag ; image publiée avec ses labels OCI ; notes de version tirées de ce fichier.
- Sauvegarde du panel (base, clé maître, options de lancement) dans `backups/_hivora/` avant chaque migration de la base et par `python -m hivora backup-self` ; les 5 dernières sont gardées.

### Modifié

- Hivora refuse de démarrer sur une base écrite par une version plus récente (retour à une ancienne image), avec un message clair, sans rien modifier.

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
