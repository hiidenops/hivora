#!/bin/sh
# Hivora installer: installs Docker if needed, then Hivora; re-running it updates Hivora
# or changes its options (kept in <data>/install.env), apps and data stay.
#
#   sudo sh -c "$(curl -fsSL https://github.com/hiidenops/hivora/releases/latest/download/install.sh)"
#   sudo sh -c "$(curl ...)" install.sh --yes --access lan --port 8443
#
# Options:
#   --yes             no questions (public access still needs --i-understand)
#   --dry-run         show what would be done, change nothing
#   --lang fr|en      language of the installer (asked first; default without questions: en)
#   --version TAG     Hivora version (default: this script's release, else install.env)
#   --image REF       image without tag (default: ghcr.io/hiidenops/hivora)
#   --access MODE     vpn+lan, vpn, lan or public (asked on a new install; default:
#                     vpn+lan on a private network, vpn on a machine with a public IP only)
#   --reconfigure     ask again how the panel is reached (an existing install)
#   --port N          panel port on the machine (8443)
#   --bind IP         address the panel listens on (overrides --access)
#   --vpn-host HOST   address the admin VPN's clients connect to (default: public IP)
#   --vpn-port N      UDP port of the admin VPN (51820)
#   --rescue-admin    new keys for the admin VPN client, then show its QR code
#   --data DIR        panel data (/opt/hivora/data)   --srv DIR   app volumes (/srv/hivora)
#   --i-understand    confirm --access public with --yes
#
# Everything is in functions and `main` runs on the last line: a download cut halfway
# runs nothing. install.env is read line by line, never executed, and every value is
# checked before use. Questions are read from the terminal (one channel, fd 3), never
# with --yes; every message is in msg_en and msg_fr (a test checks they match).
set -eu

SCRIPT_VERSION=""  # the release tag, set by release.yml when publishing
DEFAULT_IMAGE="ghcr.io/hiidenops/hivora"
CONTAINER="hivora"
OS_RELEASE="${HIVORA_OS_RELEASE:-/etc/os-release}"  # tests point it elsewhere
TTY_DEVICE="${HIVORA_TTY:-/dev/tty}"                # tests give a file of answers
HEALTH_TIMEOUT="${HIVORA_HEALTH_TIMEOUT:-120}"      # seconds
VPN_TIMEOUT="${HIVORA_VPN_TIMEOUT:-600}"            # seconds: the WireGuard image download
PUBLIC_IP_URL="https://api.ipify.org"               # the panel asks the same service (D12)
# The admin VPN's fixed addressing: the same values as backend/src/hivora/vpn/admin.py
# (a test compares them). The panel joins the Administration zone's network at PANEL_IP.
ADMIN_NETWORK="hivora-zone-administration"
ADMIN_ZONE_SUBNET="10.254.254.0/24"
ADMIN_ZONE_RANGE="10.254.254.0/25"
PANEL_IP="10.254.254.254"
ADMIN_VPN_SUBNET="10.254.253.0/24"
UI_LANG="en"

# --- messages ----------------------------------------------------------------------------
# One line per message: `key) m 'printf format' ;;` (the parity test reads these lines).
m() { printf '%s' "$1"; }

msg_en() {
  case "$1" in
    needs_value) m '%s needs a value' ;;
    unknown_option) m 'unknown option: %s (see --help)' ;;
    bad_lang) m 'invalid --lang: %s (fr or en)' ;;
    bad_data) m '--data must be an absolute path' ;;
    bad_srv) m '--srv must be an absolute path' ;;
    no_version) m 'no version to install: use --version TAG (this script is not from a release)' ;;
    bad_version) m 'invalid version: %s' ;;
    bad_image) m 'invalid image: %s' ;;
    bad_port) m 'invalid port: %s' ;;
    bad_vpn_host) m 'invalid --vpn-host: %s' ;;
    bad_lan) m 'invalid LAN address: %s' ;;
    bad_ids) m 'invalid PUID/PGID' ;;
    bad_access) m 'invalid --access: %s (vpn+lan, vpn, lan or public)' ;;
    bad_bind) m 'invalid --bind address: %s' ;;
    no_lan_ip) m 'no LAN address found: use --bind IP or --access vpn' ;;
    vps_refused) m 'this machine only has a public address (%s): no local network.\n  "%s" would publish the panel on that address, that is on the Internet,\n  without mandatory two-factor authentication. Choose --access vpn (recommended) or\n  --access public, or set the listening address yourself with --bind IP.' ;;
    linux_only) m 'Hivora runs on Linux only.' ;;
    bad_arch) m 'unsupported CPU architecture: %s (amd64 or arm64 needed)' ;;
    need_root) m 'run as root (e.g. with sudo).' ;;
    os_unsupported) m '%s %s is not officially supported (Debian 12+, Ubuntu 22.04+, Raspberry Pi OS 64-bit).' ;;
    continue_anyway) m 'Continue anyway?' ;;
    cancelled) m 'cancelled.' ;;
    need_terminal) m 'no terminal to answer "%s": re-run with --yes' ;;
    no_answer) m 'no answer (end of input): cancelled.' ;;
    no_docker) m 'Docker is not installed.' ;;
    install_docker) m 'Install it now with the official script (get.docker.com)?' ;;
    docker_required) m 'Docker is required.' ;;
    podman) m 'Podman is not supported: Hivora needs Docker Engine.' ;;
    daemon_down) m 'the Docker daemon does not answer.' ;;
    docker_old) m 'Docker Engine 24 or newer is needed (found %s).' ;;
    rootless) m 'rootless Docker is not supported: Hivora needs the system Docker daemon.' ;;
    port_busy) m 'port %s is already in use on this machine: choose another with --port N' ;;
    udp_busy) m 'UDP port %s is already in use on this machine: choose another with --vpn-port N' ;;
    network_other) m 'the Docker network %s exists with another address range (%s); move the Administration zone apps to another zone (or set it to "Not linked") and remove it (docker network rm %s), or use --access lan' ;;
    overlap) m 'the network of this machine overlaps %s (the admin VPN addresses): use --access lan' ;;
    public_warn) m 'The panel will listen on every address of this machine, Internet included.\n!! Hivora controls Docker (root on this machine); Docker bypasses UFW: the firewall\n   does not protect it. Two-factor authentication will be mandatory for every account.' ;;
    public_needs_understand) m '--access public with --yes needs --i-understand' ;;
    backing_up) m 'Backing up the panel (database, key, options)...' ;;
    backup_failed) m 'the panel backup failed; nothing was changed.' ;;
    backup_done) m 'Backup: %s' ;;
    no_backup) m 'Hivora is not running: no backup now (a pending migration is backed up at startup).' ;;
    downloading) m 'Downloading Hivora %s...' ;;
    cannot_download) m 'cannot download %s' ;;
    preparing) m 'Preparing the panel...' ;;
    prepare_failed) m 'the panel could not be prepared (see above)%s' ;;
    creating_network) m 'Creating the admin network %s...' ;;
    starting) m 'Starting Hivora %s...' ;;
    not_started) m 'Hivora did not start; see: docker logs %s%s' ;;
    waiting_vpn) m 'Setting up the admin VPN (the first time, WireGuard is downloaded)...' ;;
    vpn_late) m 'the admin VPN is not ready yet; later: docker exec %s python -m hivora admin-vpn (and docker logs %s)' ;;
    rescue_not_running) m 'Hivora is not running here: nothing to rescue.' ;;
    rescue_keys) m 'New keys for the admin VPN client (the old admin.conf stops working)...' ;;
    rescue_no_conf) m 'no new admin.conf: see docker logs %s' ;;
    rescue_import) m 'Import it in the WireGuard app, then open https://%s:8443' ;;
    go_back) m '\n  To go back: docker rm -f %s' ;;
    go_back_tar) m '; rm -f %s/hivora.db-wal %s/hivora.db-shm; tar -xzf %s -C %s' ;;
    go_back_version) m '; then re-run this script with --version %s' ;;
    dry_done) m 'Dry run: nothing was changed.' ;;
    unchanged_access) m 'Access: %s (unchanged; to change it: --reconfigure)' ;;
    reconf_tty) m '--reconfigure asks questions: run it in a terminal, without --yes (or use --access)' ;;
    reconf_nothing) m 'nothing installed here yet: run the installer without --reconfigure' ;;
    yes_no) m '[Y/n]' ;;
    no_yes) m '[y/N]' ;;
    mode_lan) m 'Local network only' ;;
    mode_vpnlan) m 'Local network + VPN' ;;
    mode_vpn) m 'Only through the VPN' ;;
    mode_public) m 'Internet (advanced)' ;;
    menu_title) m 'How will you reach the panel?' ;;
    machine_private) m 'This machine: %s (private network)' ;;
    machine_public) m 'This machine: %s (PUBLIC address, no private network found)' ;;
    tag_simplest) m 'simplest' ;;
    tag_recommended) m '[recommended]' ;;
    tag_private) m 'most private' ;;
    tag_not_recommended) m 'not recommended' ;;
    tag_unavailable) m 'unavailable: there is no local network here' ;;
    desc_lan) m '%s from your network. Nothing to set up on your router.' ;;
    desc_vpnlan) m 'Same as 1, plus a WireGuard VPN to reach it from anywhere.\n       You will open a UDP port on your router and scan a QR code (in the panel).' ;;
    desc_vpn) m 'No panel port on the network. Without the VPN client,\n       nobody (you included) can open the panel.' ;;
    desc_public) m 'The panel listens on every address. Two-factor authentication\n       becomes mandatory for every account.' ;;
    vps_explain) m 'Choices 1 and 2 would publish the panel on %s, that is on the Internet,\n  without the Internet mode protections (mandatory two-factor authentication).' ;;
    your_choice) m 'Your choice [%s]: ' ;;
    invalid_choice) m 'Invalid choice: type 1, 2, 3 or 4.' ;;
    unavailable_choice) m 'This choice is not available on this machine.' ;;
    addr_detected) m 'Detected public address for the VPN:' ;;
    addr_current) m 'Current public address for the VPN:' ;;
    addr_help) m 'Your devices will connect to it from outside (UDP port %s).\n  If you have a domain name (e.g. home.example.org), answer "n".' ;;
    addr_correct) m 'Is this correct?' ;;
    addr_not_detected) m 'Public address not detected (no Internet access?).' ;;
    addr_prompt) m 'IP address or domain name for the VPN: ' ;;
    addr_invalid) m '"%s" is neither a valid IP address nor a valid domain name.' ;;
    addr_noresolve) m '%s does not resolve (or not to %s).\n   The VPN will work only once that name is in place. Keep it?' ;;
    vpn_moves) m 'The admin VPN address changes: %s → %s\n   Devices already set up keep their keys: fix "Endpoint" in the WireGuard app,\n   or import the configuration again (QR code: docker exec hivora python -m hivora admin-vpn, or in the panel).' ;;
    vpn_drop) m 'The VPN restarts: it drops for a few seconds, for every device.' ;;
    confirm_vpn) m 'Only through the VPN: you will need the WireGuard app and the QR code shown\n   at the end. Keep this terminal open until the connection works.\n   Fallback on this machine: run the installer again with --access lan.' ;;
    confirm_vpn_switch) m 'Switching to "Only through the VPN": have you opened the panel through the\n   VPN at least once? Otherwise you will not be able to reach it any more.' ;;
    type_word) m 'Type %s to confirm: ' ;;
    leave_vpn) m 'Without the VPN: the "Admin VPN" app stays installed but is no longer\n   protected; remove it from the panel if you do not want it.' ;;
    to_public) m 'Internet mode: every account without two-factor authentication will have\n   to turn it on at its next login.' ;;
    recap_title) m 'Hivora %s will be installed:' ;;
    recap_access) m 'Access' ;;
    recap_panel) m 'Panel' ;;
    recap_through) m '(through the VPN)' ;;
    recap_vpn) m 'VPN' ;;
    recap_vpn_line) m 'UDP port %s, public address %s' ;;
    recap_was) m ' (was: %s)' ;;
    recap_vpn_auto) m 'detected by the panel' ;;
    recap_data) m 'Data' ;;
    recap_volumes) m 'App volumes' ;;
    recap_tz) m 'Timezone' ;;
    recap_update) m 'An existing Hivora will be backed up and replaced (apps keep running).' ;;
    continue) m 'Continue?' ;;
    ready) m 'HIVORA IS READY' ;;
    f_url) m 'URL:' ;;
    f_user) m 'User:' ;;
    f_password) m 'Password:' ;;
    f_unchanged) m 'unchanged (forgotten: docker exec %s python -m hivora reset-admin-password)' ;;
    f_once) m 'Shown once only: write it down, then clear your screen (clear).\nYou will choose your own password at first login.' ;;
    f_cert) m 'The certificate is self-signed: your browser warns once, that is expected.' ;;
    f_lan_later) m 'Remote access later: run the installer again with --reconfigure (adds the VPN).' ;;
    f_vpn_available) m 'Admin VPN: available (optional)' ;;
    f_vpn_updating) m 'Admin VPN: new address, admin.conf is being updated (a few moments)' ;;
    f_vpn_setup) m 'Admin VPN: being set up (optional, a few minutes the first time)' ;;
    f_through) m '  Through the VPN:  https://%s:8443' ;;
    f_file) m '  File:             %s' ;;
    f_qr) m '  QR code:          docker exec %s python -m hivora admin-vpn' ;;
    f_qr_panel) m '  QR code:          docker exec %s python -m hivora admin-vpn   (or in the panel: Admin VPN)' ;;
    f_udp) m '  To use it from outside: open UDP port %s on your router towards this machine.' ;;
    f_steps) m 'VPN access, step by step:' ;;
    f_step1) m '  1. Install the WireGuard app (phone or computer).' ;;
    f_step2) m '  2. Open UDP port %s on your router towards this machine.' ;;
    f_step3) m '  3. Scan this QR code (or import %s).' ;;
    f_step4) m '  4. Turn the tunnel on, then open https://%s:8443' ;;
    f_again) m 'Show it again: docker exec %s python -m hivora admin-vpn' ;;
    f_newkeys) m 'New keys: run the installer again with --rescue-admin' ;;
    f_fallback) m 'Fallback on this machine: run the installer again with --access lan' ;;
    f_public) m 'Panel reachable from the Internet: two-factor authentication will be asked\n   right after your first password change.' ;;
    f_options) m 'Options kept in %s.\nLogs: docker logs %s\nUninstall: docker rm -f %s (apps and %s stay)' ;;
    error) m 'Error:' ;;
    installing_docker) m 'Installing Docker (get.docker.com), a few minutes...' ;;
    wt_yes) m 'Yes' ;;
    wt_no) m 'No' ;;
    wt_ok) m 'OK' ;;
    wt_cancel) m 'Cancel' ;;
    steps_title) m 'Installing' ;;
  esac
}

# shellcheck disable=SC1112  # French typography: ’ is a letter here, not a quote
msg_fr() {
  case "$1" in
    needs_value) m '%s demande une valeur' ;;
    unknown_option) m 'option inconnue : %s (voir --help)' ;;
    bad_lang) m '--lang invalide : %s (fr ou en)' ;;
    bad_data) m '--data doit être un chemin absolu' ;;
    bad_srv) m '--srv doit être un chemin absolu' ;;
    no_version) m 'aucune version à installer : utilisez --version TAG (ce script ne vient pas d’une release)' ;;
    bad_version) m 'version invalide : %s' ;;
    bad_image) m 'image invalide : %s' ;;
    bad_port) m 'port invalide : %s' ;;
    bad_vpn_host) m '--vpn-host invalide : %s' ;;
    bad_lan) m 'adresse LAN invalide : %s' ;;
    bad_ids) m 'PUID/PGID invalides' ;;
    bad_access) m '--access invalide : %s (vpn+lan, vpn, lan ou public)' ;;
    bad_bind) m 'adresse --bind invalide : %s' ;;
    no_lan_ip) m 'aucune adresse LAN trouvée : utilisez --bind IP ou --access vpn' ;;
    vps_refused) m 'cette machine n’a qu’une adresse publique (%s) : pas de réseau local.\n  « %s » publierait le panel sur cette adresse, donc sur Internet, sans\n  double authentification obligatoire. Choisissez --access vpn (recommandé) ou\n  --access public, ou indiquez vous-même l’adresse d’écoute avec --bind IP.' ;;
    linux_only) m 'Hivora fonctionne uniquement sous Linux.' ;;
    bad_arch) m 'architecture non prise en charge : %s (amd64 ou arm64 requis)' ;;
    need_root) m 'lancez-le en root (par exemple avec sudo).' ;;
    os_unsupported) m '%s %s n’est pas officiellement pris en charge (Debian 12+, Ubuntu 22.04+, Raspberry Pi OS 64 bits).' ;;
    continue_anyway) m 'Continuer quand même ?' ;;
    cancelled) m 'annulé.' ;;
    need_terminal) m 'aucun terminal pour répondre à « %s » : relancez avec --yes' ;;
    no_answer) m 'aucune réponse (fin de saisie) : annulé.' ;;
    no_docker) m 'Docker n’est pas installé.' ;;
    install_docker) m 'L’installer maintenant avec le script officiel (get.docker.com) ?' ;;
    docker_required) m 'Docker est nécessaire.' ;;
    podman) m 'Podman n’est pas pris en charge : Hivora a besoin de Docker Engine.' ;;
    daemon_down) m 'le démon Docker ne répond pas.' ;;
    docker_old) m 'Docker Engine 24 ou plus récent est nécessaire (trouvé : %s).' ;;
    rootless) m 'Docker sans root (rootless) n’est pas pris en charge : Hivora a besoin du démon Docker du système.' ;;
    port_busy) m 'le port %s est déjà utilisé sur cette machine : choisissez-en un autre avec --port N' ;;
    udp_busy) m 'le port UDP %s est déjà utilisé sur cette machine : choisissez-en un autre avec --vpn-port N' ;;
    network_other) m 'le réseau Docker %s existe avec une autre plage d’adresses (%s) ; déplacez les apps de la zone Administration dans une autre zone (ou passez-la en « Non reliées »), puis supprimez-le (docker network rm %s), ou utilisez --access lan' ;;
    overlap) m 'le réseau de cette machine chevauche %s (les adresses du VPN d’administration) : utilisez --access lan' ;;
    public_warn) m 'Le panel écoutera sur toutes les adresses de cette machine, Internet compris.\n!! Hivora pilote Docker (root sur cette machine) ; Docker contourne UFW : le pare-feu\n   ne le protège pas. La double authentification sera obligatoire pour tous les comptes.' ;;
    public_needs_understand) m '--access public avec --yes demande --i-understand' ;;
    backing_up) m 'Sauvegarde du panel (base, clé, options)...' ;;
    backup_failed) m 'la sauvegarde du panel a échoué ; rien n’a été modifié.' ;;
    backup_done) m 'Sauvegarde : %s' ;;
    no_backup) m 'Hivora ne tourne pas : pas de sauvegarde maintenant (une migration en attente est sauvegardée au démarrage).' ;;
    downloading) m 'Téléchargement de Hivora %s...' ;;
    cannot_download) m 'impossible de télécharger %s' ;;
    preparing) m 'Préparation du panel...' ;;
    prepare_failed) m 'le panel n’a pas pu être préparé (voir ci-dessus)%s' ;;
    creating_network) m 'Création du réseau d’administration %s...' ;;
    starting) m 'Démarrage de Hivora %s...' ;;
    not_started) m 'Hivora n’a pas démarré ; voir : docker logs %s%s' ;;
    waiting_vpn) m 'Préparation du VPN d’administration (la première fois, WireGuard est téléchargé)...' ;;
    vpn_late) m 'le VPN d’administration n’est pas encore prêt ; plus tard : docker exec %s python -m hivora admin-vpn (et docker logs %s)' ;;
    rescue_not_running) m 'Hivora ne tourne pas ici : rien à secourir.' ;;
    rescue_keys) m 'Nouvelles clés pour le client du VPN d’administration (l’ancien admin.conf ne marche plus)...' ;;
    rescue_no_conf) m 'pas de nouvel admin.conf : voir docker logs %s' ;;
    rescue_import) m 'Importez-le dans l’app WireGuard, puis ouvrez https://%s:8443' ;;
    go_back) m '\n  Pour revenir en arrière : docker rm -f %s' ;;
    go_back_tar) m ' ; rm -f %s/hivora.db-wal %s/hivora.db-shm ; tar -xzf %s -C %s' ;;
    go_back_version) m ' ; puis relancez ce script avec --version %s' ;;
    dry_done) m 'Simulation : rien n’a été modifié.' ;;
    unchanged_access) m 'Accès : %s (inchangé ; pour le changer : --reconfigure)' ;;
    reconf_tty) m '--reconfigure pose des questions : lancez-le dans un terminal, sans --yes (ou utilisez --access)' ;;
    reconf_nothing) m 'rien n’est encore installé ici : lancez l’installation sans --reconfigure' ;;
    yes_no) m '[O/n]' ;;
    no_yes) m '[o/N]' ;;
    mode_lan) m 'Réseau local uniquement' ;;
    mode_vpnlan) m 'Réseau local + VPN' ;;
    mode_vpn) m 'Uniquement par le VPN' ;;
    mode_public) m 'Internet (avancé)' ;;
    menu_title) m 'Comment accéderez-vous au panel ?' ;;
    machine_private) m 'Cette machine : %s (réseau privé)' ;;
    machine_public) m 'Cette machine : %s (adresse PUBLIQUE, aucun réseau privé trouvé)' ;;
    tag_simplest) m 'le plus simple' ;;
    tag_recommended) m '[recommandé]' ;;
    tag_private) m 'le plus discret' ;;
    tag_not_recommended) m 'déconseillé' ;;
    tag_unavailable) m 'indisponible : pas de réseau local ici' ;;
    desc_lan) m '%s depuis votre réseau. Rien à régler sur la box.' ;;
    desc_vpnlan) m 'Comme 1, plus un VPN WireGuard pour y accéder de partout.\n       Il faudra ouvrir un port UDP sur votre box et scanner un QR code (dans le panel).' ;;
    desc_vpn) m 'Aucun port du panel sur le réseau. Sans le client VPN,\n       personne (vous compris) ne peut ouvrir le panel.' ;;
    desc_public) m 'Le panel écoute sur toutes les adresses. La double authentification\n       devient obligatoire pour tous les comptes.' ;;
    vps_explain) m 'Les choix 1 et 2 publieraient le panel sur %s, donc sur Internet,\n  sans les protections du mode Internet (double authentification obligatoire).' ;;
    your_choice) m 'Votre choix [%s] : ' ;;
    invalid_choice) m 'Choix invalide : tapez 1, 2, 3 ou 4.' ;;
    unavailable_choice) m 'Ce choix n’est pas disponible sur cette machine.' ;;
    addr_detected) m 'Adresse publique détectée pour le VPN :' ;;
    addr_current) m 'Adresse publique actuelle du VPN :' ;;
    addr_help) m 'Vos appareils s’y connecteront depuis l’extérieur (port UDP %s).\n  Si vous avez un nom de domaine (ex. maison.example.org), répondez « n ».' ;;
    addr_correct) m 'Est-ce correct ?' ;;
    addr_not_detected) m 'Adresse publique non détectée (pas d’accès à Internet ?).' ;;
    addr_prompt) m 'Adresse IP ou nom de domaine pour le VPN : ' ;;
    addr_invalid) m '« %s » n’est ni une adresse IP ni un nom de domaine valide.' ;;
    addr_noresolve) m '%s ne se résout pas (ou pas vers %s).\n   Le VPN ne marchera qu’une fois ce nom en place. On le garde ?' ;;
    vpn_moves) m 'L’adresse du VPN d’administration change : %s → %s\n   Les appareils déjà configurés gardent leurs clés : corrigez « Endpoint » dans\n   l’app WireGuard, ou réimportez la configuration (QR code : docker exec hivora python -m hivora admin-vpn, ou dans le panel).' ;;
    vpn_drop) m 'Le VPN redémarre : il est coupé quelques secondes, pour tous les appareils.' ;;
    confirm_vpn) m 'Uniquement par le VPN : il faudra l’app WireGuard et le QR code affiché\n   à la fin. Gardez ce terminal ouvert jusqu’à ce que la connexion marche.\n   Secours sur cette machine : relancez l’installation avec --access lan.' ;;
    confirm_vpn_switch) m 'Passer en « Uniquement par le VPN » : avez-vous déjà ouvert le panel\n   par le VPN au moins une fois ? Sinon vous ne pourrez plus y accéder.' ;;
    type_word) m 'Tapez %s pour confirmer : ' ;;
    leave_vpn) m 'Sans VPN : l’app « Admin VPN » reste installée mais n’est plus protégée ;\n   supprimez-la depuis le panel si vous n’en voulez plus.' ;;
    to_public) m 'Mode Internet : chaque compte sans double authentification devra\n   l’activer à sa prochaine connexion.' ;;
    recap_title) m 'Hivora %s va être installé :' ;;
    recap_access) m 'Accès' ;;
    recap_panel) m 'Panel' ;;
    recap_through) m '(par le VPN)' ;;
    recap_vpn) m 'VPN' ;;
    recap_vpn_line) m 'port UDP %s, adresse publique %s' ;;
    recap_was) m ' (avant : %s)' ;;
    recap_vpn_auto) m 'détectée par le panel' ;;
    recap_data) m 'Données' ;;
    recap_volumes) m 'Volumes des apps' ;;
    recap_tz) m 'Fuseau' ;;
    recap_update) m 'Le Hivora existant sera sauvegardé puis remplacé (les apps continuent de tourner).' ;;
    continue) m 'Continuer ?' ;;
    ready) m 'HIVORA EST PRÊT' ;;
    f_url) m 'URL :' ;;
    f_user) m 'Utilisateur :' ;;
    f_password) m 'Mot de passe :' ;;
    f_unchanged) m 'inchangé (oublié : docker exec %s python -m hivora reset-admin-password)' ;;
    f_once) m 'Affiché une seule fois : notez-le, puis effacez l’écran (clear).\nVous choisirez votre propre mot de passe à la première connexion.' ;;
    f_cert) m 'Le certificat est auto-signé : votre navigateur vous avertira une fois, c’est normal.' ;;
    f_lan_later) m 'Accès à distance plus tard : relancez l’installation avec --reconfigure (ajoute le VPN).' ;;
    f_vpn_available) m 'VPN d’administration : disponible (optionnel)' ;;
    f_vpn_updating) m 'VPN d’administration : nouvelle adresse, admin.conf en cours de mise à jour (quelques instants)' ;;
    f_vpn_setup) m 'VPN d’administration : en préparation (optionnel, quelques minutes la première fois)' ;;
    f_through) m '  Par le VPN :  https://%s:8443' ;;
    f_file) m '  Fichier :     %s' ;;
    f_qr) m '  QR code :     docker exec %s python -m hivora admin-vpn' ;;
    f_qr_panel) m '  QR code :     docker exec %s python -m hivora admin-vpn   (ou dans le panel : Admin VPN)' ;;
    f_udp) m '  Pour l’utiliser de l’extérieur : ouvrez le port UDP %s de votre box vers cette machine.' ;;
    f_steps) m 'Accès par le VPN, pas à pas :' ;;
    f_step1) m '  1. Installez l’app WireGuard (téléphone ou ordinateur).' ;;
    f_step2) m '  2. Ouvrez le port UDP %s de votre box vers cette machine.' ;;
    f_step3) m '  3. Scannez ce QR code (ou importez %s).' ;;
    f_step4) m '  4. Activez le tunnel, puis ouvrez https://%s:8443' ;;
    f_again) m 'Le revoir : docker exec %s python -m hivora admin-vpn' ;;
    f_newkeys) m 'Nouvelles clés : relancez l’installation avec --rescue-admin' ;;
    f_fallback) m 'Secours sur cette machine : relancez l’installation avec --access lan' ;;
    f_public) m 'Panel joignable depuis Internet : la double authentification vous sera demandée\n   juste après votre premier changement de mot de passe.' ;;
    f_options) m 'Options gardées dans %s.\nJournaux : docker logs %s\nDésinstaller : docker rm -f %s (les apps et %s restent)' ;;
    error) m 'Erreur :' ;;
    installing_docker) m 'Installation de Docker (get.docker.com), quelques minutes...' ;;
    wt_yes) m 'Oui' ;;
    wt_no) m 'Non' ;;
    wt_ok) m 'OK' ;;
    wt_cancel) m 'Annuler' ;;
    steps_title) m 'Installation' ;;
  esac
}

t() {  # t KEY [ARGS]: the message in the chosen language, formatted
  key="$1"; shift
  if [ "$UI_LANG" = "fr" ]; then fmt="$(msg_fr "$key")"; else fmt="$(msg_en "$key")"; fi
  # shellcheck disable=SC2059  # the format is one of the messages above, never user input
  printf -- "$fmt" "$@"  # --: some messages start with an option name
}

colours() {  # colours on|off: on a terminal only (a redirected output, NO_COLOR, TERM=dumb: none)
  B="" D="" N="" R="" G="" Y="" C=""
  { [ "$1" = on ] && [ -t 1 ] && [ -t 2 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-dumb}" != "dumb" ]; } \
    || return 0
  B="$(printf '\033[1m')" D="$(printf '\033[2m')" N="$(printf '\033[0m')" R="$(printf '\033[1;31m')"
  G="$(printf '\033[1;32m')" Y="$(printf '\033[1;33m')" C="$(printf '\033[1;36m')"
}
colours on

logo() {
  cat <<'EOF'
 _   _ ___ __     __  ___   ____      _
| | | |_ _|\ \   / / / _ \ |  _ \    / \
| |_| || |  \ \ / / | | | || |_) |  / _ \
|  _  || |   \ V /  | |_| ||  _ <  / ___ \
|_| |_|___|   \_/    \___/ |_| \_\/_/   \_\
EOF
  printf '\n%28s\n' "made by HiidenOPS"
}

banner() {  # the logo, on a cleared screen
  [ -z "${CLEAR:-}" ] || printf '\033[H\033[2J'
  printf '\n%s' "$C"; logo | sed 's/^/  /'; printf '%s' "$N"
}

emit() {  # emit PREFIX INDENT TEXT: the first line after PREFIX, the next ones after INDENT
  # In a window, one paragraph: whiptail wraps it to its width.
  if [ -n "$WT" ]; then printf '%s%s\n' "$1" "$(flat "$3")"; return 0; fi
  first=1
  printf '%s\n' "$3" | while IFS= read -r l; do
    if [ -n "$first" ]; then printf '%s%s%s\n' "$1" "$l" "$N"; first=""
    else printf '%s%s%s\n' "$2" "${l#"${l%%[! ]*}"}" "$N"; fi  # its own indent dropped
  done
}

pad() {  # pad TEXT WIDTH: printf %-Ns counts bytes, an accent is two
  n="$(printf '%s' "$1" | LC_ALL=C tr -d '\200-\277' | wc -c)"
  printf '%s%*s' "$1" "$(( $2 > n ? $2 - n : 0 ))" ""
}

title() {  # title TEXT [COLOUR]: a new screen; with whiptail, the next window's title
  if [ -n "$WT" ]; then WT_TITLE="$1"; return 0; fi
  [ -z "${CLEAR:-}" ] || printf '\033[H\033[2J'  # scrollback kept: earlier screens stay above
  heading "$@"
}

heading() {  # heading TEXT [COLOUR]
  printf '\n  %s%s%s\n  %s──────────────────────────────────────────────%s\n' "${2:-$B}" "$1" "$N" "$D" "$N"
}

row() { printf '    %s%s%s %s\n' "$D" "$(pad "$1" 17)" "$N" "$2"; }  # row LABEL VALUE

say() {  # a step (on the steps screen with whiptail), or a note
  if [ -n "$STEPS" ] && step_screen "$1"; then return 0; fi
  emit "  $C▸$N $D$(step_number "$1")$N" "    " "$(t "$@")"
}
warn() {  # during the steps with whiptail: kept for the final screen
  if [ -n "$WT" ] && [ -n "$STEPS" ]; then LATE="${LATE:+$LATE
}$(t "$@")"; return 0; fi
  emit "  $Y!$N " "    " "$(t "$@")" >&2
}
die() {
  if [ -n "$WT" ]; then  # back to the terminal: the error, after what the steps printed
    end_wt; printf '\033[H\033[2J'
    [ -z "$STEPS" ] || tail -n 30 "$BUF" >&2
  fi
  emit "  $R✗ $(t error)$N " "    " "$(t "$@")" >&2; exit 1
}
line() { emit "  " "  " "$(t "$@")"; }

# --- whiptail: windows for the questions and the steps, on a terminal that has it ---------
# Everything printed meanwhile goes to $BUF: the next window shows it above its question,
# the steps' output is shown only on a failure. Without whiptail (--yes, no terminal,
# HIVORA_UI=text, the tests): the same screens as text.
WT="" STEPS="" LATE="" WT_TITLE=""
TTY_OUT="${HIVORA_TTY_OUT:-/dev/tty}"  # where the windows are drawn (tests: a file)

start_wt() {
  case "${HIVORA_UI:-}" in
    text) return 0 ;;
    whiptail) ;;
    *) [ -t 1 ] && [ "${TERM:-dumb}" != "dumb" ] && command -v whiptail >/dev/null 2>&1 || return 0
       # `curl | sudo sh`: sudo (use_pty) leaves the user's terminal line by line when its
       # input is a pipe; the arrow keys would never reach the window. Text questions work.
       [ -t 0 ] || [ -z "${SUDO_USER:-}" ] || return 0 ;;
  esac
  size="$(stty size <&3 2>/dev/null || true)"
  rows="${size% *}" cols="${size#* }"
  matches "$rows $cols" '[0-9]+ [0-9]+' || { rows=24 cols=80; }
  WT_H=$((rows - 4)); [ "$WT_H" -le 30 ] || WT_H=30
  WT_W=$((cols - 4)); [ "$WT_W" -le 78 ] || WT_W=78
  BUF="$(mktemp)"
  trap 'rm -f "$BUF"' EXIT
  WT=1
  colours off  # the windows' text is plain
  exec 6>&1 7>&2 >>"$BUF" 2>&1
}

end_wt() {  # back to the terminal for the final screen
  [ -n "$WT" ] || return 0
  exec 1>&6 2>&7
  WT=""
  colours on
  [ -z "$DRY" ] || grep '^+ ' "$BUF" >&2 || true  # --dry-run: the commands
}

wt() {  # wt WHIPTAIL_ARGS: a window on the terminal, the answer on stdout
  TERM="${WT_TERM:-${TERM:-dumb}}" LC_ALL=C.UTF-8 whiptail --backtitle "Hivora · made by HiidenOPS" \
    --title " ${WT_TITLE:-Hivora} " --yes-button "$(t wt_yes)" --no-button "$(t wt_no)" \
    --ok-button "$(t wt_ok)" --cancel-button "$(t wt_cancel)" "$@" 2>&1 >"$TTY_OUT" <&3
}

wt_text() {  # wt_text QUESTION: what was printed since the last window, then QUESTION
  before="$(sed '/./,$!d' "$BUF")"; : >"$BUF"
  if [ -n "$before" ]; then printf '\n%s\n\n%s' "$before" "$1"; else printf '\n%s' "$1"; fi
}

wt_height() {  # wt_height TEXT EXTRA: the text's lines, as wrapped, plus EXTRA, within the terminal
  lines="$(printf '%s\n' "$1" | awk -v w=$((WT_W - 6)) '{ n += length($0) ? int((length($0) + w - 1) / w) : 1 } END { print n }')"
  h=$((lines + $2 + 2))
  [ "$h" -le "$WT_H" ] || h="$WT_H"
  printf '%s' "$h"
}

wt_info() {  # wt_info TEXT: a window that stays while the work goes on
  # TERM=ansi: an xterm's alternate screen would erase it as soon as whiptail exits.
  WT_TERM=ansi wt --infobox "$1" "$(wt_height "$1" 4)" "$WT_W" || true
  WT_TERM=""
}

step_label() {
  case "$1" in
    downloading|starting) t "$1" "$VERSION" ;;
    creating_network) t creating_network "$ADMIN_NETWORK" ;;
    *) t "$1" ;;
  esac
}

step_number() {  # step_number KEY: "[2/5] " for a step, nothing otherwise
  i=0
  for key in $STEPS; do
    i=$((i + 1))
    [ "$key" != "$1" ] || { printf '[%s/%s] ' "$i" "$(echo "$STEPS" | wc -w)"; return 0; }
  done
}

step_screen() {  # step_screen KEY: with whiptail, the steps done, KEY and the next ones
  [ -n "$WT" ] && [ -n "$(step_number "$1")" ] || return 1
  text="$(logo)
" mark="✓"
  for key in $STEPS; do
    if [ "$key" = "$1" ]; then text="$text
   ▸ $(step_label "$key")"; mark="·"
    else text="$text
   $mark $(step_label "$key")"; fi
  done
  WT_TITLE="$(t steps_title)" wt_info "$text"
}

# --- questions (terminal only, never with --yes) -------------------------------------------
open_tty() {  # one channel for every answer (fd 3): reopening would read the first line again
  TTY=""
  [ -z "$YES" ] || return 0
  if (exec 3<"$TTY_DEVICE") 2>/dev/null; then
    exec 3<"$TTY_DEVICE"
    TTY=1
    [ ! -t 1 ] || [ -z "$C" ] || CLEAR=1  # a terminal that takes escape codes
  fi
}

reply() {  # reply PROMPT_KEY [ARGS]: one answer line, in REPLY (1: cancelled in the window)
  if [ -n "$WT" ]; then
    text="$(wt_text "$(t "$@")")"
    REPLY="$(wt --inputbox "$text" "$(wt_height "$text" 7)" "$WT_W" "")" || return 1
    return 0
  fi
  printf '  %s?%s %s%s%s' "$C" "$N" "$B" "$(t "$@")" "$N"
  if ! read -r REPLY <&3; then printf '\n'; die no_answer; fi
}

ask() {  # ask KEY y|n [ARGS] -> 0 if yes (always yes with --yes)
  key="$1" default="$2"; shift 2
  [ -n "$YES" ] && return 0
  [ -n "$TTY" ] || die need_terminal "$(t "$key" "$@")"
  if [ -n "$WT" ]; then
    text="$(wt_text "$(t "$key" "$@")")"
    if [ "$default" = "y" ]; then
      wt --yesno "$text" "$(wt_height "$text" 5)" "$WT_W" >/dev/null
    else
      wt --defaultno --yesno "$text" "$(wt_height "$text" 5)" "$WT_W" >/dev/null
    fi
    return
  fi
  if [ "$default" = "y" ]; then hint="$(t yes_no)"; else hint="$(t no_yes)"; fi
  printf '  %s?%s %s%s%s %s%s%s ' "$C" "$N" "$B" "$(t "$key" "$@")" "$N" "$D" "$hint" "$N"
  if ! read -r answer <&3; then printf '\n'; die no_answer; fi
  case "$answer" in
    "") [ "$default" = "y" ] ;;
    y|Y|yes|YES|o|O|oui|OUI) return 0 ;;
    *) return 1 ;;
  esac
}

confirm_word() {  # confirm_word WORD -> 0 when typed exactly
  reply type_word "$1" || return 1  # cancelled: back to the menu
  [ "$REPLY" = "$1" ]
}

choose_lang() {  # screen 0, before any other question
  case "${LANG:-}" in fr*) default=1 ;; *) default=2 ;; esac
  if [ -n "$WT" ]; then
    WT_TITLE="Installation"
    text="$(logo)

  Langue / Language"
    REPLY="$(wt --default-item "$default" --menu "$text" "$(wt_height "$text" 8)" "$WT_W" 2 \
      1 "Français" 2 "English")" || die cancelled
    if [ "$REPLY" = 1 ]; then UI_LANG="fr"; else UI_LANG="en"; fi
    return 0
  fi
  banner
  printf '\n    %s1)%s Français\n    %s2)%s English\n\n' "$C" "$N" "$C" "$N"
  while :; do
    printf '  %s?%s %sLangue / Language%s %s[%s]%s ' "$C" "$N" "$B" "$N" "$D" "$default" "$N"
    if ! read -r REPLY <&3; then printf '\n'; die no_answer; fi
    case "${REPLY:-$default}" in
      1) UI_LANG="fr"; return 0 ;;
      2) UI_LANG="en"; return 0 ;;
    esac
  done
}

mode_label() {
  case "$1" in
    lan) t mode_lan ;; vpn+lan) t mode_vpnlan ;; vpn) t mode_vpn ;; public) t mode_public ;;
  esac
}

is_private() {  # RFC 1918, and CGNAT (a provider's private network)
  case "$1" in
    10.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[01].*) return 0 ;;
    100.6[4-9].*|100.[7-9][0-9].*|100.1[01][0-9].*|100.12[0-7].*) return 0 ;;
  esac
  return 1
}

valid_host() {  # an IPv4, an IPv6 or a domain name
  matches "$1" '([0-9]{1,3}\.){3}[0-9]{1,3}' && return 0
  case "$1" in *:*) matches "$1" '[0-9A-Fa-f:]{2,39}' && return 0 ;; esac
  [ "${#1}" -le 253 ] && matches "$1" '([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}'
}

choose_access() {  # screen 1: the access mode (sets ACCESS); $1 = the preselected one
  ip="${LAN_IP:-?}"
  case "$1" in lan) default=1 ;; vpn+lan) default=2 ;; vpn) default=3 ;; *) default=4 ;; esac
  notice=""  # a wrong answer, shown on the redrawn screen
  while :; do
    title "Hivora $VERSION"
    if [ -n "$WT" ]; then access_window; else access_text; fi
    case "${REPLY:-$default}" in
      1|2) [ -n "$LAN_OK" ] || { notice="$(t unavailable_choice)"; continue; }
           if [ "${REPLY:-$default}" = 1 ]; then ACCESS="lan"; else ACCESS="vpn+lan"; fi ;;
      3) ACCESS="vpn" ;;
      4) ACCESS="public" ;;
      *) notice="$(t invalid_choice)"; continue ;;
    esac
    confirm_choice && return 0
  done
}

access_text() {  # the menu as text; the answer in REPLY
  if [ -n "$LAN_OK" ]; then emit "  $D" "" "$(t machine_private "$ip")"; else emit "  $Y" "" "$(t machine_public "$ip")"; fi
  printf '\n  %s%s%s\n\n' "$B" "$(t menu_title)" "$N"
  if [ -n "$LAN_OK" ]; then
    option 1 "$(t mode_lan)" "$D" "$(t tag_simplest)" "$(t desc_lan "https://$ip:$PORT")"
    option 2 "$(t mode_vpnlan)" "$G" "$(t tag_recommended)" "$(t desc_vpnlan)"
    option 3 "$(t mode_vpn)" "$D" "$(t tag_private)" "$(t desc_vpn)"
    option 4 "$(t mode_public)" "$Y" "$(t tag_not_recommended)" "$(t desc_public)"
  else
    option 1 "$(t mode_lan)" "$D" "$(t tag_unavailable)"
    option 2 "$(t mode_vpnlan)" "$D" "$(t tag_unavailable)"
    option 3 "$(t mode_vpn)" "$G" "$(t tag_recommended)"
    option 4 "$(t mode_public)" "$Y" "$(t tag_not_recommended)"
    printf '\n'; emit "  $Y" "  $Y" "$(t vps_explain "$ip")"; printf '\n'
  fi
  [ -z "$notice" ] || { emit "  $Y! " "" "$notice"; printf '\n'; notice=""; }
  reply your_choice "$default"
}

access_window() {  # the menu in a window; the answer in REPLY
  [ -z "$notice" ] || { printf '! %s\n\n' "$notice"; notice=""; }
  if [ -n "$LAN_OK" ]; then
    t machine_private "$ip"; printf '\n\n'
    printf '1) %s\n2) %s\n3) %s\n4) %s\n\n' "$(flat "$(t desc_lan "https://$ip:$PORT")")" \
      "$(flat "$(t desc_vpnlan)")" "$(flat "$(t desc_vpn)")" "$(flat "$(t desc_public)")"
    tag1="$(t tag_simplest)" tag2="$(t tag_recommended)" tag3="$(t tag_private)"
  else
    t machine_public "$ip"; printf '\n\n%s\n\n' "$(flat "$(t vps_explain "$ip")")"
    tag1="$(t tag_unavailable)" tag2="$tag1" tag3="$(t tag_recommended)"
  fi
  text="$(wt_text "$(t menu_title)")"
  REPLY="$(wt --default-item "$default" --menu "$text" "$(wt_height "$text" 10)" "$WT_W" 4 \
    1 "$(t mode_lan) — $tag1" 2 "$(t mode_vpnlan) — $tag2" 3 "$(t mode_vpn) — $tag3" \
    4 "$(t mode_public) — $(t tag_not_recommended)")" || die cancelled
}

flat() { printf '%s' "$1" | tr '\n' ' ' | tr -s ' '; }  # one line: a window wraps it

option() {  # option N LABEL TAG_COLOUR TAG [DESCRIPTION]: one line of the menu
  printf '    %s%s)%s %s%s%s %s%s%s\n' "$C" "$1" "$N" "$B" "$(pad "$2" 26)" "$N" "$3" "$4" "$N"
  [ -z "${5:-}" ] || { emit "       $D" "       $D" "$5"; printf '\n'; }
}

confirm_choice() {  # screen 3: the modes that can lock you out or expose the panel
  old="$(env_value HIVORA_ACCESS)"
  case "$old" in vpn|vpn+lan) case "$ACCESS" in lan|public) printf '\n'; warn leave_vpn ;; esac ;; esac
  case "$ACCESS" in
    vpn) [ "$old" != "vpn" ] || return 0
         printf '\n'
         if [ -n "$RECONFIGURE" ]; then warn confirm_vpn_switch; else warn confirm_vpn; fi
         confirm_word vpn ;;
    public) [ "$old" != "public" ] || return 0
         printf '\n'; warn public_warn
         [ -z "$RECONFIGURE" ] || warn to_public
         confirm_word public && CONFIRMED_PUBLIC=1 ;;
    *) return 0 ;;
  esac
}

detect_public_ip() {  # an IPv4 from the service, or nothing
  ip="$(curl -fsS -m 5 "$PUBLIC_IP_URL" 2>/dev/null || true)"
  if matches "$ip" '([0-9]{1,3}\.){3}[0-9]{1,3}'; then printf '%s' "$ip"; fi
}

choose_vpn_host() {  # screen 2: the address the VPN clients connect to (sets VPN_HOST)
  detected="$(detect_public_ip)"
  candidate="${VPN_HOST:-${CUR_HOST:-$detected}}"  # an existing VPN: its current address
  if [ -n "$candidate" ]; then
    if [ "$candidate" = "$detected" ] && [ -z "$CUR_HOST" ]; then title=addr_detected; else title=addr_current; fi
    title VPN
    printf '\n  %s\n    %s%s%s\n\n' "$(t "$title")" "$C" "$candidate" "$N"
    emit "  $D" "  $D" "$(t addr_help "$VPN_PORT")"; printf '\n'
    if ask addr_correct y; then VPN_HOST="$candidate"; return 0; fi
  else
    title VPN
    printf '\n'; emit "  $Y" "" "$(t addr_not_detected)"; printf '\n'
  fi
  while :; do
    reply addr_prompt || die cancelled
    if ! valid_host "$REPLY"; then line addr_invalid "$REPLY"; continue; fi
    case "$REPLY" in
      *:*) ;;  # an IPv6
      *[A-Za-z]*)  # a name: it should lead to this machine (a warning, it may come later)
        resolved="$(getent hosts "$REPLY" 2>/dev/null || true)"
        if [ -z "$resolved" ] || { [ -n "$detected" ] && ! printf '%s\n' "$resolved" | grep -qwF "$detected"; }; then
          ask addr_noresolve y "$REPLY" "${detected:-?}" || continue
        fi ;;
    esac
    VPN_HOST="$REPLY"
    return 0
  done
}

run() {  # a command that changes something: only shown (on stderr) with --dry-run
  if [ -n "$DRY" ]; then printf '%s+ %s%s\n' "$D" "$*" "$N" >&2; else "$@"; fi
}

usage() { sed -n '9,26p' "$0" 2>/dev/null || true; exit 2; }

# --- options -------------------------------------------------------------------------
parse_args() {
  YES="" DRY="" UNDERSTAND="" RESCUE="" RECONFIGURE=""
  OPT_VERSION="" OPT_IMAGE="" OPT_ACCESS="" OPT_PORT="" OPT_BIND="" OPT_DATA="" OPT_SRV=""
  OPT_VPN_HOST="" OPT_VPN_PORT="" OPT_LANG=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --yes|-y) YES=1 ;;
      --dry-run) DRY=1 ;;
      --i-understand) UNDERSTAND=1 ;;
      --rescue-admin) RESCUE=1 ;;
      --reconfigure) RECONFIGURE=1 ;;
      --version|--image|--access|--port|--bind|--data|--srv|--vpn-host|--vpn-port|--lang)
        [ $# -ge 2 ] || die needs_value "$1"
        case "$1" in
          --version) OPT_VERSION="$2" ;;
          --image) OPT_IMAGE="$2" ;;
          --access) OPT_ACCESS="$2" ;;
          --port) OPT_PORT="$2" ;;
          --bind) OPT_BIND="$2" ;;
          --data) OPT_DATA="$2" ;;
          --srv) OPT_SRV="$2" ;;
          --vpn-host) OPT_VPN_HOST="$2" ;;
          --vpn-port) OPT_VPN_PORT="$2" ;;
          --lang) OPT_LANG="$2" ;;
        esac
        shift ;;
      -h|--help) usage ;;
      *) die unknown_option "$1" ;;
    esac
    shift
  done
}

env_value() {  # env_value KEY: KEY="value" from install.env, read, never executed
  [ -f "$ENV_FILE" ] || return 0
  sed -n "s/^$1=\"\\([^\"]*\\)\"\$/\\1/p" "$ENV_FILE" | tail -n 1
}

matches() {  # matches VALUE REGEX (extended, whole value)
  printf '%s\n' "$1" | grep -Eqx "$2"
}

resolve() {  # command line, then install.env (or the questions), then detection and defaults
  OLD_VERSION="$(env_value HIVORA_VERSION)"
  VERSION="${OPT_VERSION:-${SCRIPT_VERSION:-$OLD_VERSION}}"
  [ -n "$VERSION" ] || die no_version
  IMAGE="${OPT_IMAGE:-$(env_value HIVORA_IMAGE)}"; IMAGE="${IMAGE:-$DEFAULT_IMAGE}"
  VPN_HOST="${OPT_VPN_HOST:-$(env_value HIVORA_VPN_HOST)}"
  VPN_PORT="${OPT_VPN_PORT:-$(env_value HIVORA_VPN_PORT)}"; VPN_PORT="${VPN_PORT:-51820}"
  PORT="${OPT_PORT:-$(env_value HIVORA_PORT)}"; PORT="${PORT:-8443}"
  SRV="${OPT_SRV:-$(env_value HIVORA_SRV)}"; SRV="${SRV:-${HIVORA_INSTALL_SRV:-/srv/hivora}}"
  LAN_IP="$(env_value HIVORA_LAN_IP)"
  [ -n "$LAN_IP" ] || LAN_IP="$(ip -4 route get 1.1.1.1 2>/dev/null \
    | awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1)}')" || true
  TZ_NAME="$(env_value HIVORA_TIMEZONE)"
  [ -n "$TZ_NAME" ] || TZ_NAME="$(timedatectl show -p Timezone --value 2>/dev/null || true)"
  [ -n "$TZ_NAME" ] || TZ_NAME="$(cat /etc/timezone 2>/dev/null || true)"
  [ -n "$TZ_NAME" ] || TZ_NAME="UTC"
  PUID="$(env_value HIVORA_PUID)"; PUID="${PUID:-${SUDO_UID:-1000}}"
  PGID="$(env_value HIVORA_PGID)"; PGID="${PGID:-${SUDO_GID:-1000}}"

  matches "$VERSION" '[A-Za-z0-9][A-Za-z0-9._-]{0,127}' || die bad_version "$VERSION"
  matches "$IMAGE" '[a-z0-9][a-z0-9._/:-]{0,254}' || die bad_image "$IMAGE"
  for port in "$PORT" "$VPN_PORT"; do
    if ! { matches "$port" '[0-9]{1,5}' && [ "$port" -ge 1 ] && [ "$port" -le 65535 ]; }; then
      die bad_port "$port"
    fi
  done
  [ -z "$VPN_HOST" ] || valid_host "$VPN_HOST" || die bad_vpn_host "$VPN_HOST"
  matches "$SRV" '/[A-Za-z0-9._/-]*' || die bad_srv
  [ -z "$LAN_IP" ] || matches "$LAN_IP" '[0-9]{1,3}(\.[0-9]{1,3}){3}' || die bad_lan "$LAN_IP"
  matches "$TZ_NAME" '[A-Za-z0-9_+/-]{1,64}' || TZ_NAME="UTC"
  if ! { matches "$PUID" '[0-9]{1,10}' && matches "$PGID" '[0-9]{1,10}'; }; then
    die bad_ids
  fi

  # A private address: a local network to publish on. Only a public one (a VPS): publishing
  # "on the LAN" would publish on the Internet without the public mode's TOTP (D13).
  LAN_OK=""
  if [ -n "$OPT_BIND" ] || { [ -n "$LAN_IP" ] && is_private "$LAN_IP"; }; then LAN_OK=1; fi
  # Default (D15): VPN + LAN on a private network, VPN only otherwise; an install from
  # before install.env stays on lan.
  if [ -n "$LAN_OK" ]; then default_access="vpn+lan"; else default_access="vpn"; fi
  [ -z "$UPDATE" ] || [ -f "$ENV_FILE" ] || default_access="lan"
  ACCESS="${OPT_ACCESS:-$(env_value HIVORA_ACCESS)}" ACCESS_KEPT=""
  if [ -n "$INTERACTIVE" ] && [ -z "$OPT_ACCESS" ]; then
    choose_access "${ACCESS:-$default_access}"
  else
    ACCESS="${ACCESS:-$default_access}"
    if [ -n "$UPDATE" ] && [ -z "$OPT_ACCESS" ] && [ -f "$ENV_FILE" ]; then
      ACCESS_KEPT=1  # said on the recap screen
    fi
  fi
  case "$ACCESS" in
    lan|vpn+lan)
      [ -n "$LAN_OK" ] || die vps_refused "${LAN_IP:-?}" "$(mode_label "$ACCESS")"
      BIND="$LAN_IP"; [ -n "$BIND" ] || [ -n "$OPT_BIND" ] || die no_lan_ip ;;
    public) BIND="0.0.0.0" ;;
    vpn) BIND="" ;;  # no port of the panel published: the admin VPN only
    *) die bad_access "$ACCESS" ;;
  esac
  [ -z "$OPT_BIND" ] || BIND="$OPT_BIND"
  [ -z "$BIND" ] || matches "$BIND" '[0-9]{1,3}(\.[0-9]{1,3}){3}' || die bad_bind "$BIND"
  case "$ACCESS" in vpn|vpn+lan) VPN=1 ;; *) VPN="" ;; esac
  current_endpoint
  if [ -n "$VPN" ] && [ -n "$INTERACTIVE" ] && [ -z "$OPT_VPN_HOST" ]; then choose_vpn_host; fi
}

current_endpoint() {  # an existing admin VPN: where its clients connect (admin.conf, read only)
  CUR_HOST="" CUR_PORT=""
  ep="$(sed -n 's/^Endpoint = //p' "$DATA/admin.conf" 2>/dev/null | head -n 1)"
  [ -n "$ep" ] || return 0
  CUR_PORT="${ep##*:}"
  CUR_HOST="${ep%:*}"; CUR_HOST="${CUR_HOST#[}"; CUR_HOST="${CUR_HOST%]}"
}

endpoint_change() {  # install.env wins (D17): the server moves the VPN; devices must follow
  ENDPOINT_CHANGED=""
  [ -n "$VPN" ] && [ -n "$CUR_HOST" ] || return 0
  OLD_ENDPOINT="$CUR_HOST:$CUR_PORT"
  new="${VPN_HOST:-$CUR_HOST}:$VPN_PORT"  # no address given: the server keeps the current one
  [ "$new" != "$OLD_ENDPOINT" ] || return 0
  ENDPOINT_CHANGED=1
  NEW_ENDPOINT="$new"  # warned about on the recap screen
}

# --- checks (nothing changed yet) --------------------------------------------------------
check_platform() {
  [ "$(uname -s)" = "Linux" ] || die linux_only
  case "$(uname -m)" in
    x86_64|amd64|aarch64|arm64) ;;
    *) die bad_arch "$(uname -m)" ;;
  esac
  [ "$(id -u)" -eq 0 ] || die need_root
}

os_value() { sed -n "s/^$1=//p" "$OS_RELEASE" 2>/dev/null | tr -d '"' | head -n 1; }

check_os() {  # Debian 12+, Ubuntu 22.04+, Raspberry Pi OS 64-bit (reports "debian")
  os_id="$(os_value ID)" version="$(os_value VERSION_ID)"
  major="${version%%.*}"
  matches "$major" '[0-9]+' || major=0
  case "$os_id" in
    debian) [ "$major" -ge 12 ] && return 0 ;;
    ubuntu) [ "$major" -ge 22 ] && return 0 ;;
  esac
  warn os_unsupported "${os_id:-?}" "$version"
  ask continue_anyway n || die cancelled
}

check_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    say no_docker
    ask install_docker n || die docker_required
    if [ -n "$DRY" ]; then
      run sh -c "curl -fsSL https://get.docker.com | sh"
      return 0
    fi
    [ -z "$WT" ] || { WT_TITLE="Docker" wt_info "$(wt_text "$(t installing_docker)")"; }
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker 2>/dev/null || true
    [ -z "$WT" ] || : >"$BUF"  # its output: not for the next window
  fi
  if docker version 2>/dev/null | grep -qi podman; then
    die podman
  fi
  server="$(docker version --format '{{.Server.Version}}' 2>/dev/null)" || die daemon_down
  major="${server%%.*}"
  if ! { matches "$major" '[0-9]+' && [ "$major" -ge 24 ]; }; then
    die docker_old "$server"
  fi
  if docker info --format '{{.SecurityOptions}}' 2>/dev/null | grep -q rootless; then
    die rootless
  fi
}

check_port() {  # free, or already Hivora's own (an update)
  [ -n "$BIND" ] || return 0  # vpn: nothing published
  busy="$(ss -ltnH "sport = :$PORT" 2>/dev/null || true)"
  [ -n "$busy" ] || return 0
  if [ -n "$UPDATE" ] && docker port "$CONTAINER" 8443/tcp 2>/dev/null | grep -q ":$PORT\$"; then
    return 0
  fi
  die port_busy "$PORT"
}

check_vpn() {  # the admin VPN: its UDP port, its fixed addresses, its network
  [ -n "$VPN" ] || return 0
  if [ -n "$(ss -lunH "sport = :$VPN_PORT" 2>/dev/null || true)" ] \
      && [ -z "$(docker ps -q --filter label=io.hivora.app=admin-vpn --filter "publish=$VPN_PORT/udp" 2>/dev/null)" ]; then
    die udp_busy "$VPN_PORT"
  fi
  subnet="$(docker network inspect "$ADMIN_NETWORK" \
    --format '{{range .IPAM.Config}}{{.Subnet}} {{end}}' 2>/dev/null || true)"
  case "$subnet" in
    ""|"$ADMIN_ZONE_SUBNET ") ;;
    *) die network_other "$ADMIN_NETWORK" "$subnet" "$ADMIN_NETWORK" ;;
  esac
  NETWORK_EXISTS="$subnet"
  nets="$ADMIN_VPN_SUBNET"  # once made, the zone's network is routed here: ours, not a clash
  [ -n "$NETWORK_EXISTS" ] || nets="$ADMIN_ZONE_SUBNET $nets"
  for net in $nets; do
    prefix="${net%.0/24}."
    if case "$LAN_IP" in "$prefix"*) true ;; *) false ;; esac \
        || ip -4 route 2>/dev/null | grep -q "^${prefix%.}[./]"; then
      die overlap "$net"
    fi
  done
}

confirm_public() {  # without the menu (which asked already)
  if [ "$ACCESS" != "public" ] || [ -n "$OPT_BIND" ] || [ -n "${CONFIRMED_PUBLIC:-}" ]; then
    return 0
  fi
  [ "$(env_value HIVORA_ACCESS)" != "public" ] || [ -n "$YES" ] || return 0  # already public
  warn public_warn
  if [ -n "$YES" ]; then
    [ -n "$UNDERSTAND" ] || die public_needs_understand
  else
    [ -n "$TTY" ] || die need_terminal public
    confirm_word public || die cancelled
  fi
}

recap() {  # screen 4
  title "$(t recap_title "$VERSION")"
  printf '\n'
  [ -z "$ACCESS_KEPT" ] || { say unchanged_access "$(mode_label "$ACCESS")"; printf '\n'; }
  row "$(t recap_access)" "$B$(mode_label "$ACCESS")$N"
  panel=""
  [ -z "$BIND" ] || panel="https://$(display_host):$PORT"
  if [ -n "$VPN" ]; then
    through="$C""https://$PANEL_IP:8443$N $D$(t recap_through)$N"
    if [ -n "$panel" ]; then
      row "$(t recap_panel)" "$C$panel$N"; row "" "$through"
    else
      row "$(t recap_panel)" "$through"
    fi
    was=""
    [ -z "$ENDPOINT_CHANGED" ] || was="$(t recap_was "$OLD_ENDPOINT")"
    row "$(t recap_vpn)" "$(t recap_vpn_line "$VPN_PORT" "${VPN_HOST:-${CUR_HOST:-$(t recap_vpn_auto)}}")$was"
  else
    row "$(t recap_panel)" "$C$panel$N"
  fi
  row "$(t recap_data)" "$DATA"; row "$(t recap_volumes)" "$SRV"
  row "$(t recap_tz)" "$TZ_NAME   ${D}PUID/PGID$N $PUID/$PGID"
  [ -z "$UPDATE" ] || { printf '\n'; emit "  $Y" "  $Y" "$(t recap_update)"; }
  if [ -n "$ENDPOINT_CHANGED" ]; then
    printf '\n'; warn vpn_moves "$OLD_ENDPOINT" "$NEW_ENDPOINT"
    warn vpn_drop  # a new revision recreates the WireGuard container, address or port alike
  fi
  printf '\n'
}

display_host() {  # the panel's address on the network (public: the LAN one, if any)
  if [ "$BIND" = "0.0.0.0" ]; then printf '%s' "${LAN_IP:-<server-ip>}"; else printf '%s' "$BIND"; fi
}

# --- steps ------------------------------------------------------------------------------
backup_panel() {  # before an update, while the old Hivora still runs
  if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" = "true" ]; then
    say backing_up
    if [ -n "$DRY" ]; then
      run docker exec "$CONTAINER" python -m hivora backup-self
    else
      BACKUP="$(docker exec "$CONTAINER" python -m hivora backup-self)" || die backup_failed
    fi
  else
    say no_backup
  fi
}

mounts() {  # the same paths inside and outside: generated compose files use host paths
  printf '%s\n' -v "$DATA:$DATA" -v "$SRV:$SRV" -e "HIVORA_DATA_DIR=$DATA" -e "HIVORA_VOLUMES_ROOT=$SRV"
}

bootstrap() {  # before the server: admin never usable as admin/admin
  say preparing
  # shellcheck disable=SC2046  # mounts() prints one word per line, no spaces in them
  if [ -n "$DRY" ]; then
    run docker run --rm $(mounts) "$IMAGE:$VERSION" python -m hivora bootstrap
    ADMIN="dry-run"
    return 0
  fi
  # shellcheck disable=SC2046
  out="$(docker run --rm $(mounts) "$IMAGE:$VERSION" python -m hivora bootstrap)" \
    || die prepare_failed "$(recovery)"
  ADMIN="$(printf '%s\n' "$out" | sed -n 's/^ADMIN=//p')"
  ADMIN_USER="$(printf '%s\n' "$out" | sed -n 's/^ADMIN_USER=//p')"
  ADMIN_PASSWORD="$(printf '%s\n' "$out" | sed -n 's/^ADMIN_PASSWORD=//p')"
}

network() {  # how the panel is reached: published port, admin VPN network (one word per line)
  [ -z "$BIND" ] || printf '%s\n' -p "$BIND:$PORT:8443"
  [ -n "$VPN" ] || return 0
  printf '%s\n' --network "$ADMIN_NETWORK" --ip "$PANEL_IP" -e "HIVORA_ADMIN_VPN_PORT=$VPN_PORT"
  [ -z "$VPN_HOST" ] || printf '%s\n' -e "HIVORA_ADMIN_VPN_HOST=$VPN_HOST"
}

start() {
  if [ -n "$VPN" ] && [ -z "$NETWORK_EXISTS" ]; then
    say creating_network "$ADMIN_NETWORK"
    run docker network create --driver bridge --subnet "$ADMIN_ZONE_SUBNET" \
      --ip-range "$ADMIN_ZONE_RANGE" --label io.hivora.zone-network=1 "$ADMIN_NETWORK" >/dev/null
  fi
  say starting "$VERSION"
  # shellcheck disable=SC2046  # network() and mounts() print one word per line
  run docker run -d --name "$CONTAINER" --restart unless-stopped \
    $(network) \
    -v /var/run/docker.sock:/var/run/docker.sock \
    $(mounts) \
    -e "HIVORA_HOST_LAN_IP=$LAN_IP" -e "HIVORA_TIMEZONE=$TZ_NAME" \
    -e "HIVORA_PUID=$PUID" -e "HIVORA_PGID=$PGID" -e "HIVORA_ACCESS=$ACCESS" \
    --label io.hivora.self=true \
    "$IMAGE:$VERSION" >/dev/null
  [ -z "$DRY" ] || return 0
  wait_healthy
}

wait_healthy() {
  waited=0
  until [ "$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null)" = "healthy" ]; do
    waited=$((waited + 2))
    [ "$waited" -le "$HEALTH_TIMEOUT" ] || die not_started "$CONTAINER" "$(recovery)"
    sleep 2
  done
}

admin_conf_sum() { cksum "$DATA/admin.conf" 2>/dev/null || true; }

wait_admin_vpn() {  # until admin.conf differs from $1 (written by the server: WireGuard is a job)
  say waiting_vpn
  waited=0
  while [ "$(admin_conf_sum)" = "$1" ]; do
    waited=$((waited + 2))
    if [ "$waited" -gt "$VPN_TIMEOUT" ]; then
      warn vpn_late "$CONTAINER" "$CONTAINER"
      return 0
    fi
    sleep 2
  done
  VPN_READY=1
}

rescue_admin() {  # --rescue-admin: new keys for the admin VPN client, nothing else
  [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" = "true" ] \
    || die rescue_not_running
  say rescue_keys
  before="$(admin_conf_sum)"
  run docker exec "$CONTAINER" python -m hivora rescue-admin >/dev/null
  run docker restart "$CONTAINER" >/dev/null
  [ -z "$DRY" ] || { say dry_done; return 0; }
  wait_healthy
  wait_admin_vpn "$before"
  [ -n "${VPN_READY:-}" ] || die rescue_no_conf "$CONTAINER"
  docker exec "$CONTAINER" python -m hivora admin-vpn
  printf '\n  %s\n\n' "$(t rescue_import "$PANEL_IP")"
}

recovery() {  # how to go back, printed after a failure once the old container is gone
  [ -n "$UPDATE" ] || return 0
  t go_back "$CONTAINER"
  # The killed panel's write-ahead log belongs to the new database: never to the restored one.
  [ -z "${BACKUP:-}" ] || t go_back_tar "$DATA" "$DATA" "$BACKUP" "$DATA"
  [ -z "$OLD_VERSION" ] || t go_back_version "$OLD_VERSION"
}

write_env() {
  if [ -n "$DRY" ]; then
    run write "$ENV_FILE"
    return 0
  fi
  tmp="$ENV_FILE.tmp"
  (
    umask 077
    {
      echo "# Written by the Hivora installer: its options, read again when it is re-run."
      for key in VERSION IMAGE ACCESS PORT LAN_IP TIMEZONE PUID PGID DATA SRV VPN_HOST VPN_PORT LANG; do
        case "$key" in
          TIMEZONE) value="$TZ_NAME" ;;
          LANG) value="$UI_LANG" ;;
          *) eval "value=\${$key}" ;;  # one of the fixed names above
        esac
        printf 'HIVORA_%s="%s"\n' "$key" "$value"
      done
    } > "$tmp"
  )
  mv "$tmp" "$ENV_FILE"
}

summary() {  # the panel first (URL, account), then the VPN as the mode needs it
  if [ "$ACCESS" = "vpn" ]; then url="https://$PANEL_IP:8443"; else url="https://$(display_host):$PORT"; fi
  banner
  heading "✓ $(t ready)" "$G"
  printf '\n'
  row "$(t f_url)" "$C$url$N"
  case "$ADMIN" in
    created|secured)
      row "$(t f_user)" "$B$ADMIN_USER$N"
      row "$(t f_password)" "$Y$ADMIN_PASSWORD$N"
      printf '\n'; emit "  $Y! " "    $Y" "$(t f_once)" ;;
    *) row "$(t f_password)" "$D$(t f_unchanged "$CONTAINER")$N" ;;
  esac
  printf '\n'; emit "  $D" "  $D" "$(t f_cert)"
  printf '\n'
  case "$ACCESS" in
    lan) line f_lan_later ;;
    vpn+lan)  # optional: never waited for, never a QR code here (D14)
      if [ -n "$ENDPOINT_CHANGED" ]; then
        emit "  $B" "" "$(t f_vpn_updating)"; line f_through "$PANEL_IP"; line f_file "$DATA/admin.conf"
        line f_qr "$CONTAINER"
      elif [ -f "$DATA/admin.conf" ]; then
        emit "  $B" "" "$(t f_vpn_available)"; line f_through "$PANEL_IP"; line f_file "$DATA/admin.conf"
        line f_qr "$CONTAINER"
      else
        emit "  $B" "" "$(t f_vpn_setup)"; line f_through "$PANEL_IP"; line f_qr_panel "$CONTAINER"
      fi
      line f_udp "$VPN_PORT" ;;
    vpn)  # the only way in (waited for by main): the steps and the QR code, last
      printf '\n'; emit "  $B" "" "$(t f_steps)"
      line f_step1; line f_step2 "$VPN_PORT"; line f_step3 "$DATA/admin.conf"; line f_step4 "$PANEL_IP"
      printf '\n'
      if [ -n "${VPN_READY:-}" ]; then
        docker exec "$CONTAINER" python -m hivora admin-vpn | sed 1d
      fi
      line f_again "$CONTAINER"; line f_newkeys; line f_fallback ;;
    public) emit "  $R!! " "     $R" "$(t f_public)" ;;
  esac
  [ -z "$LATE" ] || { printf '\n'; emit "  $Y! " "    $Y" "$LATE"; }  # warned during the steps
  [ -z "${BACKUP:-}" ] || { printf '\n'; line backup_done "$BACKUP"; }  # the steps screen is gone
  printf '\n'; emit "  $D" "  $D" "$(t f_options "$ENV_FILE" "$CONTAINER" "$CONTAINER" "$SRV")"; printf '\n'
}

main() {
  parse_args "$@"
  if [ -n "$OPT_LANG" ]; then
    case "$OPT_LANG" in fr|en) UI_LANG="$OPT_LANG" ;; *) die bad_lang "$OPT_LANG" ;; esac
  fi
  DATA="${OPT_DATA:-${HIVORA_INSTALL_DATA:-/opt/hivora/data}}"
  matches "$DATA" '/[A-Za-z0-9._/-]*' || die bad_data
  ENV_FILE="$DATA/install.env"
  saved_lang="$(env_value HIVORA_LANG)"
  if [ -z "$OPT_LANG" ]; then
    case "$saved_lang" in fr|en) UI_LANG="$saved_lang" ;; esac
  fi
  UPDATE=""
  docker container inspect "$CONTAINER" >/dev/null 2>&1 && UPDATE=1
  open_tty
  # Questions: a new install in a terminal, or --reconfigure; never with --yes.
  INTERACTIVE=""
  if [ -n "$RECONFIGURE" ]; then
    [ -n "$TTY" ] || die reconf_tty
    [ -n "$UPDATE" ] || [ -f "$ENV_FILE" ] || die reconf_nothing
    INTERACTIVE=1
  elif [ -n "$TTY" ] && [ -z "$UPDATE" ] && [ ! -f "$ENV_FILE" ] && [ -z "$RESCUE" ]; then
    INTERACTIVE=1
  fi
  [ -z "$TTY" ] || [ -n "$RESCUE" ] || start_wt  # questions on a terminal: windows
  if [ -n "$INTERACTIVE" ] && [ -z "$OPT_LANG" ] && [ -z "$saved_lang" ]; then choose_lang; fi
  check_platform
  if [ -n "$RESCUE" ]; then
    rescue_admin
    return 0
  fi
  resolve
  check_os
  check_docker
  check_port
  check_vpn
  endpoint_change
  confirm_public
  recap
  ask continue y || die cancelled
  title "$(t steps_title)"
  STEPS="downloading"
  [ -z "$UPDATE" ] || STEPS="$STEPS backing_up"
  STEPS="$STEPS preparing"
  [ -z "$VPN" ] || [ -n "$NETWORK_EXISTS" ] || STEPS="$STEPS creating_network"
  STEPS="$STEPS starting"
  [ "$ACCESS" != "vpn" ] || [ -n "$DRY" ] || STEPS="$STEPS waiting_vpn"

  run mkdir -p "$DATA" "$SRV"
  run chmod 700 "$DATA"
  say downloading "$VERSION"
  run docker pull "$IMAGE:$VERSION" || docker image inspect "$IMAGE:$VERSION" >/dev/null 2>&1 \
    || die cannot_download "$IMAGE:$VERSION"
  BACKUP=""
  if [ -n "$UPDATE" ]; then
    backup_panel
    run docker rm -f "$CONTAINER" >/dev/null
  fi
  bootstrap
  BEFORE_START="$(admin_conf_sum)"  # an address change: wait for the rewritten admin.conf
  start
  write_env
  if [ -n "$DRY" ]; then
    end_wt
    say dry_done
    return 0
  fi
  if [ "$ACCESS" = "vpn" ]; then  # the only way in: wait for it, on the steps screen
    if [ -n "$ENDPOINT_CHANGED" ]; then wait_admin_vpn "$BEFORE_START"; else wait_admin_vpn ""; fi
  fi
  end_wt
  summary
}

main "$@"
