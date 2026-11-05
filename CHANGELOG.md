# Journal des modifications

Toutes les modifications notables de Hivora sont notées ici.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le projet suit le [versionnage sémantique](https://semver.org/lang/fr/) (avant 1.0, une version mineure peut casser la compatibilité ; ses notes le disent).

## [Non publié]

## [0.5.0] - 2026-11-05

Après la mise à jour, ouvrez **Adressage** (menu Réseau), passez en mode avancé et cliquez une fois sur **Appliquer le plan** : chaque app est redéployée sur ses adresses fixes.

### Ajouté

- **Adressage statique** : chaque zone a maintenant un sous-réseau fixe (un /24 de la plage d'Hivora, ou celui qui suit le réseau du VPN qui la rejoint), le réseau propre de chaque app un /28 fixe et chaque conteneur une IP fixe, gardés d'une mise à jour à l'autre. Hivora ne prend jamais une adresse du réseau local, des routes de la machine, des autres réseaux Docker ni des tunnels VPN. Une zone sans réseau commun donne un /28 à chacune de ses apps.
- **Carte DNS du VPN** : le bouton « DNS » ouvre une carte de la zone (ou des zones) du VPN : les noms à gauche, les apps à droite avec leurs ports web et les sites qu'elles hébergent. Ajoutez un nom, puis tirez un lien vers l'app, un port ou un site (ou choisissez la cible dans la carte du nom).
- **Un nom suffit, sans le port** : un nom relié à un port autre que 80 (Actual sur 5006, le deuxième site d'un nginx…) s'ouvre en `http://actual.lan`, sans `:5006`. Hivora installe et retire seul un petit proxy web derrière le VPN (jamais publié sur la machine, en HTTP).
- **Supprimer une zone et tout son contenu** : sur la page Zones, le bouton rouge d'une zone liste ses apps (conteneurs, fichiers, données), puis supprime chaque app et la zone avec son réseau, en une seule tâche. Les données sont gardées sauf si vous cochez la case ; il faut taper le nom de la zone pour confirmer. Refusé si une app d'une autre zone dépend d'une app de celle-ci ; un VPN d'une autre zone cesse simplement de la desservir.
- **Page Adressage** (menu Réseau) : la plage d'Hivora, les réseaux exclus, chaque zone avec son sous-réseau et l'IP prévue de chaque conteneur à côté de celle que Docker a donnée (écart signalé). En mode avancé : changer le sous-réseau d'une zone, l'IP d'un service ou la plage, avec un aperçu (apps redéployées, commandes Docker ou diff du compose) avant d'appliquer. « Appliquer le plan » met les apps installées avant cette version sur leurs adresses fixes : à faire une fois après la mise à jour.

### Corrigé

- **nginx et Apache** : depuis la 0.4.1, sur un panel qui en avait déjà installé un, modifier leurs réglages, les mettre à jour ou en déployer un nouveau échouait (« template changed without a version bump »). Modèles 1.1.1 ; un test empêche désormais qu'un modèle change sans changer de version.

## [0.4.1] - 2026-11-04

### Ajouté

- **DNS du VPN depuis le tableau de bord et la carte VPN** : bouton « DNS » sur l'en-tête de chaque zone derrière un VPN et sur la carte VPN de l'app WireGuard (plus seulement dans la topologie).
- **Supprimer un serveur web depuis son site principal** : le menu ⋯ du site principal d'un nginx ou d'un Apache propose « Supprimer le serveur et ses sites » (la suppression de l'app, ce qui part listé, données gardées par défaut).

- **Recherche rapide (Ctrl+K)** : Ctrl+K (⌘K sur Mac), « / » ou la loupe à côté du logo ouvrent « Aller à… » : tapez quelques lettres du nom d'une app ou d'une page (accents et majuscules ignorés), Entrée pour y aller.
- **Fil d'Ariane sur la page d'une app** : Tableau de bord › zone › app. Dans Activité, une tâche sélectionnée propose « Ouvrir l'app ».

### Modifié

- **Menu regroupé** : Tableau de bord, puis trois groupes repliables, chacun de sa couleur (Applications : catalogue, image Docker, projet Python, sites ; Réseau : zones, topologie, pare-feu ; Administration : activité, utilisateurs, paramètres, système). Un groupe replié le reste dans ce navigateur (son titre montre alors le nombre de pages, et un point quand la page ouverte en fait partie) ; il se déplie tout seul quand on arrive sur l'une de ses pages. Sur téléphone, le menu s'ouvre par un bouton au lieu de défiler en haut de l'écran.
- **Catalogue** : les apps gérées par Hivora (badge « Adapté à Hivora », désormais aussi nginx et Apache) sont affichées à part, en premier ; les autres suivent.

### Corrigé

- **DNS du VPN** : un nom vers une adresse IP placé sous le nom d'une app (`web.maison.lan` sous `maison.lan`) ne répondait pas. Ouvrir la carte du VPN réécrit sa configuration DNS.

## [0.4.0] - 2026-11-04

### Ajouté

- **Domaines publics en HTTPS** : un proxy HTTPS (Caddy, nouveau modèle « Proxy HTTPS ») publie vos apps web sous votre nom de domaine, avec un certificat Let's Encrypt obtenu et renouvelé tout seul. Dans la topologie, cliquez sur une zone : sa fiche liste les noms de ses apps et permet d'en lier un nouveau en une ligne (nom + app). Zone derrière un VPN : un nom local (`minecraft.local`) ; sinon : un domaine public, le proxy s'installe depuis la même fiche s'il manque. La page du proxy montre chaque domaine, son certificat (validité, émetteur), où pointe son DNS et pourquoi Let's Encrypt l'a refusé. Il faut faire pointer le domaine vers l'IP publique de la machine et rediriger les ports 80 et 443 de la box.
- **DNS local du VPN** : chaque VPN WireGuard a maintenant son propre DNS. Dans la topologie, cliquez sur le VPN puis « DNS » pour donner un nom (ex. `minecraft.local`) à une app de ses zones ou à une adresse IP ; les clients du VPN y accèdent par ce nom. Une app suit son conteneur, même si son IP change. Les autres noms passent par le DNS réglé dans « DNS pour Internet » (vide : celui de la machine), le web marche donc toujours. Modèle WireGuard 2.4.0 : sur un VPN déjà installé, l'appliquer avec « Voir et mettre à jour », puis retélécharger la configuration des clients (leur DNS devient l'adresse du VPN). Les iPhone et Mac réservent `.local` au réseau local : préférez `.lan` ou `.home.arpa` s'ils ne le résolvent pas.

### Corrigé

- **Projet Python, code non monté** : un projet packagé (`pyproject.toml`, code copié par le Dockerfile) dont le compose ne monte que des dossiers de données se déploie maintenant : le code est placé dans `/app`. Avant, le déploiement échouait avec une erreur 500. Si les dépendances ne sont dans aucun dossier monté, le formulaire le dit (erreur 422) au lieu d'échouer.
- **Projet Python, dossier personnel** : quand le Dockerfile crée un utilisateur (`USER`, `useradd --home-dir`) ou fixe `ENV HOME`, l'analyse propose la variable `HOME` vers ce dossier. Hivora lance le code en root : sans elle, le programme écrivait dans `/root` au lieu des volumes du compose (par ex. `/home/app/.state`), et ces données disparaissaient à chaque mise à jour. Un projet déjà déployé n'est pas modifié : pour en profiter, déployez-le à nouveau depuis son .zip.
- **Minecraft, port de jeu** : le serveur écoute maintenant sur le port choisi dans « Port de jeu », pas seulement la machine. C'est le même numéro partout : sur la machine, sur le réseau local, à travers le VPN et dans l'adresse affichée (avant, à travers le VPN, il fallait toujours 25565). Si le port avait été réservé au réseau local ou fermé dans les réglages avancés, il le reste quand on le change. Modèle 1.14.0 : sur un serveur déjà installé, l'appliquer avec « Voir et mettre à jour » sur la page de l'app.

## [0.3.8] - 2026-11-03

### Ajouté

- **TeamSpeak 3** : nouveau modèle (image officielle, x86 uniquement) avec son propre panneau sur la page de l'app. Hivora parle au serveur par sa ServerQuery, sans jamais publier son port. On y voit les connectés (pseudo, adresse, pays), qu'on peut expulser ou bannir, la liste des bans, l'historique des connexions, et on y règle le nom, le message de bienvenue, le nombre de places et le mot de passe du serveur. « Message à tous » écrit à tout le serveur. « Générer une nouvelle clé » crée une clé admin (droits Server Admin), affichée une seule fois, et supprime les anciennes pas encore utilisées. Mot de passe et clé admin : admin et code TOTP récent.
- **TeamSpeak 3, protection fail2ban** : avec l'agent hôte, une jail par serveur bloque sur la machine (chaîne `DOCKER-USER`) les adresses qui ratent trop de connexions ServerQuery, d'après le journal du serveur ; échecs, durée et blocage réglables, adresses bloquées listées et débloquables.
- **Tableau de bord** : la tuile d'un serveur de jeu qui tourne affiche le nombre de connectés.

### Corrigé

- **Audit** : les demandes de mise à jour des paquets et de redémarrage de l'hôte sont maintenant notées dans le journal d'audit.

## [0.3.7] - 2026-11-03

### Ajouté

- **Nouveautés** : après plusieurs mises à jour d'un coup, la fenêtre des nouveautés montre les notes de toutes les versions depuis la dernière vue dans ce navigateur, la plus récente d'abord.
- **Activité** : les tâches et le journal d'audit affichent 10 lignes par défaut, puis 20, 50 ou tout (500 tâches, 1 000 entrées du journal au plus) selon le choix « Afficher ».
- **Topologie** : dans le panneau d'une app, chaque port a un bouton qui copie l'adresse complète `IP:port` (l'IP du conteneur et le port du conteneur).

## [0.3.6] - 2026-11-03

### Ajouté

- **Nouveautés** : à la première visite après une mise à jour (et à la toute première), une fenêtre montre les nouveautés de la version installée. Une fois fermée, elle ne revient plus jusqu'à la version suivante (retenu par navigateur).
- **Système de l'hôte** : une carte de la page Système, par l'agent hôte, pour les paquets de la machine. Elle vérifie toutes les 6 h (ou sur « Vérifier ») les paquets à mettre à jour, dont ceux de sécurité, et si un redémarrage est nécessaire. « Mettre à jour les paquets » lance `apt-get upgrade` (jamais `full-upgrade`) ; la mise à jour continue même si elle redémarre Docker. « Redémarrer » liste les apps, les arrête proprement dans l'ordre des zones, redémarre la machine, puis Hivora les relance dans l'ordre à son retour. Admin et code TOTP récent, Debian et Ubuntu.
- **Topologie** : le panneau d'une app propose « Ouvrir dans le tableau de bord », « Ouvrir sur le web » (quand elle a une adresse web) et la copie de son adresse IP.
- **Panneaux latéraux** (compose, détails avancés, sauvegardes, logs…) : leur bord gauche se tire pour les élargir ou les réduire ; la largeur est retenue pour chaque panneau, un double clic revient à la largeur par défaut.

### Modifié

- **Notes de version** (page Système) : elles s'ouvrent dans une fenêtre, mises en forme (titres, listes, gras, code), au lieu d'un texte brut déroulant.
- **Boutons** : les derniers boutons qui lançaient une action sans indicateur (tâches planifiées, clients VPN, sauvegardes, utilisateurs, sessions, déconnexion) attendent la fin de l'action ; un second clic ne fait rien.

### Corrigé

- **Zones** : en créant une zone avec un nouveau VPN, le formulaire de déploiement du VPN propose cette zone, et non plus Administration.

## [0.3.5] - 2026-11-02

### Ajouté

- **Mise à jour depuis le panel** : un bouton « Mettre à jour » dans la carte Mises à jour de la page Système (admin, code TOTP si la double authentification est active). Il télécharge l'image de la release, vérifie que son digest est celui publié, puis un petit conteneur `hivora-updater` arrête le panel, le sauvegarde, prépare la base et recrée `hivora` avec exactement les mêmes options. Si la nouvelle version ne démarre pas, il revient tout seul à l'ancienne et à la base d'avant. La page se recharge d'elle-même sur la nouvelle version. Le bouton ne fait que monter de version ; l'installeur reste le moyen de revenir en arrière ou de changer d'options.
- **Installeur** : `--no-self-update` retire ce bouton (`HIVORA_SELF_UPDATE` dans `install.env`) ; `--self-update` le remet.

### Notes

- Le bouton sert à partir de la version suivante : passer à la 0.3.5 se fait encore avec la commande de l'installeur.

## [0.3.4] - 2026-11-02

### Ajouté

- **Zones** : à la création d'une zone, on choisit son VPN : aucun, un VPN existant (il dessert la zone aussitôt), ou un nouveau serveur WireGuard. Dans ce dernier cas, le formulaire de déploiement s'ouvre, prérempli (« VPN <zone> »), et le VPN déployé dessert la zone. Une zone desservie par un VPN relie toujours ses apps entre elles.

## [0.3.3] - 2026-11-02

### Ajouté

- **Icône** : la tête du chat, mascotte de Hivora (celui de l'étagère, en bas de la navigation), sur fond miel, dans l'onglet du navigateur et les favoris.
- **Tableau de bord** : un bouton « Ouvrir » sur chaque app qui a une adresse web, vers l'adresse adaptée (réseau local, Internet ou VPN).

- **Chargement des boutons** : un bouton dont l'action tourne affiche un indicateur et attend ; un second clic ne fait rien. Démarrer, arrêter et redémarrer restent en attente jusqu'à la fin de la tâche, et le panel ne crée pas une seconde tâche identique pour une app tant que la première n'est pas finie (double clic, deux onglets).

### Modifié

- **Boutons** : un style plus sobre dans les deux thèmes (couleur pleine, bord net, plus de dégradé brillant ni de halo ; ils s'enfoncent au clic au lieu de se soulever), et un anneau de focus visible au clavier.
- **Page Système** : les cartes Système, Santé du panel et Mises à jour quittent Paramètres pour une page à elles, ouverte par le bouton « Système » en bas de la barre de navigation. La pastille (santé à vérifier, nouvelle version) est sur ce bouton.
- **VPN** : la fiche d'un serveur VPN n'affiche plus « Pour jouer depuis Internet, pensez à ouvrir le port… ».
- **Topologie** : la carte d'une app d'une zone VPN montre, comme celle du panel, son adresse par le VPN (« VPN 10.8.1.7 ») et les ports joignables par lui.
- **Mises à jour** : chaque clic dans la barre de navigation redemande au panel s'il existe une nouvelle version ; le panel interroge GitHub au plus toutes les 20 minutes (au lieu de 12 heures).

## [0.3.2] - 2026-11-01

### Ajouté

- **Image libre** : la page liste les images déjà déployées (la plus récente d'abord, avec les apps qui les utilisent encore) ; « Reprendre » relit l'image dans son registre et pré-remplit le formulaire.

### Corrigé

- **Adresse affichée** : le panel montrait le port du formulaire (par exemple 8081 pour Stirling PDF) même quand le compose en publiait un autre ; il suit maintenant le port réellement publié, comme la topologie.
- **App derrière un VPN** : son adresse par le VPN donne le port sur lequel elle écoute (8080 pour Stirling PDF), au format complet (`http://10.8.1.7:8080`), et non plus le port qu'elle aurait publié.
- **Fin du déploiement** : les adresses affichées sont celles de l'app installée (réseau local, Internet, VPN), plus celles calculées avant le déploiement.

## [0.3.1] - 2026-11-01

### Modifié

- **Accès d'une app** : au déploiement, trois choix clairs, « Publié sur Internet », « Réseau local » (seulement l'IP locale de la machine) ou « Par un VPN ». La liste des zones suit le choix.
- **VPN et zones** : un VPN dessert des zones, plus des apps isolées (une app placée seule derrière un VPN ne l'est plus : mettez-la dans une zone desservie ; ses ports fermés à la main restent fermés). Une zone n'est desservie que par un VPN ; elle passe d'elle-même en réseau « reliées entre elles », reçoit son propre réseau à côté de celui du VPN (par exemple `10.8.1.0/24`), et **aucune de ses apps ne publie de port** sur la machine : elles ne sont joignables que par les clients du VPN. Avant d'enregistrer, la carte VPN liste les ports qui vont se fermer. Les interrupteurs des zones de la carte VPN ne sont plus grisés sans explication.
- **Topologie** : une zone desservie par un VPN n'est plus reliée au pare-feu de l'hôte, seulement à son VPN ; tirer un lien d'un VPN vers une app explique qu'il faut passer par une zone.
- **Tableau de bord** : une pastille « VPN » sur le titre des zones desservies.

### À savoir avant de mettre à jour

- En mode d'accès « VPN » ou « VPN + LAN », la zone Administration est desservie par le VPN d'administration : à leur prochain déploiement, les apps qui y sont ne publient plus de port. Une app qui doit rester joignable sur le réseau local (par exemple AdGuard Home pour le DNS) est à déplacer dans une autre zone.

## [0.3.0] - 2026-11-01

### Ajouté

- **Catalogue** : un badge « Adapté à Hivora » signale les modèles retravaillés et testés pour le panel (WireGuard, Minecraft, Vaultwarden, MariaDB, PostgreSQL). Un modèle le reçoit avec `metadata.verified: true`.

### Corrigé

- **VPN** : à la première installation, les clients WireGuard ne se connectaient pas. Démarrée sans configuration, l'image supprimait la route par défaut du conteneur, et les réponses aux clients ne repartaient plus ; Hivora la remet avant de monter le tunnel.

## [0.2.0] - 2026-10-29

### Ajouté

- **Jeux coupés à l'installation** : l'installeur demande s'il faut garder les jeux dans le catalogue (`--no-games` / `--games` sans question), pour une école ou un lieu de travail. Coupés, ils ne sont ni affichés ni installables (l'API refuse avec `games_disabled`) ; les serveurs de jeux déjà installés continuent de tourner. Le choix vit dans `install.env` ; pour le changer, relancer l'installeur.

### Corrigé

- **Topologie** : le panel Hivora lui-même apparaît dans la zone dont il a rejoint le réseau (Administration, dans les modes VPN), avec son port sur le réseau local et son adresse par le VPN.
- **Topologie** : le schéma suit le thème choisi dans Hivora (clair ou sombre), plus celui du système ; en sombre sur un système clair, ses textes étaient noirs.

### Modifié

- **Script d'installation** : dans un terminal, les questions s'affichent dans des fenêtres (whiptail, présent d'office sur les distributions supportées) avec le logo Hivora, et une fenêtre suit les étapes de l'installation (faites, en cours, à venir) ; en cas d'échec, l'installeur revient au terminal avec la sortie de l'étape et l'erreur. Sans whiptail, avec `--yes` ou `HIVORA_UI=text` : écrans en texte, avec des titres, des couleurs (seulement dans un terminal ; `NO_COLOR` les coupe), des colonnes alignées même avec des accents et des étapes numérotées. L'écran de fin, en texte dans tous les cas, fait ressortir l'URL et le mot de passe. Nouvelle commande d'installation et de mise à jour : `sudo sh -c "$(curl -fsSL …/install.sh)"` (avec `curl … | sudo sh`, l'installeur marche toujours, en questions texte).

## [0.1.0] - 2026-10-17

Première version publique.

### Ajouté

- **Installation et accès** : un seul conteneur (API, WebSocket, interface web), HTTPS par défaut avec certificat auto-signé, script d'installation, interface en français et en anglais, mode simple et mode avancé.
- **Comptes et sécurité** : rôles administrateur, opérateur et lecture seule, double authentification (TOTP), limitation des tentatives de connexion, journal d'audit, secrets chiffrés et jamais écrits dans les fichiers compose.
- **Catalogue** : 41 modèles, des jeux (Minecraft avec modpacks Modrinth et CurseForge, Valheim, Palworld, Rust, Enshrouded, Satisfactory, Factorio, Terraria…) aux applications (Nextcloud, Jellyfin, Immich, Vaultwarden, Home Assistant, Gitea, n8n, AdGuard Home, Uptime Kuma…), aux outils et aux bases de données ; images figées par digest, choix de l'image selon l'architecture.
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
- Licence AGPL-3.0.
- Versionnement et releases officiels : la version du paquet fait foi, vérifiée contre le tag ; image publiée avec ses labels OCI ; notes de version tirées de ce fichier.
- Sauvegarde du panel (base, clé maître, options de lancement) dans `backups/_hivora/` avant chaque migration de la base et par `python -m hivora backup-self` ; les 5 dernières sont gardées.
- `python -m hivora bootstrap` : crée le compte `admin` avec un mot de passe aléatoire affiché une seule fois (à changer à la première connexion), ou remplace `admin` / `admin` s'il n'a jamais été changé ; sans effet sur un compte déjà configuré.
- `python -m hivora reset-admin-password [utilisateur]` : nouveau mot de passe aléatoire, à changer à la connexion suivante, depuis la machine seulement.
- Installeur officiel (`install.sh`, publié avec chaque release) : version exacte de la release, options gardées dans `install.env` et reprises à chaque relance, vérification de la distribution (Debian 12+, Ubuntu 22.04+, Raspberry Pi OS 64 bits), de Docker (24+, ni rootless ni Podman) et du port, sauvegarde du panel avant une mise à jour, compte `admin` créé avant le démarrage avec un mot de passe aléatoire, accès `lan` ou `public` (confirmation explicite), `--dry-run`.
- Mode d'accès public : la double authentification (TOTP) est obligatoire pour tous les comptes ; page « Double authentification obligatoire » après la première connexion, puis le panel dans la même session ; elle ne peut pas y être désactivée.
- `python -m hivora reset-totp [utilisateur]` : retire la double authentification d'un compte (téléphone et codes de secours perdus), depuis la machine.
- VPN d'administration (modes d'accès `vpn` et `vpn+lan`, côté serveur) : au démarrage, Hivora met en place une seule fois l'app WireGuard « Admin VPN » dans la zone Administration (réseau partagé), son client `admin` limité à cette zone et `admin.conf` (0600) ; ce client et cette app ne peuvent être ni supprimés ni désactivés (badge « Accès d'administration ») ; `python -m hivora admin-vpn` affiche `admin.conf` en QR code dans le terminal, `python -m hivora rescue-admin` lui donne de nouvelles clés au démarrage suivant. Réglages `HIVORA_ADMIN_VPN_HOST` et `HIVORA_ADMIN_VPN_PORT`.
- Installeur : modes d'accès `vpn+lan` (défaut d'une nouvelle installation) et `vpn` (aucun port du panel publié) ; le panel rejoint le réseau de la zone Administration à l'adresse fixe `10.254.254.254` (`https://10.254.254.254:8443` par le VPN) ; vérification du port UDP, des plages d'adresses et du réseau existant ; QR code du client VPN affiché à la fin de l'installation ; options `--vpn-host`, `--vpn-port` et `--rescue-admin` (nouvelles clés du client VPN d'administration).
- Changer l'adresse (`--vpn-host`, `--reconfigure`) ou le port (`--vpn-port`) du VPN d'administration d'une installation existante : l'app « Admin VPN » et `admin.conf` suivent au démarrage, sans changer les clés ; l'installeur avertit (ancienne → nouvelle adresse, coupure de quelques secondes) et, en mode VPN seul, affiche le nouveau QR code ; le panel refuse de modifier ces deux réglages quand l'installation les fixe.
- README en français (présentation, installation rapide, modes d'accès, captures d'écran), documentation détaillée en français dans `docs/` (installation, VPN d'administration, mises à jour et retour arrière, sauvegardes, dépannage, désinstallation, développement, publication des versions) et politique de sécurité (`SECURITY.md`, signalement par les GitHub Security Advisories).
- Mises à jour (Paramètres, administrateurs) : version installée et ses notes, dernière version publiée sur GitHub selon le canal (Stable ou Pré-versions) avec ses notes en texte, commande de mise à jour à copier et lien vers la release ; vérification activée par défaut, désactivable, au plus toutes les 12 h, sans autre donnée envoyée que l'en-tête User-Agent ; pastille bleue sur « Paramètres » quand une version plus récente existe.
- Santé du panel (Paramètres, administrateurs) : version, base de données (vérification complète à la demande), espace disque, Docker, tâches, sauvegarde du panel, exposition, certificat HTTPS et VPN d'administration, avec le mode d'accès actuel ; pastille sur « Paramètres » quand un point est à vérifier ; bandeau quand le panel est publié sur toutes les adresses hors mode Internet (erreur) ou en mode Internet (rappel).
- Lien « Code source (AGPL-3.0) » vers la version en cours, sur la page de connexion et dans Paramètres ; réglable par `HIVORA_SOURCE_URL` pour une version modifiée.
- Le panel signale une nouvelle version du serveur et propose de recharger la page.
- Installeur en français ou en anglais (choix au premier écran, `--lang`) ; menu du mode d'accès avec une courte description de chaque mode ; adresse publique du VPN détectée, à confirmer ou à corriger (IP ou nom de domaine) ; récapitulatif avant l'installation ; `--reconfigure` pour changer de mode sur une installation existante.

### Modifié

- Hivora refuse de démarrer sur une base écrite par une version plus récente (retour à une ancienne image), avec un message clair, sans rien modifier.
- La réinitialisation de la double authentification d'un compte par un administrateur coupe aussi ses sessions.
- Une valeur inconnue de `HIVORA_ACCESS` empêche le démarrage.
- `deploy/compose.yaml` : mode d'accès `lan` explicite et port publié sur l'adresse donnée par `HIVORA_BIND` (obligatoire) au lieu de toutes les adresses.
- Retour arrière après une mise à jour : la procédure (documentation et message de l'installeur) supprime d'abord `hivora.db-wal` et `hivora.db-shm`, qui appartiennent à la base remplacée ; sans cela, la base restaurée était endommagée.
- Une nouvelle installation est en mode `vpn+lan` par défaut (avant : `lan`) ; une installation existante garde son mode.
- Installeur : un port UDP déjà occupé n'est plus accepté que s'il est publié par le VPN d'administration lui-même (avant : dès que ce VPN existait, même pour un nouveau port).
- Installeur : sur une machine qui n'a qu'une adresse IP publique (VPS), les modes `lan` et `vpn+lan` sont refusés sauf avec `--bind` (le panel y aurait été publié sur Internet sans double authentification obligatoire) ; le mode par défaut y est `vpn`. En `vpn+lan`, l'installation n'attend plus le VPN et n'affiche plus son QR code. La fin de l'installation commence par l'URL et le compte.
